"""savebridge save packages: one save, from any platform, for any platform.

A package is a zip holding a game's saves in savebridge's platform-neutral form
(the bytes every plugin reads into ``Save.parts``: decrypted, decompressed, no
account binding) plus ``save.json`` describing it:

    save.json                     the manifest below
    parts/<n>/<m>                 one file per part of each save

    {
      "format": "savebridge-save", "version": 1,
      "game": "witcher3",
      "title": "NG+ ready, enchanted armour", "description": "...",
      "author": "github-username",
      "platform": "steam",                 # where the save came from (PLATFORMS)
      "game_version": "4.04",
      "tested": [{"platform": "xbox-pc", "by": "name", "date": "2026-10-14", "game_version": "4.04"}],
      "saves": [{"key": "ManualSave_...", "summary": "manual save, 4.0 MB",
                 "parts": {"sav": {"file": "parts/0/0", "size": 3973138, "sha256": "..."}}}],
      "created": "2026-10-14"
    }

Because the content is platform-neutral, importing a package into Steam or Xbox
goes through the game's normal write path (re-encrypting for the receiving
account where a game needs it).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import zipfile
from pathlib import Path

from .games import Game, ReadResult, Save, SaveError

FORMAT = 'savebridge-save'
VERSION = 1
MANIFEST = 'save.json'
PLATFORMS = {
    'steam': 'Steam (PC)',
    'xbox-pc': 'Xbox app (PC)',
    'xbox-series': 'Xbox Series X|S / Xbox One',
    'ps3': 'PlayStation 3',
    'ps4': 'PlayStation 4',
    'ps5': 'PlayStation 5',
}
REQUIRED = ('game', 'title', 'author', 'platform', 'game_version')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(game: Game, saves: list[Save], meta: dict) -> tuple[bytes, dict]:
    """Zip ``saves`` with a manifest built from ``meta``. Returns (zip bytes, manifest)."""
    missing = [k for k in REQUIRED if k != 'game' and not str(meta.get(k, '')).strip()]
    if missing:
        raise SaveError(f'package needs: {", ".join(missing)}')
    if meta['platform'] not in PLATFORMS:
        raise SaveError(f'unknown platform {meta["platform"]!r}; use one of: {", ".join(PLATFORMS)}')
    manifest = {
        'format': FORMAT, 'version': VERSION, 'game': game.id,
        'title': meta['title'].strip(), 'description': (meta.get('description') or '').strip(),
        'author': meta['author'].strip(), 'platform': meta['platform'],
        'game_version': str(meta['game_version']).strip(),
        'tested': meta.get('tested') or [],
        'saves': [], 'created': dt.date.today().isoformat(),
    }
    files = {}
    for n, s in enumerate(sorted(saves, key=lambda s: game.key_order(s.key))):
        entry = {'key': s.key, 'summary': _describe(game, s), 'parts': {}}
        for m, (part, data) in enumerate(sorted(s.parts.items())):
            name = f'parts/{n}/{m}'
            files[name] = data
            entry['parts'][part] = {'file': name, 'size': len(data), 'sha256': sha256(data)}
        manifest['saves'].append(entry)
    if not manifest['saves']:
        raise SaveError('nothing to package')
    return _zip(manifest, files), manifest


def _zip(manifest: dict, files: dict[str, bytes]) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _describe(game: Game, s: Save) -> str:
    try:
        return game.describe(s)
    except Exception:  # noqa: BLE001 - a summary is optional
        return ''


def is_package(path: Path) -> bool:
    """A package zip, or a folder holding save.zip (the layout in the saves/ library)."""
    if path.is_dir():
        return (path / 'save.zip').is_file() and (path / MANIFEST).is_file()
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as z:
        if MANIFEST not in z.namelist():
            return False
        try:
            return json.loads(z.read(MANIFEST)).get('format') == FORMAT
        except ValueError:
            return False


def read(path: Path) -> tuple[dict, dict[str, bytes]]:
    """(manifest, files) of a package zip or library folder, with every part's hash checked."""
    if path.is_dir():
        path = path / 'save.zip'
    try:
        with zipfile.ZipFile(path) as z:
            manifest = json.loads(z.read(MANIFEST))
            files = {i.filename: z.read(i) for i in z.infolist() if i.filename.startswith('parts/')}
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
        raise SaveError(f'not a readable savebridge package ({e})') from None
    problems = validate(manifest, files)
    if problems:
        raise SaveError('damaged savebridge package: ' + '; '.join(problems))
    return manifest, files


def validate(manifest: dict, files: dict[str, bytes] | None = None) -> list[str]:
    """Structural problems with a manifest (and, given ``files``, with the parts)."""
    out = []
    if manifest.get('format') != FORMAT:
        return ['not a savebridge save package']
    if manifest.get('version') != VERSION:
        out.append(f'unsupported package version {manifest.get("version")}')
    for k in REQUIRED:
        if not str(manifest.get(k, '')).strip():
            out.append(f'missing {k}')
    if manifest.get('platform') not in PLATFORMS:
        out.append(f'unknown platform {manifest.get("platform")!r}')
    if not manifest.get('saves'):
        out.append('no saves listed')
    for s in manifest.get('saves', []):
        for part, info in s.get('parts', {}).items():
            if files is None:
                continue
            data = files.get(info.get('file', ''))
            if data is None:
                out.append(f'{s.get("key")}/{part}: file missing')
            elif len(data) != info.get('size') or sha256(data) != info.get('sha256'):
                out.append(f'{s.get("key")}/{part}: contents do not match the manifest')
    return out


def saves_of(game: Game, path: Path) -> tuple[dict, ReadResult]:
    """The saves inside a package, as if read from a store."""
    manifest, files = read(path)
    if manifest['game'] != game.id:
        raise SaveError(f'this package is a {manifest["game"]} save, not {game.id}')
    r = ReadResult()
    for s in manifest['saves']:
        parts = {part: files[info['file']] for part, info in s['parts'].items()}
        r.saves[s['key']] = Save(s['key'], parts, f'{manifest["title"]} by {manifest["author"]}')
    return manifest, r
