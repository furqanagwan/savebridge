"""The Blood of Dawnwalker (Steam app 3751260, Xbox package NAMCOBANDAIGamesInc.TheBloodofDawnwalker).

Each save is three files, byte-identical on both platforms apart from naming:

    Steam  %LOCALAPPDATA%/Dawnwalker/Saved/SaveGames/<Name>.sav / .meta / .png   (per PC)
    Xbox   container <Name>, blobs Data / Meta / SaveIcon

<Name> is ManualSave<N>, Autosave<N> or FinalAutosave. The .sav is Rebel
Wolves' chunked DSAV format (no account ID, and it doesn't record its own slot
name). The .meta is JSON the load menu reads: day, play time, date, build and
save version, plus SaveName/Type/TypeString, which must match the slot. So
moving a save to another slot rewrites only those three meta fields.

The Xbox-only RebelSettings container (settings) is left alone.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from ..platforms import LOCALAPPDATA, Account
from .base import Game, ReadResult, Save, SaveError

NAME = re.compile(r'ManualSave\d+|Autosave\d+|FinalAutosave')
EXT_TO_BLOB = {'.sav': 'Data', '.meta': 'Meta', '.png': 'SaveIcon'}
BLOB_TO_EXT = {v: k for k, v in EXT_TO_BLOB.items()}
TYPES = {'Manual': 0, 'Auto': 1, 'FinalAuto': 2}


def meta_of(save: Save) -> dict:
    try:
        return json.loads(save.parts['Meta'])['Meta']
    except (KeyError, ValueError) as e:
        raise SaveError(f'{save.key}: unreadable .meta ({e})') from None


def _created(meta_bytes: bytes) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(json.loads(meta_bytes)['Meta']['Date'], '%Y.%m.%d-%H.%M.%S')
    except (KeyError, ValueError):
        return None


def _set_meta(meta: bytes, field: str, value) -> bytes:
    """Replace one field in place, keeping the game's formatting (tabs, CRLF)."""
    new = json.dumps(value).encode()
    out, n = re.subn(rb'("%s":\s*)("[^"]*"|-?\d+)' % field.encode(), lambda m: m.group(1) + new, meta)
    if n != 1:
        raise SaveError(f'.meta has no single "{field}" field')
    return out


class Dawnwalker(Game):
    id = 'dawnwalker'
    name = 'The Blood of Dawnwalker'
    verified = ('steam-to-xbox',)
    steam_app_id = 3751260
    xbox_package_prefix = 'NAMCOBANDAIGamesInc.TheBloodofDawnwalker_'
    process_prefixes = ('dawnwalker',)
    steam_per_account = False

    def key_order(self, key: str) -> tuple:
        m = re.fullmatch(r'([A-Za-z]+?)(\d*)', key)
        kind = {'ManualSave': 0, 'Autosave': 1, 'FinalAutosave': 2}.get(m.group(1), 3)
        return (kind, int(m.group(2) or 0))

    def slot_key(self, n: int) -> str:
        return f'ManualSave{n}'

    def describe(self, save: Save) -> str:
        try:
            m = meta_of(save)
        except SaveError:
            return 'no .meta'
        return f'day {m.get("Day")}, {m.get("PlayTime", 0) / 3600:.1f} h, {m.get("TypeString", "?")}'

    def _save(self, key: str, parts: dict[str, bytes], source: str) -> Save:
        return Save(key, parts, source, _created(parts['Meta']) if 'Meta' in parts else None)

    def _check(self, key: str, parts: dict[str, bytes]) -> None:
        if 'Data' not in parts or 'Meta' not in parts:
            raise SaveError(f'{key}: needs both .sav and .meta')
        if parts['Data'][:4] != b'DSAV':
            raise SaveError(f'{key}: .sav is not a Dawnwalker save')
        name = meta_of(Save(key, parts)).get('SaveName')
        if name != key:
            raise SaveError(f'{key}: .meta says it is {name}')

    # ---- Steam ----------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return LOCALAPPDATA / 'Dawnwalker' / 'Saved' / 'SaveGames'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        groups: dict[str, dict[str, bytes]] = {}
        for f in root.iterdir():
            if f.is_file() and f.suffix in EXT_TO_BLOB and NAME.fullmatch(f.stem):
                groups.setdefault(f.stem, {})[EXT_TO_BLOB[f.suffix]] = f.read_bytes()
        r = ReadResult()
        for key, parts in groups.items():
            try:
                self._check(key, parts)
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            r.saves[key] = self._save(key, parts, str(root))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for blob, ext in BLOB_TO_EXT.items():
            p = root / f'{save.key}{ext}'
            if blob not in save.parts:
                p.unlink(missing_ok=True)  # don't leave another save's screenshot behind
                continue
            tmp = p.with_name(p.name + '.tmp')
            tmp.write_bytes(save.parts[blob])
            os.replace(tmp, p)

    # ---- Xbox -----------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if NAME.fullmatch(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def xbox_reserved(self, key: str) -> int:
        return 1  # what the game writes for its save containers

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        self._check(container, blobs)
        return self._save(container, dict(blobs), container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {b: save.parts[b] for b in ('Data', 'Meta', 'SaveIcon') if b in save.parts}

    # ---- importing ------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        stem, dot, ext = filename.rpartition('.')
        if dot and NAME.fullmatch(stem) and f'.{ext}' in EXT_TO_BLOB:
            return Save(stem, {EXT_TO_BLOB[f'.{ext}']: data}, folder)
        parent = folder.rpartition('/')[2]  # a blob from an Xbox save folder
        if NAME.fullmatch(parent) and filename in BLOB_TO_EXT:
            return Save(parent, {filename: data}, folder.rpartition('/')[0])
        return None

    def collect(self, found: list[Save]) -> ReadResult:
        parts: dict[str, dict[str, bytes]] = {}
        source: dict[str, str] = {}
        for s in found:
            parts.setdefault(s.key, {}).update(s.parts)
            source[s.key] = s.source
        r = ReadResult()
        for key, p in parts.items():
            try:
                self._check(key, p)
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            r.saves[key] = self._save(key, p, source[key])
        return r

    def remap(self, save: Save, new_key: str) -> Save:
        if not re.fullmatch(r'ManualSave\d+', new_key):
            raise SaveError(f'saves can only be moved into a ManualSave<number> slot, not {new_key}')
        meta = save.parts['Meta']
        meta = _set_meta(meta, 'SaveName', new_key)
        meta = _set_meta(meta, 'Type', TYPES['Manual'])
        meta = _set_meta(meta, 'TypeString', 'Manual')
        return Save(new_key, {**save.parts, 'Meta': meta}, save.source, save.created)
