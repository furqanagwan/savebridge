"""Command line: savebridge <command> <game> ..."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import (Target, backup_target, ensure_game_closed, resolve, scan,
                   steam_candidates)
from .games import GAMES, Game, Save, SaveError, get_game
from .platforms import active_steam_user, long_path, xbox_accounts
from .wgs import WgsError


def _other(platform: str) -> str:
    return 'xbox' if platform == 'steam' else 'steam'


def _select(game: Game, saves: dict[str, Save], args) -> list[Save]:
    if args.only:
        wanted = [k.strip().lower() for k in args.only.split(',') if k.strip()]
        missing = [k for k in wanted if k not in saves]
        if missing:
            have = ', '.join(sorted(saves, key=game.key_order)) or 'nothing'
            raise SaveError(f'not in source: {", ".join(missing)} (have: {have})')
    elif args.all:
        wanted = list(saves)
    else:
        wanted = game.default_keys(list(saves))
    return [saves[k] for k in sorted(set(wanted), key=game.key_order)]


def _apply_slot_map(game: Game, saves: list[Save], spec: str | None) -> list[Save]:
    if not spec:
        return saves
    mapping = {}
    for pair in spec.split(','):
        src, _, dst = pair.partition(':')
        src, dst = src.strip().lower(), dst.strip().lower()
        src = src if not src.isdigit() else f'slot{src}'
        dst = dst if not dst.isdigit() else f'slot{dst}'
        mapping[src] = dst
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
    for s in saves:
        note = ''
        if s.key in existing:
            note = f'  replaces {game.describe(existing[s.key])}'
        print(f'  {s.key:<10} {game.describe(s):<30} from {s.source}{note}')


def _write(game: Game, saves: list[Save], dest: Target, args) -> int:
    if not saves:
        print('Nothing to copy.')
        return 1
    print(f'\nInto {dest}\n  {dest.path}\n')
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
    if dest.platform == 'xbox':
        print('Open the game (or the Xbox app) online so the changes upload to the cloud.')
    else:
        print('If Steam reports a cloud conflict on the next launch, keep the local files.')
    return 0


# ---- commands ----------------------------------------------------------------

def cmd_games(args) -> int:
    for g in GAMES.values():
        print(f'{g.id:<14} {g.name}  (Steam app {g.steam_app_id}, Xbox {g.xbox_package_prefix}*)')
    return 0


def cmd_accounts(args) -> int:
    game = get_game(args.game)
    active = active_steam_user()
    print('Steam accounts:')
    for a in steam_candidates(game):
        flags = []
        if a.steamid64 == active:
            flags.append('signed in now')
        if game.steam_dir(a).is_dir():
            flags.append('has saves')
        print(f'  {a}' + (f'  [{", ".join(flags)}]' if flags else ''))
    print('Xbox accounts:')
    for a in xbox_accounts(game.xbox_package_prefix) or []:
        print(f'  {a}')
    if not xbox_accounts(game.xbox_package_prefix):
        print('  none (launch the Xbox version once while signed in)')
    return 0


def cmd_list(args) -> int:
    game = get_game(args.game)
    tables = {}
    for platform in ('steam', 'xbox'):
        try:
            t = resolve(game, platform, args.steam_account, args.xbox_account)
            r = t.read()
        except (SaveError, WgsError) as e:
            print(f'{platform.capitalize()}: {e}')
            tables[platform] = {}
            continue
        print(f'{t}\n  {t.path}')
        for w in r.warnings:
            print(f'  warning: {w}')
        tables[platform] = r.saves
    keys = sorted(set(tables['steam']) | set(tables['xbox']), key=game.key_order)
    print(f'\n{"save":<10} {"Steam":<30} {"Xbox":<30}')
    for k in keys:
        cells = [game.describe(tables[p][k]) if k in tables[p] else '-' for p in ('steam', 'xbox')]
        print(f'{k:<10} {cells[0]:<30} {cells[1]:<30}')
    return 0


def cmd_convert(args) -> int:
    game = get_game(args.game)
    src_platform = 'steam' if args.direction == 'steam-to-xbox' else 'xbox'
    src = resolve(game, src_platform, args.steam_account, args.xbox_account)
    dest = resolve(game, _other(src_platform), args.steam_account, args.xbox_account)
    r = src.read()
    for w in r.warnings:
        print(f'warning: {w}')
    print(f'From {src}\n  {src.path}')
    saves = _apply_slot_map(game, _select(game, r.saves, args), args.slot_map)
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
    saves = _apply_slot_map(game, _select(game, r.saves, args), args.slot_map)
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
        game.write_steam(long_path(out), s)  # Steam's loose-file layout travels well
        print(f'  {s.key:<10} {game.describe(s)}')
    print(f'Exported {len(saves)} save(s) to {out}. Anyone can bring them in with '
          f'"savebridge import {game.id} <folder> --to steam|xbox".')
    return 0


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
    writing.add_argument('--slot-map', metavar='MAP',
                         help='move slots while copying, e.g. 1:5,2:6')
    writing.add_argument('--dry-run', action='store_true', help='show the plan, write nothing')
    writing.add_argument('--force', action='store_true', help='skip the game-running check')

    sub.add_parser('games', help='list supported games')

    p = sub.add_parser('accounts', help='list Steam and Xbox accounts found for a game')
    p.add_argument('game')

    p = sub.add_parser('list', parents=[accounts], help="show a game's saves on both platforms")
    p.add_argument('game')

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

    args = ap.parse_args(argv)
    handler = {'games': cmd_games, 'accounts': cmd_accounts, 'list': cmd_list,
               'convert': cmd_convert, 'import': cmd_import, 'export': cmd_export}[args.cmd]
    try:
        return handler(args)
    except (SaveError, WgsError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
