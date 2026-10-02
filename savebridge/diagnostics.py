"""Read-only readiness checks and reports safe to share without personal paths."""

from __future__ import annotations

from pathlib import Path

from . import core
from .games import GAMES, Game, ReadResult, SaveError
from .games.halo_campaign_evolved import (
    HaloCampaignEvolved, decode_checkpoint, ooz_path, player_mapping,
)
from .games.re_engine import ReEngineGame
from .unreal import GvasError, read_header
from .wgs import WgsError, WgsStore


def _check(code: str, ok: bool, message: str, action: str = '') -> dict:
    return {'code': code, 'status': 'pass' if ok else 'fail',
            'message': message if ok else action, 'action': '' if ok else action}


def helper_checks(game: Game) -> list[dict]:
    if isinstance(game, HaloCampaignEvolved):
        return [_check('oodle-helper', ooz_path().is_file(), 'Halo Oodle decoder is available.',
                       'Run native/build_ooz.ps1 or set SAVEBRIDGE_OOZ to your ooz executable.')]
    if isinstance(game, ReEngineGame):
        helper = Path(__file__).with_name('_native') / 'dsss_find.dll'
        return [_check('dsss-helper', helper.is_file(), 'Capcom account-key helper is available.',
                       'Build the Capcom helper with native/build.cmd.')]
    return []


def readiness(game: Game, to: str, source: str | None = None,
              steam_account: str | None = None, xbox_account: str | None = None) -> dict:
    """Check target readiness; optional source means a local-store conversion.

    Import readiness does not claim an arbitrary incoming file will be accepted.
    Selection, companion files and account binding are still validated at preview.
    """
    game = game.readonly()
    checks = helper_checks(game)
    running = any(any(p.startswith(prefix) for prefix in game.process_prefixes)
                  for p in core.running_processes())
    checks.append(_check('game-closed', not running, 'Game is closed.',
                         f'Close {game.name} before writing saves.'))
    target = None
    try:
        target = core.resolve(game, to, steam_account, xbox_account)
        if target.uses_wgs:
            WgsStore(target.io_path).index()
        # WGS requires an existing store. Loose-file destinations can be created.
        checks.append(_check('target-account', True, f'{to.capitalize()} target is available.'))
    except (SaveError, WgsError, OSError, ValueError):
        target = None
        checks.append(_check('target-account', False, f'{to.capitalize()} target is unavailable.',
                             ('Start the Xbox version and save once on your chosen profile; '
                              'select a profile if several are available.') if to == 'xbox' else
                             'Sign in to Steam and select the account you want to use.'))
    if target and to == 'xbox' and isinstance(game, (HaloCampaignEvolved, ReEngineGame)):
        if any(c['status'] == 'fail' for c in helper_checks(game)):
            checks.append(_check('target-profile', False, 'Target profile could not be checked.',
                                 'Install the native helper, then check again.'))
        else:
            try:
                if isinstance(game, HaloCampaignEvolved):
                    existing = target.read()
                    mappings = {player_mapping(decode_checkpoint(s.parts['Data']))
                                for k, s in existing.saves.items() if k.startswith('CoreSave_')}
                    valid = len(mappings) == 1
                else:
                    valid = game._xbox_id(target.account) is not None
                checks.append(_check('target-profile', valid, 'Target profile mapping is available.',
                                     'Save a solo checkpoint on this Xbox profile, close the game, '
                                     'then check again.'))
            except (SaveError, WgsError, OSError, ValueError):
                checks.append(_check('target-profile', False, 'Target profile mapping is unavailable.',
                                     'Save once in the Xbox version on this profile, close it, '
                                     'then check again.'))
    if source:
        try:
            origin = core.resolve(game, source, steam_account, xbox_account)
            found = origin.read()
            valid = bool(found.saves) and not found.warnings
            checks.append(_check('source-saves', valid, f'{source.capitalize()} saves were checked.',
                                 'Save once in the source game; use Inspect save to diagnose '
                                 'unrecognized files or import a downloaded save instead.'))
        except (SaveError, WgsError, OSError, ValueError):
            checks.append(_check('source-saves', False, 'Source saves could not be checked.',
                                 'Choose a source account with saves, or import a downloaded save.'))
    return {'game': game.id, 'to': to, 'source': source,
            'ready': all(c['status'] == 'pass' for c in checks), 'checks': checks,
            'verified': list(game.verified), 'note': game.note}


def _metadata(data: bytes) -> dict:
    if data[:8] == b'HALOCEVO':
        data = decode_checkpoint(data)
        fmt = 'HALOCEVO / Oodle / GVAS'
    elif data[:4] == b'GVAS':
        fmt = 'GVAS'
    else:
        return {'format': 'game-specific', 'decoded_bytes': len(data)}
    result = {'format': fmt, 'decoded_bytes': len(data)}
    try:
        header = read_header(data)
        result.update(engine_version=list(header.engine), package_version=header.package_version)
        # Class and branch strings can contain arbitrary user-controlled text;
        # numeric versions are sufficient for the default shareable report.
    except GvasError:
        pass
    return result


def inspect_saves(paths: list[Path], game: Game | None = None) -> dict:
    """Recognize through game adapters; reports contain no paths or raw values.

    Do not use adapter descriptions, input filenames or exception strings: they
    can embed account IDs, paths or payload fields even after simple redaction.
    """
    candidates = [g.readonly() for g in ([game] if game else GAMES.values())]
    matches: dict[str, list] = {}
    groups: dict[str, set[str]] = {}
    problems = []
    total, count, unmatched = 0, 0, 0
    limited = False
    for index, (group, name, data) in enumerate(core._iter_files(paths), 1):
        if count == 1024 or total + len(data) > 256 * 1024 * 1024:
            limited = True
            break
        total += len(data)
        count += 1
        recognized = False
        for adapter in candidates:
            try:
                save = adapter.identify(data, name)
            except (SaveError, GvasError, WgsError, OSError, ValueError):
                problems.append({'input': index, 'game': adapter.id,
                                 'message': 'A candidate save could not be validated. '
                                            'Check its format and required native helper.'})
                continue
            if save:
                recognized = True
                matches.setdefault(adapter.id, []).append(save)
                groups.setdefault(adapter.id, set()).add(adapter.import_root(group))
        if not recognized:
            unmatched += 1
    reports = []
    for adapter in candidates:
        found = matches.get(adapter.id)
        if not found:
            continue
        warnings = []
        try:
            collected = adapter.collect(found)
        except SaveError:
            collected = ReadResult()
            warnings.append('Candidate files could not be assembled into complete saves.')
        if len(groups[adapter.id]) > 1:
            warnings.append('Multiple save sets found. Import one set at a time.')
        if collected.warnings:
            warnings.append('Some companion files could not be assembled into complete saves.')
        try:
            adapter.prepare(list(collected.saves.values()), {})
        except SaveError:
            # Do not serialize arbitrary adapter exception text into shareable reports.
            warnings.append('This set needs companion files or target profile data before import.')
        reports.append({'id': adapter.id, 'name': adapter.name,
                        'verified': list(adapter.verified), 'note': adapter.note,
                        'helpers': helper_checks(adapter), 'warnings': warnings,
                        'required_companions': adapter.required_companions(list(collected.saves)),
                        'saves': [{'key': save.key,
                                   'bytes': sum(len(b) for b in save.parts.values()),
                                   'parts': len(save.parts),
                                   'metadata': [_metadata(b) for b in save.parts.values()]}
                                  for save in sorted(collected.saves.values(),
                                                     key=lambda s: adapter.key_order(s.key))]})
    return {'schema_version': 1, 'privacy': 'Paths, account IDs and save payloads are omitted.',
            'input_bytes': total,
            'inputs_examined': min(count, 1024), 'unrecognized_inputs': unmatched,
            'limited': limited, 'games': reports, 'problems': problems}


def inspection_text(report: dict) -> str:
    lines = [report['privacy'], f"Examined {report['inputs_examined']} input files."]
    for game in report['games']:
        lines.append(f"\n{game['name']} ({game['id']})")
        lines.append('Verified in game: ' + (', '.join(game['verified']) or 'none; synthetic tests only'))
        if game['note']:
            lines.append(game['note'])
        for save in game['saves']:
            formats = ', '.join(m['format'] for m in save['metadata'])
            lines.append(f"  {save['key']}: {save['bytes']:,} bytes, {formats}")
            for meta in save['metadata']:
                if 'engine_version' in meta:
                    lines.append('    Engine: ' + '.'.join(map(str, meta['engine_version']))
                                 + f"; package version: {meta['package_version']}")
        lines += ['  ' + warning for warning in game['warnings']]
        if game['required_companions']:
            lines.append('  Missing companion saves: ' + ', '.join(game['required_companions']))
        lines += ['  ' + check['action'] for check in game['helpers'] if check['status'] == 'fail']
    if not report['games']:
        lines.append('No supported saves recognized.')
    for problem in report['problems']:
        lines.append(f"Input {problem['input']} ({problem['game']}): {problem['message']}")
    if report['limited']:
        lines.append('Inspection limit reached; inspect a smaller save folder.')
    return '\n'.join(lines)
