"""Halo checkpoints: HALOCEVO + Unreal chunk archive, containing Oodle GVAS.

Progress is ordinary GVAS. Xbox containers have the same names as Steam files.
Checkpoint player mappings are opaque IDs, not XUIDs or SteamIDs; learn the
receiving profile's mapping from its existing checkpoints. Never invent one.
"""

from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

from ..platforms import Account, XboxAccount
from ..unreal import GvasError, fstring, read_header
from .base import Save, SaveError
from .unreal_files import BLOB, SaveFile, UnrealFilesGame

MAGIC = b'HALOCEVO'
ARCHIVE_TAG = 0x222222229E2A83C1
CHUNK_SIZE = 131072
MAX_RAW = 64 * 1024 * 1024
CORE_CLASS = '/Script/BlamEngine.BlamSaveSlotSaveGame'
PROGRESS_CLASS = '/Script/BlamEngine.BlamProgressLocalPlayerSaveGame'
MAPPING_TAG = (fstring('PerPlayerXuidMapping') + fstring('UInt64Property')
               + struct.pack('<iiB', 0, 8, 0))


def _class(data: bytes, expected: str) -> None:
    try:
        if read_header(data).save_class != expected:
            raise SaveError(f'expected {expected}')
    except GvasError as e:
        raise SaveError(str(e)) from None


def ooz_path() -> Path:
    return Path(os.environ.get('SAVEBRIDGE_OOZ',
                Path(__file__).resolve().parents[1] / '_native' / 'ooz.exe'))


def _decode_chunk(data: bytes, size: int) -> bytes:
    # Oodle's uncompressed Kraken block: restart + raw flag, codec 6.
    if data[:2] == b'\xcc\x06' and len(data) == size + 2:
        return data[2:]
    return _decode_compressed_chunk(data, size, ooz_path())


@lru_cache(maxsize=256)
def _decode_compressed_chunk(data: bytes, size: int, helper: Path) -> bytes:
    # Raw blocks are cheap to decode and must not evict expensive compressed ones.
    if not helper.is_file():
        raise SaveError('Halo compressed saves need ooz.exe; run native/build_ooz.ps1 '
                        'or set SAVEBRIDGE_OOZ to your ooz executable')
    with tempfile.TemporaryDirectory(prefix='savebridge-halo-') as folder:
        src, dst = Path(folder) / 'chunk.bin', Path(folder) / 'chunk.raw'
        src.write_bytes(struct.pack('<Q', size) + data)
        try:
            result = subprocess.run([str(helper), str(src), str(dst)],
                                    capture_output=True, timeout=30,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SaveError(f'Halo decompression failed: {e}') from None
        if result.returncode or not dst.is_file() or dst.stat().st_size != size:
            raise SaveError('invalid Oodle checkpoint chunk')
        return dst.read_bytes()


def checkpoint_chunks(data: bytes) -> list[tuple[bytes, int]]:
    if len(data) < 49 or data[:8] != MAGIC:
        raise SaveError('invalid Halo checkpoint header')
    version, raw_size = struct.unpack_from('<II', data, 8)
    tag, chunk_size = struct.unpack_from('<QQ', data, 16)
    compressed, total_raw = struct.unpack_from('<QQ', data, 33)
    if (version != 0 or tag != ARCHIVE_TAG or chunk_size != CHUNK_SIZE
            or data[32] != 2 or not 0 < raw_size <= MAX_RAW or total_raw != raw_size):
        raise SaveError('unsupported Halo checkpoint archive')
    count = (raw_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    offset = 49 + 16 * count
    if offset > len(data) or compressed != len(data) - offset:
        raise SaveError('truncated Halo checkpoint archive')
    chunks = []
    for i in range(count):
        packed, unpacked = struct.unpack_from('<QQ', data, 49 + 16 * i)
        expected = min(CHUNK_SIZE, raw_size - i * CHUNK_SIZE)
        if unpacked != expected or packed == 0 or offset + packed > len(data):
            raise SaveError('invalid Halo checkpoint chunk sizes')
        chunks.append((data[offset:offset + packed], unpacked))
        offset += packed
    if offset != len(data):
        raise SaveError('unexpected data after Halo checkpoint chunks')
    return chunks


@lru_cache(maxsize=2)
def decode_checkpoint(data: bytes) -> bytes:
    raw = b''.join(_decode_chunk(packed, size) for packed, size in checkpoint_chunks(data))
    _class(raw, CORE_CLASS)
    player_mapping(raw)  # refuse files whose profile mapping we cannot locate
    return raw


def encode_checkpoint(raw: bytes) -> bytes:
    """Write raw Oodle blocks; no proprietary compressor is needed."""
    _class(raw, CORE_CLASS)
    if not 0 < len(raw) <= MAX_RAW:
        raise SaveError('invalid Halo checkpoint size')
    chunks = [raw[i:i + CHUNK_SIZE] for i in range(0, len(raw), CHUNK_SIZE)]
    return _pack_chunks([(b'\xcc\x06' + c, len(c)) for c in chunks])


def _pack_chunks(chunks: list[tuple[bytes, int]]) -> bytes:
    size = sum(n for _, n in chunks)
    return (MAGIC + struct.pack('<IIQQBQQ', 0, size, ARCHIVE_TAG, CHUNK_SIZE,
                               2, sum(len(c) for c, _ in chunks), size)
            + b''.join(struct.pack('<QQ', len(c), n) for c, n in chunks)
            + b''.join(c for c, _ in chunks))


def rebind_checkpoint(data: bytes, target: bytes) -> bytes:
    """Retain compressed chunks unless rebinding actually changes their payload.

    Replace on the full decoded payload first, including IDs that cross a chunk
    boundary. Each archive chunk is an independent Oodle stream.
    """
    if len(target) != 8 or target == bytes(8):
        raise SaveError('invalid target Halo player mapping')
    raw = decode_checkpoint(data)
    source = player_mapping(raw)
    if raw.count(source) != 7:
        raise SaveError('unsupported Halo player mapping layout (expected '
                        'seven copies in a solo checkpoint)')
    if source == target:
        return data
    rebound = raw.replace(source, target)
    chunks = []
    offset = 0
    for packed, size in checkpoint_chunks(data):
        changed = rebound[offset:offset + size]
        if changed != raw[offset:offset + size]:
            packed = b'\xcc\x06' + changed
        chunks.append((packed, size))
        offset += size
    return _pack_chunks(chunks)


def player_mapping(raw: bytes) -> bytes:
    offset = raw.find(MAPPING_TAG)
    if offset < 0 or raw.find(MAPPING_TAG, offset + 1) >= 0:
        raise SaveError('missing or ambiguous Halo player mapping')
    value = raw[offset + len(MAPPING_TAG):offset + len(MAPPING_TAG) + 8]
    if len(value) != 8 or value == bytes(8):
        raise SaveError('invalid Halo player mapping')
    return value


class HaloCampaignEvolved(UnrealFilesGame):
    id = 'halo-campaign-evolved'
    name = 'Halo: Campaign Evolved'
    verified = ('steam-to-xbox',)
    steam_app_id = 2806050
    xbox_package_prefix = 'Microsoft.198377053870B_'
    process_prefixes = ('halocampaignevolved', 'meteorite')
    steam_per_account = False
    steam_subdir = 'Meteorite/Saved/SaveGames'
    note = ('Solo saves; requires existing target checkpoints for player-ID rebinding. '
            'Compact output awaits in-game confirmation.')
    files = (SaveFile('CoreSave_0', (CORE_CLASS,)),
             SaveFile('CoreSave_1', (CORE_CLASS,)),
             SaveFile('Progress', (PROGRESS_CLASS,)))

    def _check(self, key: str, data: bytes) -> None:
        if key.startswith('CoreSave_'):
            decode_checkpoint(data)
        else:
            _class(data, PROGRESS_CLASS)

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        path = name.replace('\\', '/')
        folder, _, filename = path.rpartition('/')
        key = folder.rpartition('/')[2] if filename == BLOB else filename.removesuffix('.sav')
        if self._file(key) is None:
            return None
        self._check(key, data)
        return Save(key, {BLOB: data}, name)

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        if any(s.key.startswith('CoreSave_') for s in saves):
            if not any(s.key == 'Progress' for s in saves):
                raise SaveError('Halo checkpoints must travel with Progress.sav')
            mappings = {player_mapping(decode_checkpoint(s.parts[BLOB]))
                        for k, s in existing.items() if k.startswith('CoreSave_')}
            if not mappings:
                # A first export to Steam can retain the source profile mapping.
                # Xbox imports must already have a profile checkpoint (see rebind).
                return [replace(s, bind='missing-profile') for s in saves]
            if len(mappings) != 1:
                raise SaveError('save once in the target game profile first: Halo needs '
                                'one unambiguous existing checkpoint player mapping')
            target = mappings.pop()
            rebound = []
            for s in saves:
                if s.key.startswith('CoreSave_'):
                    raw = decode_checkpoint(s.parts[BLOB])
                    source = player_mapping(raw)
                    # Includes the metadata and copies within Blam's binary game state.
                    # Restrict this to the observed solo format; co-op needs more research.
                    if raw.count(source) != 7:
                        raise SaveError('unsupported Halo player mapping layout (expected '
                                        'seven copies in a solo checkpoint)')
                    if source != target:
                        s = Save(s.key, {BLOB: rebind_checkpoint(s.parts[BLOB], target)},
                                 s.source, s.created)
                rebound.append(s)
            return rebound
        return saves

    def rebind(self, save: Save, target: Account) -> Save:
        if (isinstance(target, XboxAccount) and save.key.startswith('CoreSave_')
                and save.bind == 'missing-profile'):
            raise SaveError('save once in the Xbox profile first: Halo needs an existing '
                            'checkpoint to learn its player mapping')
        return save

    def required_companions(self, keys: list[str]) -> list[str]:
        return ['Progress'] if any(k.startswith('CoreSave_') for k in keys) and 'Progress' not in keys else []

    def describe(self, save: Save) -> str:
        if save.key == 'Progress':
            return 'mission unlocks, skulls and progression'
        return ('main campaign' if save.key == 'CoreSave_0' else 'Operation: METEORITE')
