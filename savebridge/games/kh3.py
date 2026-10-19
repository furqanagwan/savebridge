"""KINGDOM HEARTS III + Re Mind (Steam app 2552450, Xbox package 39EA002F.KH3REMIND).

    Steam  Documents/My Games/KINGDOM HEARTS III/Steam/<SteamID64>/SaveGames/kh3sv2/data/
               KHIII_slot<N>.bin, KHIII_system.bin
    Epic   Documents/KINGDOM HEARTS III/Epic Games Store/1638/SaveGames/kh3sv2/data/ (same files)
    Xbox   container kh3sv2/data: blobs slot<N>.bin, system.bin and a 1-byte _ph_ placeholder;
           container kh3setting/data holds GameSettings.dat (left alone)

A save is an 'S@vE' structure: u32 file size at 4, version 5.2 at 8, CRC-32 at
0x0C over the file-size bytes from 0x10. Xbox (and PlayStation) store it bare,
0x10 + file size bytes long. Steam and Epic wrap it: zero-pad to 16 bytes,
AES-256-ECB, then 0x08 and the MD5 of the first file size + 16 bytes. The AES key
is 32 characters picked from a fixed table by a fixed mask XORed with the
owner's account ID: the SteamID64 in decimal on Steam, and the constant 1638
for every Epic install. So a Steam save is bound to its account and has to be
re-encrypted for the receiving one. Format as documented by
thirteenth-order/kh3-save-editor (see THIRD_PARTY_NOTICES.md).

system.bin is game-wide data and settings, not an index of the slots, so it is
only copied with --all.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import struct
import zlib
from dataclasses import replace
from pathlib import Path

from .. import aes, platforms
from ..platforms import Account, SteamAccount, documents_dir
from .base import Game, ReadResult, Save, SaveError

MAGIC = b'S@vE'
CONTAINER = 'kh3sv2/data'
EPIC_ACCOUNT = '1638'
KEY_MASK = b'hN96q4X9f%BCURBV&pMT4kcvqTMhHYD&'
KEY_TABLE = b'ABCDE!#$%&FGHIJ012345KLMNOPqrstuvwxyzQRSTUVWXYZ6789abcdefgh},.<>ijklmnop()=~|-^+*;:[]{/?_@'
STEAM_FILE = re.compile(r'KHIII_(slot\d+|system)\.bin', re.I)
XBOX_BLOB = re.compile(r'(slot\d+|system)\.bin')
DIFFICULTY = {0: 'Beginner', 1: 'Standard', 2: 'Proud', 3: 'Critical'}
FDATETIME_EPOCH = dt.datetime(1, 1, 1)


def key_for(account: str) -> bytes:
    a = account.encode()
    return bytes(KEY_TABLE[(KEY_MASK[i] ^ a[(i + 1) % len(a)]) % len(KEY_TABLE)] for i in range(32))


def check_plain(data: bytes, name: str) -> bytes:
    """The bare save, trimmed to 0x10 + file size; refuses a wrong magic, size or CRC."""
    if data[:4] != MAGIC or len(data) < 16:
        raise SaveError(f'{name}: not a Kingdom Hearts III save')
    size = struct.unpack_from('<I', data, 4)[0]
    if len(data) < 16 + size:
        raise SaveError(f'{name}: shorter than its size field says')
    plain = data[:16 + size]
    if struct.unpack_from('<I', plain, 12)[0] != zlib.crc32(plain[16:]):
        raise SaveError(f'{name}: checksum mismatch (damaged save)')
    return plain


def decrypt(data: bytes, account: str) -> bytes | None:
    """The bare save inside a Steam/Epic file, or None if ``account`` didn't write it."""
    if len(data) < 33 or (len(data) - 17) % 16 or data[-17] != 8:
        return None
    key = key_for(account)
    if aes.ecb(key, data[:16], decrypt=True)[:4] != MAGIC:
        return None
    padded = aes.ecb(key, data[:-17], decrypt=True)
    size = struct.unpack_from('<I', padded, 4)[0]
    if hashlib.md5(padded[:16 + size]).digest() != data[-16:]:
        return None
    return padded[:16 + size]


def encrypt(plain: bytes, account: str) -> bytes:
    padded = plain + b'\0' * (-len(plain) % 16)
    return aes.ecb(key_for(account), padded) + b'\x08' + hashlib.md5(plain).digest()


class KingdomHearts3(Game):
    id = 'kh3'
    name = 'KINGDOM HEARTS III + Re Mind'
    verified = ('steam-to-xbox',)
    steam_app_id = 2552450
    xbox_package_prefix = '39EA002F.KH3REMIND_'
    process_prefixes = ('kingdom hearts iii', 'khiii')
    xbox_keep_other_blobs = True

    def key_order(self, key: str) -> tuple:
        m = re.fullmatch(r'slot(\d+)', key)
        return (0, int(m.group(1))) if m else (1, 0)

    def slot_key(self, n: int) -> str:
        return f'slot{n}'

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if k != 'system']

    def describe(self, save: Save) -> str:
        p = save.parts['Data']
        if save.key == 'system':
            return 'game-wide data and settings'
        playtime, _, munny = struct.unpack_from('<III', p, 0x20)
        world = p[0xBBA0:0xBCA0].split(b'\0')[0].decode('latin-1').rsplit('/', 1)[-1]
        return (f'Lv {p[0x2C]}, {playtime // 3600}:{playtime % 3600 // 60:02d} played, '
                f'{DIFFICULTY.get(p[0x14], "difficulty " + str(p[0x14]))}, {world}')

    def _save(self, key: str, plain: bytes, source: str) -> Save:
        created = None
        if key != 'system':
            ticks = struct.unpack_from('<q', plain, 0x58)[0]
            try:
                created = FDATETIME_EPOCH + dt.timedelta(microseconds=ticks // 10)
            except OverflowError:
                created = None
        return Save(key, {'Data': plain}, source, created)

    # ---- account keys -------------------------------------------------------------

    def _open(self, data: bytes, name: str, hints=()) -> bytes:
        """The bare save from a file of any store, finding the account that wrote a wrapped one."""
        if data[:4] == MAGIC:
            return check_plain(data, name)
        accounts = [*hints, EPIC_ACCOUNT, *(str(a.steamid64) for a in platforms.steam_users())]
        for account in dict.fromkeys(accounts):
            plain = decrypt(data, account)
            if plain is not None:
                return check_plain(plain, name)
        raise SaveError(f'{name}: made by a Steam account savebridge cannot identify. Put the '
                        f'files in a folder named after that account\'s SteamID64 (the folder '
                        f'name under Steam\\ on the PC that made it) and try again.')

    def rebind(self, save: Save, target: Account) -> Save:
        if isinstance(target, SteamAccount):
            return replace(save, bind=str(target.steamid64))
        return save

    # ---- Steam --------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        if not isinstance(account, SteamAccount):
            raise SaveError('KINGDOM HEARTS III keeps Steam saves per Steam account')
        return (documents_dir() / 'My Games' / 'KINGDOM HEARTS III' / 'Steam' / str(account.steamid64)
                / 'SaveGames' / 'kh3sv2' / 'data')

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        owner = [p for p in root.parts if re.fullmatch(r'\d{17}', p)]
        for f in sorted(root.glob('*.bin')):
            m = STEAM_FILE.fullmatch(f.name)
            if not m:
                continue
            try:
                key = m.group(1).lower()
                r.saves[key] = self._save(key, self._open(f.read_bytes(), f.name, owner), f.name)
            except SaveError as e:
                r.warnings.append(str(e))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        if not isinstance(save.bind, str):
            raise SaveError(f'{save.key}: no Steam account to encrypt for')
        root.mkdir(parents=True, exist_ok=True)
        p = root / f'KHIII_{save.key}.bin'
        tmp = p.with_name(p.name + '.savebridge-tmp')
        tmp.write_bytes(encrypt(save.parts['Data'], save.bind))
        os.replace(tmp, p)

    # ---- Xbox ---------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return 'slot0' if container == CONTAINER else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return CONTAINER

    def decode_xbox_all(self, container: str, blobs: dict[str, bytes]) -> list[Save]:
        if container != CONTAINER:
            return []
        out = []
        for blob, data in sorted(blobs.items()):
            m = XBOX_BLOB.fullmatch(blob)
            if m:
                out.append(self._save(m.group(1), check_plain(data, blob), container))
        return out

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        saves = self.decode_xbox_all(container, blobs)
        if not saves:
            raise SaveError(f'{container}: no saves')
        return saves[0]

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {f'{save.key}.bin': save.parts['Data']}

    # ---- importing ----------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        path = name.replace('\\', '/')
        folder, _, filename = path.rpartition('/')
        m = STEAM_FILE.fullmatch(filename) or (XBOX_BLOB.fullmatch(filename) if folder.endswith(CONTAINER) else None)
        if not m:
            return None
        hints = re.findall(r'(?<!\d)(\d{17})(?!\d)', path)
        key = m.group(1).lower()
        return self._save(key, self._open(data, filename, hints), folder)

    def remap(self, save: Save, new_key: str) -> Save:
        if not re.fullmatch(r'slot\d+', new_key) or save.key == 'system':
            raise SaveError(f'only save slots can move to another slot ({new_key})')
        return save.with_key(new_key)
