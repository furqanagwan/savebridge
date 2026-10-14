"""The Witcher 3: Wild Hunt (Steam app 292030, Xbox package CDPROJEKTSA.Witcher3GOTY).

    Steam  Documents/The Witcher 3/gamesaves/<Name>.sav + <Name>.png   (per PC)
    Xbox   container <Name>, blobs sav, scr (the .png), meta, con

<Name> is e.g. ManualSave_11c607_7ea47400_3375e79 (also AutoSave, QuickSave,
CheckPoint). The .sav is the same on both stores: 'SNFHFZLC', a chunk count,
the data offset (0xC0C), then per chunk (compressed size, decompressed size,
end offset) and LZ4 blocks. Steam fills in every end offset; the Xbox build
leaves the last one 0. Inside is the 'SAV3' body: save version, game version, then
variables whose names live in a 'MANU' string table at the end.

Xbox adds two small blobs:

- meta: JSON with the build IDs, gameVersion and saveVersion (NUL-terminated).
  Taken from one of the account's own saves, so it names the installed build.
- con: the install chunks the save needs, 'content0\\0content1\\0...', i.e. the
  contentN entries set in the save's ContentTaintedFlags. A late-game save
  needs more of the game installed than a prologue save.

No account ID anywhere. The Xbox-only input and settings containers are left alone.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import struct
from dataclasses import replace
from pathlib import Path

from ..lz4 import Lz4Error, decompress_block
from ..platforms import Account, XboxAccount, documents_dir, long_path
from ..wgs import WgsError, WgsStore
from .base import Game, ReadResult, Save, SaveError

NAME = re.compile(r'(ManualSave|AutoSave|QuickSave|CheckPoint)_[0-9a-fA-F]+_[0-9a-fA-F]+_[0-9a-fA-F]+')
MAGIC = b'SNFHFZLC'
KINDS = {'ManualSave': 0, 'QuickSave': 1, 'AutoSave': 2, 'CheckPoint': 3}
TYPE_SIZES = {'Bool': 1, 'Uint8': 1, 'Int32': 4, 'Uint32': 4}


def chunks(sav: bytes) -> tuple[int, list[tuple[int, int, int]]]:
    """(data offset, [(compressed size, decompressed size, file offset)])."""
    if sav[:8] != MAGIC or len(sav) < 16:
        raise SaveError('not a Witcher 3 save')
    count, head = struct.unpack_from('<II', sav, 8)
    if not 0 < count < 4096 or head < 16 + 12 * count:
        raise SaveError('damaged Witcher 3 save header')
    out, pos = [], head
    for i in range(count):
        cs, ds, _ = struct.unpack_from('<III', sav, 16 + 12 * i)
        out.append((cs, ds, pos))
        pos += cs
    if pos != len(sav):
        raise SaveError(f'Witcher 3 save is {len(sav)} bytes, its chunks say {pos}')
    return head, out


def relayout(sav: bytes, xbox: bool) -> bytes:
    """The same save with every chunk's end offset filled in (Steam), or all but the
    last (Xbox: the game leaves the final one 0, so a one-chunk save has none)."""
    _, table = chunks(sav)
    out = bytearray(sav)
    for i, (cs, _, at) in enumerate(table):
        last = i == len(table) - 1
        struct.pack_into('<I', out, 16 + 12 * i + 8, 0 if xbox and last else at + cs)
    return bytes(out)


def body(sav: bytes) -> bytes:
    _, table = chunks(sav)
    try:
        return b''.join(decompress_block(sav[at:at + cs], ds) for cs, ds, at in table)
    except Lz4Error as e:
        raise SaveError(f'Witcher 3 save data is damaged ({e})') from None


def versions(raw: bytes) -> tuple[int, int]:
    """(saveVersion, gameVersion) from the SAV3 header."""
    if raw[:4] != b'SAV3':
        raise SaveError('Witcher 3 save body has no SAV3 header')
    return struct.unpack_from('<II', raw, 4)


def names(raw: bytes) -> list[str]:
    i = raw.rfind(b'MANU')
    if i < 0:
        raise SaveError('Witcher 3 save has no name table')
    count, p, out = struct.unpack_from('<I', raw, i + 4)[0], i + 12, []
    for _ in range(count):
        n = raw[p]
        out.append(raw[p + 1:p + 1 + n].decode('latin-1'))
        p += 1 + n
    return out


def required_content(raw: bytes) -> list[str]:
    """The install chunks (contentN) the save's ContentTaintedFlags marks as needed."""
    nm = names(raw)
    try:
        ref = nm.index('ContentTaintedFlags') + 1  # variable records use 1-based name indices
    except ValueError:
        raise SaveError('Witcher 3 save has no ContentTaintedFlags') from None
    p = raw.find(b'VL' + struct.pack('<H', ref))
    if p < 0:
        raise SaveError('Witcher 3 save has no ContentTaintedFlags value')
    out = []
    first = True
    while raw[p:p + 2] == b'VL':
        k, t = struct.unpack_from('<HH', raw, p + 2)
        name, size = nm[k - 1], TYPE_SIZES.get(nm[t - 1])
        if size is None or (not first and not re.fullmatch(r'content\d+', name)):
            break
        if not first and raw[p + 6]:
            out.append(name)
        p += 6 + size
        first = False
    if not out:
        raise SaveError('Witcher 3 save marks no content as needed')
    return out


def con_blob(content: list[str]) -> bytes:
    return b''.join(c.encode() + b'\0' for c in content)


def make_meta(template: bytes, raw: bytes) -> bytes:
    """The account's own meta (its installed build) with this save's version numbers."""
    save_version, game_version = versions(raw)
    out = template
    for field, value in (('gameVersion', game_version), ('saveVersion', save_version)):
        out, n = re.subn(rb'("%s":\s*)\d+' % field.encode(), lambda m: m.group(1) + str(value).encode(), out)
        if n != 1:
            raise SaveError(f'Xbox save metadata has no single "{field}"')
    return out


class Witcher3(Game):
    id = 'witcher3'
    name = 'The Witcher 3: Wild Hunt'
    verified = ('steam-to-xbox',)
    steam_app_id = 292030
    xbox_package_prefix = 'CDPROJEKTSA.Witcher3GOTY_'
    process_prefixes = ('witcher3',)
    steam_per_account = False

    def key_order(self, key: str) -> tuple:
        kind = key.split('_', 1)[0]
        return (KINDS.get(kind, 9), key)

    def describe(self, save: Save) -> str:
        prefix = save.key.split('_', 1)[0]
        kind = {'ManualSave': 'manual', 'QuickSave': 'quick', 'AutoSave': 'auto',
                'CheckPoint': 'checkpoint'}.get(prefix, prefix)
        when = f', {save.created:%Y-%m-%d %H:%M}' if save.created else ''
        return f'{kind} save, {len(save.parts["sav"]) / 1e6:.1f} MB{when}'

    def _save(self, key: str, sav: bytes, png: bytes | None, source: str,
              created: dt.datetime | None = None) -> Save:
        parts = {'sav': relayout(sav, xbox=False)}
        if png:
            parts['png'] = png
        return Save(key, parts, source, created)

    # ---- Steam ----------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return documents_dir() / 'The Witcher 3' / 'gamesaves'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for f in sorted(root.glob('*.sav')):
            if not NAME.fullmatch(f.stem):
                continue
            png = f.with_suffix('.png')
            try:
                r.saves[f.stem] = self._save(f.stem, f.read_bytes(), png.read_bytes() if png.is_file() else None,
                                             str(root), dt.datetime.fromtimestamp(f.stat().st_mtime))
            except SaveError as e:
                r.warnings.append(f'{f.name}: {e}')
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        files = {'.sav': save.parts['sav'], '.png': save.parts.get('png')}
        for ext, data in files.items():
            p = root / f'{save.key}{ext}'
            if data is None:
                p.unlink(missing_ok=True)
                continue
            tmp = p.with_name(p.name + '.savebridge-tmp')
            tmp.write_bytes(data)
            os.replace(tmp, p)

    # ---- Xbox -----------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if NAME.fullmatch(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if 'sav' not in blobs:
            raise SaveError(f'{container}: no sav blob')
        return self._save(container, blobs['sav'], blobs.get('scr'), container)

    def rebind(self, save: Save, target: Account) -> Save:
        if not isinstance(target, XboxAccount):
            return save
        return replace(save, bind=self._meta_template(target))

    def _meta_template(self, account: XboxAccount) -> bytes:
        """meta from the account's newest own save: it names the build that is installed."""
        try:
            store = WgsStore(long_path(account.folder))
            entries = sorted((e for e in store.live_entries() if self.xbox_key(e.name)),
                             key=lambda e: e.mtime, reverse=True)
            for e in entries:
                meta = store.read_blobs(e).get('meta')
                if meta and b'saveVersion' in meta:
                    json.loads(meta.rstrip(b'\0'))
                    return meta
        except (WgsError, OSError, ValueError) as ex:
            raise SaveError(f'could not read the Xbox saves: {ex}') from None
        raise SaveError('The Witcher 3 needs one of your own Xbox saves to copy the game build '
                        'from. Start the Xbox version, save once, close it, then try again.')

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        if not isinstance(save.bind, bytes):
            raise SaveError(f'{save.key}: no Xbox save metadata to write with')
        raw = body(save.parts['sav'])
        blobs = {
            'con': con_blob(required_content(raw)),
            'meta': make_meta(save.bind, raw),
            'sav': relayout(save.parts['sav'], xbox=True),
        }
        if 'png' in save.parts:
            blobs['scr'] = save.parts['png']
        return blobs

    # ---- importing ------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        stem, dot, ext = filename.rpartition('.')
        if dot and NAME.fullmatch(stem) and ext.lower() in ('sav', 'png'):
            part = ext.lower()
        else:
            parent = folder.rpartition('/')[2]  # a blob from an Xbox save folder
            if not (NAME.fullmatch(parent) and filename in ('sav', 'scr')):
                return None
            stem, folder, part = parent, folder.rpartition('/')[0], 'sav' if filename == 'sav' else 'png'
        if part == 'sav' and data[:8] != MAGIC:
            raise SaveError(f'{filename}: not a Witcher 3 save')
        return Save(stem, {part: data}, folder)

    def collect(self, found: list[Save]) -> ReadResult:
        parts: dict[str, dict[str, bytes]] = {}
        source: dict[str, str] = {}
        for s in found:
            parts.setdefault(s.key, {}).update(s.parts)
            source[s.key] = s.source
        r = ReadResult()
        for key, p in parts.items():
            if 'sav' not in p:
                continue  # a screenshot on its own
            try:
                r.saves[key] = self._save(key, p['sav'], p.get('png'), source[key])
            except SaveError as e:
                r.warnings.append(f'{key}: {e}')
        return r
