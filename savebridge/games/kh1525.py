"""KINGDOM HEARTS -HD 1.5+2.5 ReMIX- (Steam app 2552430, Xbox package 39EA002F.KH1.52.5).

Each game in the collection keeps all its saves in one archive of PS2-style
entries (name, dates, length; 0x158 bytes each) followed by fixed-size slots:

    game                   entries  slot size  Steam file        Xbox container (one blob, same name)
    KH Final Mix           200      0x16C40    KHFM_WW.png       KH1SaveData/SAVE0.DAT
    KH Re:Chain of Mem.    100      0x3A30     KHReCoM_WW.png    ReCOMSaveData/SAVE0.DAT
    KH II Final Mix        100      0x10FC0    KHIIFM_WW.png     KH2SaveData/SAVE0.DAT

Steam (and Epic) put the archive in a 'sqEX' chunk of a real PNG: 16 constant
bytes, then the entry table with its first 0xF0 bytes XORed with a 16-byte key
stored in entry 0's (otherwise zero) padding at 0xE0, then the slots. The Steam
build also hides entry 0's name and dates under a second fixed key and leaves
its length field 0. Xbox stores the plain archive behind the MD5 of everything
after the first 16 bytes; KH Final Mix's archive is also zlib-compressed (u32
compressed size at 16, the stream at 32) and the blob padded to 16 MiB.

A logical save here is one game's whole archive (Save.parts['Archive'], the
plain table + slots + zero tail), so importing a downloaded set replaces that
game's saves as a set. The launcher's own save (MareSaveData) and config1525
are left alone. PC format as read by Xeeynamo/KingdomSaveEditor (GPL-3.0; see
THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from ..platforms import Account, SteamAccount, documents_dir
from .base import Game, ReadResult, Save, SaveError

ENTRY = 0x158
OBFUSCATED = 0xF0
KEY_AT = 0xE0
STEAM_ENTRY0_KEY = bytes.fromhex('ddf34bc69f50ca85d0e7d8baea9c09d5')
STEAM_HEADER = bytes.fromhex('2f70e2e853ced4f77b5a93953103c5c7')
KH1_BLOB = 16 * 1024 * 1024


@dataclass(frozen=True)
class Title:
    key: str
    label: str
    steam_file: str
    container: str
    entries: int
    stride: int
    save_size: int          # data length of a save slot (system entries are 0x400)
    compressed: bool = False

    @property
    def table(self) -> int:
        return self.entries * ENTRY


TITLES = {t.key: t for t in (
    Title('kh1', 'KINGDOM HEARTS Final Mix', 'KHFM_WW.png', 'KH1SaveData/SAVE0.DAT', 200, 0x16C40, 0x16C00, True),
    Title('recom', 'KINGDOM HEARTS Re:Chain of Memories', 'KHReCoM_WW.png', 'ReCOMSaveData/SAVE0.DAT', 100, 0x3A30, 0x3630),
    Title('kh2', 'KINGDOM HEARTS II Final Mix', 'KHIIFM_WW.png', 'KH2SaveData/SAVE0.DAT', 100, 0x10FC0, 0x10FC0),
)}
BY_STEAM = {t.steam_file.lower(): t for t in TITLES.values()}
BY_CONTAINER = {t.container: t for t in TITLES.values()}


def entries(t: Title, archive: bytes) -> list[tuple[int, str, int, int]]:
    """(index, name, modified unix time, length) of each used entry of a plain archive."""
    out = []
    for i in range(t.entries):
        e = archive[i * ENTRY:(i + 1) * ENTRY]
        name = e[:0x40].split(b'\0')[0]
        if name:
            _, _, modified, _, length, _ = struct.unpack_from('<iiiiii', e, 0x40)
            out.append((i, name.decode('latin-1'), modified, length))
    return out


def check_archive(t: Title, archive: bytes, name: str) -> bytes:
    if len(archive) < t.table + t.entries * t.stride:
        raise SaveError(f'{name}: too short for a {t.label} save archive')
    for i, n, _, length in entries(t, archive):
        if not re.fullmatch(r'[\x20-\x7e]+', n) or not 0 < length <= t.stride:
            raise SaveError(f'{name}: entry {i} is damaged')
    return archive


# ---- Steam / Epic PNG ------------------------------------------------------------

def _chunks(png: bytes):
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise SaveError('not a PNG')
    p = 8
    while p + 12 <= len(png):
        length, kind = struct.unpack_from('>I4s', png, p)
        yield kind, p, png[p + 8:p + 8 + length]
        p += 12 + length


def steam_unpack(t: Title, png: bytes, name: str) -> bytes:
    """The plain archive inside a Steam/Epic save PNG."""
    try:
        sq = next(data for kind, _, data in _chunks(png) if kind == b'sqEX')
    except (StopIteration, struct.error):
        raise SaveError(f'{name}: no Kingdom Hearts save data in this PNG') from None
    table = bytearray(sq[16:16 + t.table])
    key = bytes(table[KEY_AT:KEY_AT + 16])
    for i in range(OBFUSCATED):
        table[i] ^= key[i & 15]
    slots = sq[16 + t.table:]
    first = bytes(table[:0x40]).split(b'\0')[0]
    hidden = not re.fullmatch(rb'[ -~]*', first)
    if hidden or (struct.unpack_from('<i', table, 0x50)[0] == 0 and any(slots[:t.stride])):
        _restore_entry0(t, table, slots)
    archive = bytes(table) + slots + b'\0' * 16      # Xbox's archive is 16 bytes longer (no header)
    return check_archive(t, archive, name)


def _restore_entry0(t: Title, table: bytearray, slots: bytes) -> None:
    """The Steam build hides entry 0's first 18 name bytes and its dates (0x40-0x4C) under a
    second key, and leaves its length 0; the slot data itself is untouched."""
    name = bytes(table[i] ^ STEAM_ENTRY0_KEY[i & 15] for i in range(18)).split(b'\0')[0]
    hidden = bytes(table[0:0x40]) + bytes(table[i] ^ STEAM_ENTRY0_KEY[i & 15] for i in range(0x40, 0x4C))
    if not re.fullmatch(rb'[\x20-\x7e]{8,63}', name):
        raise SaveError('entry 0 of the Steam save could not be decoded')
    table[:0x40] = name.ljust(0x40, b'\0')
    table[0x40:0x4C] = hidden[0x40:0x4C]
    system = name.endswith((b'SYS', b'system.bin'))
    struct.pack_into('<iii', table, 0x4C, 0, 0x400 if system else t.save_size, 0)


def steam_pack(t: Title, archive: bytes, template: bytes) -> bytes:
    """A Steam save PNG: ``template``'s image around ``archive`` (Kingdom Save Editor's PC layout)."""
    table = bytearray(archive[:t.table])
    key = bytes(table[KEY_AT:KEY_AT + 16])  # zero padding: XOR leaves the key readable at 0xE0
    old = next((data for kind, _, data in _chunks(template) if kind == b'sqEX'), None)
    if old is not None:
        key = bytes(old[16 + KEY_AT:16 + KEY_AT + 16])
    for i in range(OBFUSCATED):
        table[i] ^= key[i & 15]
    sq = STEAM_HEADER + bytes(table) + archive[t.table:len(archive) - 16]
    out = bytearray(template[:8])
    for kind, p, data in _chunks(template):
        if kind == b'sqEX':
            data = sq
        out += struct.pack('>I4s', len(data), kind) + data + struct.pack('>I', zlib.crc32(kind + data))
        if kind == b'IEND':
            break
    return bytes(out)


# ---- Xbox ------------------------------------------------------------------------

def xbox_unpack(t: Title, blob: bytes, name: str) -> bytes:
    if hashlib.md5(blob[16:]).digest() != blob[:16]:
        raise SaveError(f'{name}: checksum mismatch (damaged save)')
    if not t.compressed:
        return check_archive(t, blob[16:], name)
    size = struct.unpack_from('<I', blob, 16)[0]
    try:
        archive = zlib.decompress(blob[32:32 + size])
    except zlib.error as e:
        raise SaveError(f'{name}: damaged ({e})') from None
    return check_archive(t, archive, name)


def xbox_pack(t: Title, archive: bytes) -> bytes:
    if t.compressed:
        packed = zlib.compress(archive, 9)
        body = struct.pack('<I', len(packed)) + b'\0' * 12 + packed
        if len(body) + 16 > KH1_BLOB:
            raise SaveError('the Kingdom Hearts save archive is too large for the Xbox version')
        body += b'\0' * (KH1_BLOB - 16 - len(body))
    else:
        body = archive
    return hashlib.md5(body).digest() + body


class KingdomHearts1525(Game):
    id = 'kh1525'
    name = 'KINGDOM HEARTS -HD 1.5+2.5 ReMIX-'
    verified = ('steam-to-xbox',)
    note = 'KH Final Mix, Re:Chain of Memories and KH II Final Mix; a game\'s saves move as a set'
    steam_app_id = 2552430
    xbox_package_prefix = '39EA002F.KH1.52.5_'
    process_prefixes = ('kingdom hearts', 'khfm', 'kh2fm', 'khrecom', 'kingdomhearts')
    xbox_keep_other_blobs = False

    def key_order(self, key: str) -> tuple:
        return (list(TITLES).index(key) if key in TITLES else 9, key)

    def describe(self, save: Save) -> str:
        t = TITLES[save.key]
        used = entries(t, save.parts['Archive'])
        saves = [e for e in used if not e[1].endswith(('SYS', 'system.bin'))]
        newest = max((e[2] for e in used), default=0)
        when = f', newest {dt.datetime.fromtimestamp(newest):%Y-%m-%d}' if 0 < newest < 2 ** 31 else ''
        return f'{t.label}: {len(saves)} save{"" if len(saves) == 1 else "s"}{when}'

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        if not isinstance(account, SteamAccount):
            raise SaveError('KINGDOM HEARTS HD 1.5+2.5 keeps Steam saves per Steam account')
        return documents_dir() / 'My Games' / 'KINGDOM HEARTS HD 1.5+2.5 ReMIX' / 'Steam' / str(account.steamid64)

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for f in sorted(root.glob('*.png')):
            t = BY_STEAM.get(f.name.lower())
            if t is None:
                continue
            try:
                r.saves[t.key] = Save(t.key, {'Archive': steam_unpack(t, f.read_bytes(), f.name)}, f.name)
            except SaveError as e:
                r.warnings.append(str(e))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        t = TITLES[save.key]
        p = root / t.steam_file
        if not p.is_file():
            raise SaveError(f'start {t.label} in the Steam version once and save, so there is a '
                            f'{t.steam_file} to write into')
        data = steam_pack(t, save.parts['Archive'], p.read_bytes())
        tmp = p.with_name(p.name + '.savebridge-tmp')
        tmp.write_bytes(data)
        os.replace(tmp, p)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        t = BY_CONTAINER.get(container)
        return t.key if t else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return TITLES[key].container

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        t = BY_CONTAINER[container]
        if container not in blobs:
            raise SaveError(f'{container}: blob missing')
        return Save(t.key, {'Archive': xbox_unpack(t, blobs[container], container)}, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        t = TITLES[save.key]
        return {t.container: xbox_pack(t, save.parts['Archive'])}

    # ---- importing --------------------------------------------------------------

    def import_root(self, folder: str) -> str:
        # The three Xbox containers of one save folder belong together.
        for c in BY_CONTAINER:
            for tail in ('/' + c.rpartition('/')[0], '/' + c + '/' + c.rpartition('/')[0]):
                if folder.endswith(tail):
                    return folder[:-len(tail)]
        return folder

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        path = name.replace('\\', '/')
        folder, _, filename = path.rpartition('/')
        t = BY_STEAM.get(filename.lower())
        if t is not None:
            return Save(t.key, {'Archive': steam_unpack(t, data, filename)}, folder)
        for c, t in BY_CONTAINER.items():
            if path.endswith('/' + c + '/' + c) or path.endswith('/' + c):
                return Save(t.key, {'Archive': xbox_unpack(t, data, c)}, folder)
        return None
