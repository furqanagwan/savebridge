"""CONTROL Resonant (Steam app 3669870, Xbox package Remedy.CONTROLResonant, Play Anywhere).

Every save file is a Remedy RMDB blob, identical on both platforms:

    'RMDB'  u32 2  u32 2  u32 crc32(bytes 16..end)  payload...

A save "slot" is a set of files. Each save point in it (auto-N, key-<id>,
return) has four parts: -header (u32 Unix time at offset 20, plus the area
path), -player, -persi-global and -bundle-container. preferences holds the
settings (data) and a pointer to the save to continue from (savegame).

    Steam  Steam/userdata/<account id>/3669870/remote/<container>_<blob>
    Xbox   WGS container <container> with one blob per file, e.g. slot-0 / auto-4-header

The Xbox build also keeps an 'achievements' container with no Steam
counterpart; it is left alone. Saves carry no account ID. Because this is a
Play Anywhere title, anything written to Xbox syncs to Xbox consoles too.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import struct
import zlib
from pathlib import Path

from ..platforms import Account, SteamAccount, steam_install
from .base import Game, ReadResult, Save, SaveError

MAGIC = b'RMDB'
CONTAINER = re.compile(r'slot-\d+|preferences')
STEAM_FILE = re.compile(r'(slot-\d+|preferences)_(.+)')
PREFERENCES = 'preferences'
STEAM_ID64_BASE = 76561197960265728


def check_rmdb(data: bytes, strict: bool = True) -> None:
    """Verify an RMDB file's CRC. Other files (preferences data is raw) pass as is."""
    if data[:4] != MAGIC:
        return
    if len(data) < 16:
        raise SaveError('truncated RMDB file')
    if strict and struct.unpack_from('<I', data, 12)[0] != zlib.crc32(data[16:]):
        raise SaveError('checksum mismatch (corrupt or edited file)')


def fix_crc(data: bytes) -> bytes:
    if data[:4] != MAGIC:
        return data
    return data[:12] + struct.pack('<I', zlib.crc32(data[16:])) + data[16:]


def _saved_at(parts: dict[str, bytes]) -> dt.datetime | None:
    times = [struct.unpack_from('<I', d, 20)[0] for n, d in parts.items()
             if n.endswith('-header') and len(d) >= 24]
    return dt.datetime.fromtimestamp(max(times)) if times else None


def save_points(parts: dict[str, bytes]) -> list[str]:
    """e.g. ['auto-0', 'key-107081994', 'return']"""
    return sorted(n.removesuffix('-header') for n in parts if n.endswith('-header'))


class ControlResonant(Game):
    id = 'control-resonant'
    name = 'CONTROL Resonant'
    verified = ('steam-to-xbox',)
    steam_app_id = 3669870
    xbox_package_prefix = 'Remedy.CONTROLResonant_'
    process_prefixes = ('controlresonant',)

    def key_order(self, key: str) -> tuple:
        m = re.fullmatch(r'slot-(\d+)', key)
        return (0, int(m.group(1))) if m else (1, 0)

    def slot_key(self, n: int) -> str:
        return f'slot-{n}'

    def describe(self, save: Save) -> str:
        if save.key == PREFERENCES:
            m = re.search(rb'(slot-\d+)\x07\x00\x00\x00([a-z]+-\d*)', save.parts.get('savegame', b''))
            return f'continue: {m.group(1).decode()} {m.group(2).decode()}' if m else 'settings'
        n = len(save_points(save.parts))
        when = save.created.strftime('%Y-%m-%d %H:%M') if save.created else '?'
        return f'{n} save points, latest {when}'

    def _save(self, key: str, parts: dict[str, bytes], source: str) -> Save:
        created = _saved_at(parts) if key != PREFERENCES else None
        return Save(key, parts, source, created)

    # ---- Steam --------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        steam = steam_install()
        if steam is None or not isinstance(account, SteamAccount):
            raise SaveError('Steam is not installed')
        return steam / 'userdata' / str(account.steamid64 - STEAM_ID64_BASE) / \
            str(self.steam_app_id) / 'remote'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        groups: dict[str, dict[str, bytes]] = {}
        r = ReadResult()
        for f in sorted(root.iterdir()):
            m = STEAM_FILE.fullmatch(f.name)
            if not m or not f.is_file():
                continue
            data = f.read_bytes()
            try:
                check_rmdb(data)
            except SaveError as e:
                r.warnings.append(f'{f.name}: {e}')
                continue
            groups.setdefault(m.group(1), {})[m.group(2)] = data
        for key, parts in groups.items():
            r.saves[key] = self._save(key, parts, str(root))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        # A slot is replaced as a whole; leftover save points would mix playthroughs.
        for f in root.glob(f'{save.key}_*'):
            if f.name[len(save.key) + 1:] not in save.parts:
                f.unlink()
        for blob, data in save.parts.items():
            p = root / f'{save.key}_{blob}'
            tmp = p.with_name(p.name + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, p)

    # ---- Xbox ---------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if CONTAINER.fullmatch(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        for name, data in blobs.items():
            try:
                check_rmdb(data)
            except SaveError as e:
                raise SaveError(f'{name}: {e}') from None
        return self._save(container, dict(blobs), container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return dict(save.parts)

    # ---- importing ----------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        parent, _, container = folder.rpartition('/')
        if CONTAINER.fullmatch(container):  # a blob from an Xbox save folder
            folder, filename = parent, f'{container}_{filename}'
        m = STEAM_FILE.fullmatch(filename)
        if not m or (m.group(1) != PREFERENCES and data[:4] != MAGIC):
            return None
        check_rmdb(data, strict)
        if not strict:
            data = fix_crc(data)
        return Save(m.group(1), {m.group(2): data}, folder.removeprefix('//?/'))

    def collect(self, found: list[Save]) -> ReadResult:
        r = ReadResult()
        sources: dict[str, set[str]] = {}
        parts: dict[str, dict[str, bytes]] = {}
        for s in found:
            sources.setdefault(s.key, set()).add(s.source)
            parts.setdefault(s.key, {}).update(s.parts)
        for key, p in parts.items():
            if len(sources[key]) > 1:
                r.warnings.append(f'{key}: files came from several folders '
                                  f'({", ".join(sorted(sources[key]))}); import one at a time')
                continue
            r.saves[key] = self._save(key, p, next(iter(sources[key])))
        return r

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        out = []
        for s in saves:
            if s.key == PREFERENCES and PREFERENCES in existing and 'savegame' in s.parts:
                # Keep the target's settings; take the pointer to the imported save.
                parts = dict(existing[PREFERENCES].parts)
                parts['savegame'] = s.parts['savegame']
                s = Save(PREFERENCES, parts, s.source)
            out.append(s)
        return out

    def remap(self, save: Save, new_key: str) -> Save:
        raise SaveError('moving CONTROL Resonant saves between slots is not supported yet; '
                        'the continue pointer in preferences names the slot')
