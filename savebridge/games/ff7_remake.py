"""FINAL FANTASY VII REMAKE INTERGRADE (Steam app 1462040, Xbox package 39EA002F.EXED1).

    Steam  Documents/My Games/FINAL FANTASY VII REMAKE/Steam/<SteamID64>/<name>.sav
    Xbox   container <name>, blob 'Data'

<name> is ff7remake<NNN> (main game), ff7remakeplus<NNN> (INTERmission) or
ff7remakecommon (shared system data). Steam stores the raw save (9,434,752
bytes for a slot, starting 00 00 01 00 ... 'RESD'). Xbox wraps the same bytes:

    'bilz'  u32 compressed size  u32 raw size  8 zero bytes  zlib stream

So Steam -> Xbox compresses and Xbox -> Steam decompresses; the raw save is
byte-identical. The game's own deflate output differs from Python's, but it is
standard zlib and either decompresses to the same bytes. No account ID inside.
"""

from __future__ import annotations

import os
import re
import struct
import zlib
from pathlib import Path

from ..platforms import Account, SteamAccount, documents_dir
from .base import Game, ReadResult, Save, SaveError

BLOB = 'Data'


def wrap(raw: bytes) -> bytes:
    z = zlib.compress(raw, 6)
    return b'bilz' + struct.pack('<II', len(z), len(raw)) + bytes(8) + z


def unwrap(data: bytes) -> bytes:
    if data[:4] != b'bilz' or len(data) < 20:
        raise SaveError('not an Xbox FINAL FANTASY VII REMAKE save')
    csize, rsize = struct.unpack_from('<II', data, 4)
    if csize != len(data) - 20:
        raise SaveError('truncated Xbox save')
    try:
        raw = zlib.decompress(data[20:])
    except zlib.error as e:
        raise SaveError(f'corrupt Xbox save ({e})') from None
    if len(raw) != rsize:
        raise SaveError('Xbox save size mismatch')
    return raw


def check_raw(key: str, raw: bytes) -> None:
    tag = b'COSD' if key.endswith('common') else b'RESD'
    if raw[16:20] != tag:
        raise SaveError(f'{key}: not a FINAL FANTASY VII REMAKE save')


def to_raw(key: str, data: bytes) -> bytes:
    """Accept either platform's bytes; return the raw (Steam) form."""
    raw = unwrap(data) if data[:4] == b'bilz' else data
    check_raw(key, raw)
    return raw


class Ff7Remake(Game):
    id = 'ff7-remake'
    name = 'FINAL FANTASY VII REMAKE INTERGRADE'
    verified = ('steam-to-xbox',)
    steam_app_id = 1462040
    xbox_package_prefix = '39EA002F.EXED1_'
    process_prefixes = ('ff7remake',)
    prefix = 'ff7remake'                       # file/container name prefix
    documents_folder = 'FINAL FANTASY VII REMAKE'
    reserved = 1                               # index reserved field the game writes

    @property
    def name_re(self) -> re.Pattern:
        return re.compile(rf'{self.prefix}(?:plus)?\d{{3}}|{self.prefix}common')

    def to_raw(self, key: str, data: bytes) -> bytes:
        """Either platform's bytes -> the raw (Steam) form."""
        return to_raw(key, data)

    def to_xbox(self, raw: bytes) -> bytes:
        return wrap(raw)

    def key_order(self, key: str) -> tuple:
        if key.endswith('common'):
            return (2, 0)
        m = re.fullmatch(rf'{self.prefix}(plus)?(\d{{3}})', key)
        return (1 if m.group(1) else 0, int(m.group(2)))

    def slot_key(self, n: int) -> str:
        return f'{self.prefix}{n:03d}'

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if not k.endswith('common')]

    def describe(self, save: Save) -> str:
        if save.key.endswith('common'):
            return 'shared system data'
        return 'INTERmission save' if 'plus' in save.key else 'main game save'

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        root = documents_dir() / 'My Games' / self.documents_folder / 'Steam'
        return root / str(account.steamid64) if isinstance(account, SteamAccount) else root

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for p in sorted(root.glob('*.sav')):
            if not self.name_re.fullmatch(p.stem):
                continue
            try:
                raw = self.to_raw(p.stem, p.read_bytes())
            except SaveError as e:
                r.warnings.append(f'{p.name}: {e}')
                continue
            r.saves[p.stem] = Save(p.stem, {BLOB: raw}, p.name)
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = root / f'{save.key}.sav'
        tmp = p.with_name(p.name + '.savebridge-tmp')
        tmp.write_bytes(save.parts[BLOB])
        os.replace(tmp, p)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if self.name_re.fullmatch(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def xbox_reserved(self, key: str) -> int:
        return self.reserved

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if BLOB not in blobs:
            raise SaveError(f'{container} has no Data blob')
        return Save(container, {BLOB: self.to_raw(container, blobs[BLOB])}, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {BLOB: self.to_xbox(save.parts[BLOB])}

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        stem = filename.removesuffix('.sav')
        if stem == BLOB:  # a blob from an Xbox save folder
            stem = folder.rpartition('/')[2]
        if not self.name_re.fullmatch(stem):
            return None
        return Save(stem, {BLOB: self.to_raw(stem, data)}, name)

    def remap(self, save: Save, new_key: str) -> Save:
        same_kind = ('plus' in save.key) == ('plus' in new_key)
        if (not re.fullmatch(rf'{self.prefix}(plus)?\d{{3}}', new_key) or not same_kind
                or save.key.endswith('common')):
            raise SaveError(f'can only move {save.key} to another slot of the same kind, not {new_key}')
        return save.with_key(new_key)


class Ff7Rebirth(Ff7Remake):
    """FINAL FANTASY VII REBIRTH (Steam app 2909400, Xbox package 39EA002F.EXED2).

    Same raw save format and naming (ff7rebirth<NNN>, ff7rebirthcommon), but the
    Xbox blob is a bare zlib stream with no 'bilz' header, and the game also
    keeps a plain-file copy under SystemAppData/xgs (written alongside).
    """
    id = 'ff7-rebirth'
    name = 'FINAL FANTASY VII REBIRTH'
    verified = ('steam-to-xbox',)
    steam_app_id = 2909400
    xbox_package_prefix = '39EA002F.EXED2_'
    process_prefixes = ('ff7rebirth',)
    prefix = 'ff7rebirth'
    documents_folder = 'FINAL FANTASY VII REBIRTH'
    reserved = 0

    def to_raw(self, key: str, data: bytes) -> bytes:
        if data[:1] == b'x':
            try:
                data = zlib.decompress(data)
            except zlib.error as e:
                raise SaveError(f'{key}: corrupt Xbox save ({e})') from None
        check_raw(key, data)
        return data

    def to_xbox(self, raw: bytes) -> bytes:
        return zlib.compress(raw, 6)

    def describe(self, save: Save) -> str:
        return 'shared system data' if save.key.endswith('common') else 'save'
