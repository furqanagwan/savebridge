"""Crimson Desert (Steam app 3321460, Xbox package PearlAbyss.CrimsonDesert).

    Steam  %LOCALAPPDATA%/Pearl Abyss/CD/save/<SteamID64>/slot<N>/lobby.save, save.save
    Xbox   container slot<N>, blobs 'lobby' and 'save'

Both files are 'SAVE' v2: a 0x80-byte header (flags, decompressed and stored
sizes, 16-byte ChaCha20 nonce, 32-byte HMAC-SHA256) then an LZ4-compressed,
ChaCha20-encrypted body. The key is a fixed constant mixed with the header
version (see LukeFZ/pycrimson): no account or platform input, so files are
byte-identical across Steam and Xbox. Neither file records its slot number, so
a save can go into any slot. lobby holds the menu summary (character, level,
display name); save holds the game state. Slots 0-2 are manual, 100+ automatic.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import struct
from pathlib import Path

from ..platforms import LOCALAPPDATA, Account, SteamAccount
from .base import Game, ReadResult, Save, SaveError

SLOT = re.compile(r'slot(\d+)')
FILES = {'lobby': 'lobby.save', 'save': 'save.save'}
BLOB_OF = {v: k for k, v in FILES.items()}


def check(name: str, data: bytes) -> None:
    if len(data) < 0x80 or data[:4] != b'SAVE':
        raise SaveError(f'{name}: not a Crimson Desert save')
    stored = struct.unpack_from('<I', data, 0x16)[0]
    if 0x80 + stored != len(data):
        raise SaveError(f'{name}: truncated (header says {stored} bytes of data)')


class CrimsonDesert(Game):
    id = 'crimson-desert'
    name = 'Crimson Desert'
    verified = ('steam-to-xbox',)
    steam_app_id = 3321460
    xbox_package_prefix = 'PearlAbyss.CrimsonDesert_'
    process_prefixes = ('crimsondesert',)

    def key_order(self, key: str) -> tuple:
        m = SLOT.fullmatch(key)
        return (int(m.group(1)),) if m else (9999,)

    def slot_key(self, n: int) -> str:
        return f'slot{n}'

    def describe(self, save: Save) -> str:
        size = struct.unpack_from('<I', save.parts['save'], 0x12)[0]
        kind = 'auto' if int(SLOT.fullmatch(save.key).group(1)) >= 100 else 'manual'
        when = f', {save.created:%Y-%m-%d %H:%M}' if save.created else ''
        return f'{kind} slot, {size / 2**20:.1f} MB of game state{when}'

    def _check(self, key: str, parts: dict[str, bytes]) -> None:
        missing = [FILES[b] for b in FILES if b not in parts]
        if missing:
            raise SaveError(f'{key}: needs {", ".join(missing)}')
        for blob, data in parts.items():
            check(f'{key}/{FILES[blob]}', data)

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        root = LOCALAPPDATA / 'Pearl Abyss' / 'CD' / 'save'
        return root / str(account.steamid64) if isinstance(account, SteamAccount) else root

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for d in sorted(root.iterdir()):
            if not (d.is_dir() and SLOT.fullmatch(d.name)):
                continue
            parts = {BLOB_OF[p.name]: p.read_bytes() for p in d.iterdir() if p.name in BLOB_OF}
            try:
                self._check(d.name, parts)
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            when = dt.datetime.fromtimestamp((d / 'save.save').stat().st_mtime)
            r.saves[d.name] = Save(d.name, parts, str(d), when)
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        d = root / save.key
        d.mkdir(parents=True, exist_ok=True)
        for blob, data in save.parts.items():
            tmp = d / f'{FILES[blob]}.savebridge-tmp'
            tmp.write_bytes(data)
            os.replace(tmp, d / FILES[blob])

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if SLOT.fullmatch(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def xbox_reserved(self, key: str) -> int:
        return 1  # what the game writes for its slot containers

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        parts = {b: blobs[b] for b in FILES if b in blobs}
        self._check(container, parts)
        return Save(container, parts, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return dict(save.parts)

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        blob = BLOB_OF.get(filename) or (filename if filename in FILES else None)
        slot = folder.rpartition('/')[2]
        if blob is None or not SLOT.fullmatch(slot):
            return None
        check(f'{slot}/{filename}', data)
        return Save(slot, {blob: data}, folder.rpartition('/')[0])

    def collect(self, found: list[Save]) -> ReadResult:
        parts: dict[str, dict[str, bytes]] = {}
        for s in found:
            parts.setdefault(s.key, {}).update(s.parts)
        r = ReadResult()
        for key, p in parts.items():
            try:
                self._check(key, p)
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            r.saves[key] = Save(key, p, found[0].source)
        return r

    def remap(self, save: Save, new_key: str) -> Save:
        if not SLOT.fullmatch(new_key):
            raise SaveError(f'saves can only move to another slot<number>, not {new_key}')
        return save.with_key(new_key)
