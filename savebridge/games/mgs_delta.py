"""METAL GEAR SOLID Δ: SNAKE EATER (Steam app 2417610, Xbox package RG5).

Both builds store the same Unreal Engine GVAS SaveGame bytes, followed by an
18-byte trailer:

    u64 magic    0xD42AEE521DA13C62
    u64 check    CityHash64(everything before the trailer), obfuscated
    u8  zero
    u8  version  Steam writes 2, Xbox writes 1

Version 1 stores ``hash ^ magic ^ 0x100``; version 2 adds two rotate/xor
rounds. The game reads either, but each build writes its own, so conversions
re-encode the trailer to the target platform's version.

Steam keeps two alternating copies of each save (<name>_0.sav, <name>_1.sav) in
%LOCALAPPDATA%/MGSDelta/Saved/SaveGames/<SteamID64>/. Xbox keeps one container
per save; slot containers are named SaveGames<NN><24 hex chars>, where the
suffix is a unique id the save data never refers to.

Nothing in the save data refers to the owning account.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import secrets
import struct
from pathlib import Path

from ..cityhash import cityhash64, rotr
from ..platforms import LOCALAPPDATA, Account
from .base import Game, ReadResult, Save, SaveError

MAGIC = 0xD42AEE521DA13C62
K1 = 0x09EBF7FD217247F5
K2 = 0x875CB4716484CC12
TRAILER = 18
STEAM_VERSION = 2
XBOX_VERSION = 1
BLOB = 'Data'

SPECIAL = {  # logical key -> (Steam file stem, Xbox container name, SaveGame class)
    'autosave': ('SaveGamesAutoSave', 'SaveGamesAutoSave', None),
    'profile': ('UserProfile', 'UserProfile', b'/Script/MGS3.UserProfileSaveGame'),
    'settings': ('UserSettings', 'UserSettings', b'/Script/Cobra.CobraCloudSaveSettings'),
}
SLOT_CLASS = b'/Script/MGS3.SaveGameData'
XBOX_SLOT = re.compile(r'SaveGames(\d{2})([0-9a-f]{24})')


def _obfuscated(a: int, version: int) -> bool:
    return a != 0 or version > 1


def unwrap(data: bytes, strict: bool = True) -> bytes:
    """Strip and verify the trailer, returning the GVAS payload."""
    if len(data) < TRAILER + 4 or data[:4] != b'GVAS':
        raise SaveError('not an Unreal Engine save file')
    magic, stored, a, version = struct.unpack('<QQBB', data[-TRAILER:])
    if magic != MAGIC:
        raise SaveError('not a Snake Eater save (trailer missing)')
    payload = data[:-TRAILER]
    h = stored
    if _obfuscated(a, version):
        h = rotr(h ^ K2, 49)
    h ^= ((version << 8) | a) ^ magic
    if _obfuscated(a, version):
        h = rotr(h, 49) ^ K1
    if strict and cityhash64(payload) != h:
        raise SaveError('checksum mismatch (corrupt or edited file)')
    return payload


def wrap(payload: bytes, version: int) -> bytes:
    h = cityhash64(payload)
    tag = version << 8
    if _obfuscated(0, version):
        h = rotr(rotr(h ^ K1, 15) ^ MAGIC ^ tag, 15) ^ K2
    else:
        h ^= MAGIC ^ tag
    return payload + struct.pack('<QQBB', MAGIC, h, 0, version)


# ---- the few GVAS fields worth showing ---------------------------------------

def _created(p: bytes) -> dt.datetime | None:
    i = p.find(b'CreatedTime\x00')
    j = p.find(b'DateTime\x00', i) if i >= 0 else -1
    if j < 0:
        return None
    ticks = struct.unpack_from('<Q', p, j + 9 + 16 + 1)[0]
    try:
        return dt.datetime(1, 1, 1) + dt.timedelta(microseconds=ticks // 10)
    except OverflowError:
        return None


def _slot_offset(p: bytes) -> int | None:
    """Offset of the DisplaySlotNo byte value."""
    i = p.find(b'DisplaySlotNo\x00')
    if i < 0:
        return None
    j = p.find(b'None\x00', i)  # ByteProperty enum name, then a zero guid flag
    return j + 6 if 0 <= j < i + 64 else None


def _play_time(p: bytes) -> int | None:
    tag = b'PlayTime\x00\x0c\x00\x00\x00IntProperty\x00'
    i = p.find(tag)
    return struct.unpack_from('<i', p, i + len(tag) + 9)[0] if i >= 0 else None


def _slot_no(key: str) -> int | None:
    m = re.fullmatch(r'slot(\d+)', key)
    return int(m.group(1)) if m else None


class MgsDelta(Game):
    id = 'mgs-delta'
    name = 'METAL GEAR SOLID Δ: SNAKE EATER'
    verified = ('steam-to-xbox',)
    steam_app_id = 2417610
    xbox_package_prefix = 'KonamiDigitalEntertainmen.RG5_'
    process_prefixes = ('mgsdelta',)

    def key_order(self, key: str) -> tuple:
        n = _slot_no(key)
        return (0, n) if n is not None else (1, list(SPECIAL).index(key))

    def default_keys(self, keys: list[str]) -> list[str]:
        # UserProfile (unlocks) and UserSettings are opt-in.
        return [k for k in keys if k.startswith('slot') or k == 'autosave']

    def describe(self, save: Save) -> str:
        p = save.parts[BLOB]
        bits = []
        if save.created:
            bits.append(save.created.strftime('%Y-%m-%d %H:%M'))
        t = _play_time(p)
        if t is not None:
            bits.append(f'play {t // 3600}:{t % 3600 // 60:02d}')
        return ', '.join(bits) or 'present'

    def _save(self, key: str, payload: bytes, source: str) -> Save:
        return Save(key, {BLOB: payload}, source, _created(payload))

    # ---- Steam --------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        # The Xbox build uses WGS containers, so this is only asked for Steam.
        return LOCALAPPDATA / 'MGSDelta' / 'Saved' / 'SaveGames' / str(account.steamid64)

    @staticmethod
    def _steam_stem(key: str) -> str:
        n = _slot_no(key)
        return f'SaveGames{n}' if n is not None else SPECIAL[key][0]

    @staticmethod
    def _steam_key(stem: str) -> str | None:
        m = re.fullmatch(r'SaveGames(\d+)', stem)
        if m:
            return f'slot{int(m.group(1))}'
        return next((k for k, v in SPECIAL.items() if v[0] == stem), None)

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for p in sorted(root.glob('*.sav')):
            m = re.fullmatch(r'(.+)_([01])\.sav', p.name)
            key = self._steam_key(m.group(1)) if m else None
            if key is None:
                continue
            try:
                s = self._save(key, unwrap(p.read_bytes()), p.name)
            except SaveError as e:
                r.warnings.append(f'{p.name}: {e}')
                continue
            # The game alternates between _0 and _1; the newer copy is current.
            r.offer(s, (s.created or dt.datetime.min, p.stat().st_mtime))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        data = wrap(save.parts[BLOB], STEAM_VERSION)
        root.mkdir(parents=True, exist_ok=True)
        stem = self._steam_stem(save.key)
        # Write both copies so the game can't fall back to a stale one.
        for n in (0, 1):
            p = root / f'{stem}_{n}.sav'
            tmp = p.with_name(p.name + '.tmp')
            tmp.write_bytes(data)
            os.replace(tmp, p)

    # ---- Xbox ---------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        m = XBOX_SLOT.fullmatch(container)
        if m:
            return f'slot{int(m.group(1))}'
        return next((k for k, v in SPECIAL.items() if v[1] == container), None)

    def xbox_container(self, key: str, existing: list[str]) -> str:
        for name in existing:
            if self.xbox_key(name) == key:
                return name
        n = _slot_no(key)
        if n is None:
            return SPECIAL[key][1]
        return f'SaveGames{n:02d}{secrets.token_hex(12)}'

    def xbox_reserved(self, key: str) -> int:
        return 1 if key.startswith('slot') else 0  # matches what the game writes

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if BLOB not in blobs:
            raise SaveError('container has no Data blob')
        return self._save(self.xbox_key(container), unwrap(blobs[BLOB]), container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {BLOB: wrap(save.parts[BLOB], XBOX_VERSION)}

    # ---- foreign files ------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        try:
            payload = unwrap(data, strict)
        except SaveError as e:
            if 'checksum' in str(e):
                raise
            return None
        head = payload[:4096]
        if SLOT_CLASS in head:
            off = _slot_offset(payload)
            key = f'slot{payload[off]}' if off is not None else 'autosave'
        else:
            key = next((k for k, v in SPECIAL.items() if v[2] and v[2] in head), None)
            if key is None:
                return None
        return self._save(key, payload, name)

    def remap(self, save: Save, new_key: str) -> Save:
        n = _slot_no(new_key)
        if n is None or not save.key.startswith('slot') or not 1 <= n <= 255:
            raise SaveError(f'can only move a numbered slot to another numbered slot '
                            f'({save.key} -> {new_key})')
        p = bytearray(save.parts[BLOB])
        off = _slot_offset(p)
        if off is None:
            raise SaveError('slot number not found in save')
        p[off] = n
        return Save(new_key, {BLOB: bytes(p)}, save.source, save.created)
