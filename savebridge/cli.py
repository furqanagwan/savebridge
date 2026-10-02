"""Command line: savebridge <command> <game> ..."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

from .core import (Target, backup_owner, backup_target, backups, ensure_game_closed,
                   read_backup, resolve, scan, steam_candidates)
from .games import GAMES, Game, Save, SaveError, get_game
from .platforms import LocalAccount, active_steam_user, long_path, xbox_accounts
from .wgs import WgsError


def _other(platform: str) -> str:
    return 'xbox' if platform == 'steam' else 'steam'


def _key(game: Game, text: str, known) -> str:
    """Resolve what the user typed: a bare number is a slot, and case doesn't matter."""
    text = text.strip()
    if text.isdigit():
        return game.slot_key(int(text))
    return next((k for k in known if k.lower() == text.lower()), text)


def _select(game: Game, saves: dict[str, Save], args) -> list[Save]:
    if args.only:
        wanted = [_key(game, k, saves) for k in args.only.split(',') if k.strip()]
        missing = [k for k in wanted if k not in saves]
        if missing:
            have = ', '.join(sorted(saves, key=game.key_order)) or 'nothing'
            raise SaveError(f'not in source: {", ".join(missing)} (have: {have})')
    elif args.all:
        wanted = list(saves)
    else:
        wanted = game.default_keys(list(saves))
    return [saves[k] for k in sorted(set(wanted), key=game.key_order)]


def _pick_files(game: Game, saves: list[Save], args) -> list[Save]:
    spec = getattr(args, 'files', None)
    return [game.pick_files(s, spec) for s in saves] if spec else saves


def _apply_slot_map(game: Game, saves: list[Save], spec: str | None) -> list[Save]:
    if not spec:
        return saves
    mapping = {}
    keys = [s.key for s in saves]
    for pair in spec.split(','):
        src, _, dst = pair.partition(':')
        mapping[_key(game, src, keys)] = _key(game, dst, [])
    out = [game.remap(s, mapping[s.key]) if s.key in mapping else s for s in saves]
    keys = [s.key for s in out]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise SaveError(f'slot map puts two saves in {", ".join(sorted(dupes))}')
    return out


def _print_plan(game: Game, saves: list[Save], dest: Target) -> None:
    try:
        existing = dest.read().saves
    except (SaveError, WgsError, OSError):
        existing = {}
    width = max([len(s.key) for s in saves] + [10])
    for s in saves:
        print(f'  {s.key:<{width}}  {game.describe(s)}')
        print(f'  {"":<{width}}  from {s.source}')
        if s.key in existing:
            print(f'  {"":<{width}}  replaces {game.describe(existing[s.key])}')


def _write(game: Game, saves: list[Save], dest: Target, args, merge: bool = True) -> int:
    if not saves:
        print('Nothing to copy.')
        return 1
    print(f'\nInto {dest}\n  {dest.path}\n')
    saves = dest.prepare(saves) if merge else [game.rebind(s, dest.account) for s in saves]
    _print_plan(game, saves, dest)
    if args.dry_run:
        print('\nDry run: nothing written.')
        return 0
    if not args.force:
        ensure_game_closed(game)
    bak = backup_target(dest)
    if bak:
        print(f'\nBacked up {dest.platform} saves to {bak}')
    dest.write(saves)
    try:
        dest.verify(saves)
    except SaveError as e:
        raise SaveError(f'{e}; restore from {bak}') from None
    print(f'Wrote and verified {len(saves)} save(s).')
    if dest.uses_wgs:
        print('Open the game (or the Xbox app) online so the changes upload to the cloud.')
    elif dest.platform == 'xbox':
        print("This game's Xbox saves are local to this PC; they don't sync to the cloud.")
    else:
        print('If Steam reports a cloud conflict on the next launch, keep the local files.')
    return 0


# ---- commands ----------------------------------------------------------------

def _emit(data) -> int:
    print(json.dumps(data, indent=1, default=str))
    return 0


def _status(g: Game) -> str:
    return 'verified in game: ' + ', '.join(g.verified) if g.verified else 'tested on synthetic saves only'


def cmd_games(args) -> int:
    if args.json:
        return _emit([{'id': g.id, 'name': g.name, 'steam_app_id': g.steam_app_id,
                       'xbox_package': g.xbox_package_prefix.rstrip('_'), 'verified': list(g.verified),
                       'note': g.note} for g in GAMES.values()])
    w = max(len(g.id) for g in GAMES.values())
    for g in GAMES.values():
        print(f'{g.id:<{w}}  {g.name}  (Steam app {g.steam_app_id}, Xbox {g.xbox_package_prefix}*)')
        print(f'{"":<{w}}  {_status(g)}' + (f' ({g.note})' if g.note else ''))
    return 0


def cmd_accounts(args) -> int:
    game = get_game(args.game)
    active = active_steam_user()
    if args.json:
        steam = [{'steamid64': a.steamid64, 'name': a.name, 'signed_in': a.steamid64 == active,
                  'has_saves': game.save_dir('steam', a).is_dir()}
                 for a in (steam_candidates(game) if game.steam_per_account else [])]
        xbox = [{'xuid': a.xuid, 'folder': str(a.folder)}
                for a in (xbox_accounts(game.xbox_package_prefix)
                          if game.xbox_uses_wgs and game.xbox_package_prefix else [])]
        return _emit({'steam_per_pc': not game.steam_per_account,
                      'xbox_per_pc': not game.xbox_uses_wgs, 'steam': steam, 'xbox': xbox})
    print('Steam accounts:')
    if not game.steam_per_account:
        print(f'  saves are per PC, in {game.save_dir("steam", LocalAccount())}')
    for a in steam_candidates(game) if game.steam_per_account else []:
        flags = []
        if a.steamid64 == active:
            flags.append('signed in now')
        if game.save_dir('steam', a).is_dir():
            flags.append('has saves')
        print(f'  {a}' + (f'  [{", ".join(flags)}]' if flags else ''))
    print('Xbox accounts:')
    if not game.xbox_uses_wgs:
        print(f'  saves are per PC, in {game.save_dir("xbox", LocalAccount())}')
        return 0
    found = xbox_accounts(game.xbox_package_prefix)
    for a in found:
        print(f'  {a}')
    if not found:
        print('  none (launch the Xbox version once while signed in)')
    return 0


def cmd_list(args) -> int:
    game = get_game(args.game)
    tables = {}
    out = {}
    for platform in ('steam', 'xbox'):
        try:
            t = resolve(game, platform, args.steam_account, args.xbox_account)
            r = t.read()
        except (SaveError, WgsError) as e:
            out[platform] = {'error': str(e), 'saves': {}}
            if not args.json:
                print(f'{platform.capitalize()}: {e}')
            tables[platform] = {}
            continue
        out[platform] = {'account': str(t.account), 'path': str(t.path), 'warnings': r.warnings,
                         'saves': {k: game.describe(v) for k, v in
                                   sorted(r.saves.items(), key=lambda kv: game.key_order(kv[0]))}}
        tables[platform] = r.saves
        if args.json:
            continue
        print(f'{t}\n  {t.path}')
        for w in r.warnings:
            print(f'  warning: {w}')
    if args.json:
        return _emit(out)
    keys = sorted(set(tables['steam']) | set(tables['xbox']), key=game.key_order)
    rows = [(k, *[game.describe(tables[p][k]) if k in tables[p] else '-' for p in ('steam', 'xbox')])
            for k in keys]
    w = [max([len(r[i]) for r in rows] + [len(h)]) for i, h in enumerate(('save', 'Steam', 'Xbox'))]
    print(f'\n{"save":<{w[0]}}  {"Steam":<{w[1]}}  Xbox')
    for k, s, x in rows:
        print(f'{k:<{w[0]}}  {s:<{w[1]}}  {x}')
    return 0


def cmd_convert(args) -> int:
    game = get_game(args.game)
    src_platform = 'steam' if args.direction == 'steam-to-xbox' else 'xbox'
    src = resolve(game, src_platform, args.steam_account, args.xbox_account)
    dest = resolve(game, _other(src_platform), args.steam_account, args.xbox_account)
    if src.path == dest.path:
        print(f'{game.name} keeps Steam and Xbox saves in the same folder in the same '
              f'format:\n  {src.path}\nBoth versions already see the same saves. To bring in '
              f'saves from elsewhere use: savebridge import {game.id} <path> --to {dest.platform}')
        return 0
    r = src.read()
    for w in r.warnings:
        print(f'warning: {w}')
    print(f'From {src}\n  {src.path}')
    saves = _apply_slot_map(game, _pick_files(game, _select(game, r.saves, args), args), args.slot_map)
    return _write(game, saves, dest, args)


def cmd_import(args) -> int:
    game = get_game(args.game)
    dest = resolve(game, args.to, args.steam_account, args.xbox_account)
    r = scan(game, [long_path(Path(p)) for p in args.paths], strict=not args.ignore_checksum)
    for w in r.warnings:
        print(f'warning: {w}')
    if not r.saves:
        print(f'No {game.name} saves found in the given paths.')
        return 1
    saves = _apply_slot_map(game, _pick_files(game, _select(game, r.saves, args), args), args.slot_map)
    return _write(game, saves, dest, args)


def cmd_export(args) -> int:
    game = get_game(args.game)
    src = resolve(game, args.source, args.steam_account, args.xbox_account)
    r = src.read()
    for w in r.warnings:
        print(f'warning: {w}')
    saves = _select(game, r.saves, args)
    out = Path(args.out)
    for s in saves:
        game.write_files('steam', long_path(out), s)  # Steam's loose-file layout travels well
        print(f'  {s.key:<14} {game.describe(s)}')
    print(f'Exported {len(saves)} save(s) to {out}. Anyone can bring them in with '
          f'"savebridge import {game.id} <folder> --to steam|xbox".')
    return 0


def cmd_check(args) -> int:
    from .diagnostics import readiness
    report = readiness(get_game(args.game), args.to, args.source,
                       args.steam_account, args.xbox_account)
    if args.json:
        # A failed check is a valid structured response, not a transport failure.
        return _emit(report)
    print(f'{report["game"]} -> {args.to}: ' + ('ready' if report['ready'] else 'needs attention'))
    for check in report['checks']:
        print(f'  {check["status"]}: {check["code"]} - '
              + (check['message'] if check['status'] == 'pass' else check['action']))
    print('Incoming saves and selections are checked again during conversion preview.')
    return 0 if report['ready'] else 1


def cmd_inspect(args) -> int:
    from .diagnostics import inspect_saves, inspection_text
    paths = [long_path(Path(p)) for p in args.paths]
    if any(not p.exists() for p in paths):
        raise SaveError('an inspection input does not exist')
    try:
        report = inspect_saves(paths, get_game(args.game) if args.game else None)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, WgsError, SaveError):
        raise SaveError('could not read an inspection input') from None
    if args.json:
        return _emit(report)
    print(inspection_text(report))
    return 0


def _pick_backup(game: Game, name: str | None):
    found = backups(game.id)
    if not found:
        raise SaveError(f'no savebridge backups for {game.name}')
    if not name or name == 'latest':
        return found[0]
    hit = [b for b in found if name in (b.path.name, b.path.stem, str(b.path))]
    if not hit:
        raise SaveError(f'no backup named {name}; see: savebridge backups {game.id}')
    return hit[0]


def cmd_backups(args) -> int:
    found = backups(get_game(args.game).id if args.game else None)
    if args.json:
        return _emit([{'game': b.game_id, 'name': b.path.name, 'path': str(b.path),
                       'time': b.when.isoformat(), 'platform': b.platform, 'account': b.who,
                       'size': long_path(b.path).stat().st_size} for b in found])
    if not found:
        print('No backups yet. savebridge makes one before every write.')
        return 0
    for b in found:
        print(f'{b.when:%Y-%m-%d %H:%M:%S}  {b.game_id:<22} {b.platform:<5} {b.who:<18} {b.path.name}')
    print('\nRestore with: savebridge restore <game> [name]   (default: the newest)')
    return 0


def cmd_restore(args) -> int:
    game = get_game(args.game)
    b = _pick_backup(game, args.backup)
    dest = backup_owner(game, b)
    r = read_backup(game, b)
    for w in r.warnings:
        print(f'warning: {w}')
    print(f'Restoring the backup from {b.when:%Y-%m-%d %H:%M:%S}\n  {b.path}')
    saves = [r.saves[k] for k in sorted(r.saves, key=game.key_order)]
    try:
        extra = sorted(set(dest.read().saves) - set(r.saves), key=game.key_order)
    except (SaveError, WgsError, OSError):
        extra = []
    rc = _write(game, saves, dest, args, merge=False)
    if extra and not args.dry_run:
        print(f'Not in the backup, left as they are: {", ".join(extra)}')
    return rc


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    ap = argparse.ArgumentParser(
        prog='savebridge',
        description='Move PC game saves between Steam and Xbox (Game Pass / Microsoft Store), '
                    'and between accounts.')
    sub = ap.add_subparsers(dest='cmd', required=True)

    accounts = argparse.ArgumentParser(add_help=False)
    accounts.add_argument('--steam-account', metavar='ID',
                          help='SteamID64 (or account ID) to read from / write to')
    accounts.add_argument('--xbox-account', metavar='XUID',
                          help='Xbox XUID (decimal, or the hex at the start of the wgs folder name)')

    choose = argparse.ArgumentParser(add_help=False)
    choose.add_argument('--only', metavar='KEYS', help='comma-separated saves, e.g. slot1,slot3,autosave')
    choose.add_argument('--all', action='store_true',
                        help='include optional saves too (e.g. profile/settings)')

    writing = argparse.ArgumentParser(add_help=False)
    writing.add_argument('--files', metavar='SPEC',
                         help="only some files of a save, for games with many per save: "
                              "'newest', 'newest:N' or comma-separated names")
    writing.add_argument('--slot-map', metavar='MAP',
                         help='move slots while copying, e.g. 1:5,2:6')
    writing.add_argument('--dry-run', action='store_true', help='show the plan, write nothing')
    writing.add_argument('--force', action='store_true', help='skip the game-running check')

    as_json = argparse.ArgumentParser(add_help=False)
    as_json.add_argument('--json', action='store_true', help='machine-readable output (for the app)')

    sub.add_parser('games', parents=[as_json], help='list supported games and how well each is tested')

    p = sub.add_parser('accounts', parents=[as_json], help='list Steam and Xbox accounts found for a game')
    p.add_argument('game')

    p = sub.add_parser('list', parents=[accounts, as_json], help="show a game's saves on both platforms")
    p.add_argument('game')

    p = sub.add_parser('check', parents=[accounts, as_json], help='check conversion prerequisites without writing')
    p.add_argument('game')
    p.add_argument('--to', required=True, choices=['steam', 'xbox'])
    p.add_argument('--from', dest='source', choices=['steam', 'xbox'],
                   help='also check a local source store; omit for downloaded-save import')

    p = sub.add_parser('inspect', parents=[as_json], help='inspect saves and produce a report safe to share')
    p.add_argument('paths', nargs='+', help='files, folders, ZIP archives or WGS stores')
    p.add_argument('--game', help='restrict recognition to one game (default: auto-detect)')

    p = sub.add_parser('convert', parents=[accounts, choose, writing],
                       help="copy saves between this PC's Steam and Xbox accounts")
    p.add_argument('game')
    p.add_argument('direction', choices=['steam-to-xbox', 'xbox-to-steam'])

    p = sub.add_parser('import', parents=[accounts, choose, writing],
                       help='bring in save files from anywhere (another account, a download, a zip)')
    p.add_argument('game')
    p.add_argument('paths', nargs='+', help='files, folders or .zip archives')
    p.add_argument('--to', required=True, choices=['steam', 'xbox'])
    p.add_argument('--ignore-checksum', action='store_true',
                   help='accept saves whose checksum is wrong (it is rewritten)')

    p = sub.add_parser('export', parents=[accounts, choose],
                       help='copy saves to a folder to share or keep')
    p.add_argument('game')
    p.add_argument('--from', dest='source', required=True, choices=['steam', 'xbox'])
    p.add_argument('--out', required=True)

    p = sub.add_parser('backups', parents=[as_json], help='list the backups made before each write')
    p.add_argument('game', nargs='?')

    p = sub.add_parser('restore', help='put a backup back (the current saves are backed up first)')
    p.add_argument('game')
    p.add_argument('backup', nargs='?', help='backup file name (default: the newest)')
    p.add_argument('--dry-run', action='store_true', help='show the plan, write nothing')
    p.add_argument('--force', action='store_true', help='skip the game-running check')

    args = ap.parse_args(argv)
    handler = {'games': cmd_games, 'accounts': cmd_accounts, 'list': cmd_list,
               'convert': cmd_convert, 'import': cmd_import, 'export': cmd_export,
               'backups': cmd_backups, 'restore': cmd_restore,
               'check': cmd_check, 'inspect': cmd_inspect}[args.cmd]
    try:
        return handler(args)
    except (SaveError, WgsError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
