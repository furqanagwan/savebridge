"""Capcom RE Engine "DSSS" save encryption (Onimusha, Resident Evil, Monster Hunter, ...).

Ported from MandarinJuice by mi5hmash (MIT), https://github.com/mi5hmash/MandarinJuice.

File layout (little endian):

    header   'DSSS', u32 2, u32 flavor (0x10 plain, 0x18 deflate inside), u32 0
    slices   each: 528-byte slice header + (1..8) x 16 KiB of data
    footer   128 random bytes, u64 plaintext length, u32 Murmur3-32 of all
             preceding 32-bit words (seed 0xFFFFFFFF)

Everything is driven by a per-game 64-bit seed and a 64-bit value derived from
the owner's account ID (see ``parse_id``). The seed and ID run a SplitMix64
stream that picks the slice sizes, generates each slice's 32-byte AES key
(key + OFB IV) and XOR-masks the slice header. The header carries the key a
second time, as four products ``personal_seed * key_part`` next to a fixed
value, where ``personal_seed`` is a modular power of the account ID.

The first 64 bytes of every slice header are that fixed value, so its
masked form reveals the first 8 bytes of the ID's SplitMix64 stream: a cheap
test for "was this file written by account X?" (``id_matches``), and the basis
of the 2^32 brute force in ``find_id``.
"""

from __future__ import annotations

import base64
import ctypes
import os
import struct
from pathlib import Path

from . import aes
from .cityhash import cityhash64

M64 = (1 << 64) - 1
MAGIC = b'DSSS'
FLAVOR_PLAIN, FLAVOR_DEFLATE = 0x10, 0x18
HEAD, FOOT, SLICE_HEAD, SHIFT = 16, 0x8C, 0x210, 14


def _key(b64: str) -> int:
    return int.from_bytes(base64.b64decode(b64), 'little')


PK1 = _key('8ztvuXKgtyUV5Fw5GCnhgq2Km9wKZNNETXnIEKuGNxc=')  # modulus
PK2 = _key('+Z23XDnQ25IKcq4cjJRwwVbFTW4FsmmipjxkiFXDmws=')  # exponent modulus
PK3 = _key('5m9USvzOaMXvB7mgeyd1hTRKHbYTdugx9zufvV9E9xU=')  # generator
KEY_TYPE = 0x14
HEADER_KEY = pow(PK3, KEY_TYPE, PK1)


class DsssError(Exception):
    pass


def splitmix(s: int) -> int:
    s = (s + 0x9E3779B97F4A7C15) & M64
    s = ((s ^ (s >> 30)) * 0xBF58476D1CE4E5B9) & M64
    s = ((s ^ (s >> 27)) * 0x94D049BB133111EB) & M64
    return s ^ (s >> 31)


def _stream(state: int, n: int) -> tuple[bytes, int]:
    """The low bytes of the next ``n`` SplitMix64 states."""
    out = bytearray(n)
    for i in range(n):
        state = splitmix(state)
        out[i] = state & 0xFF
    return bytes(out), state


def _slices(seed: int, length: int) -> tuple[list[int], int]:
    """Slice capacities (in 16 KiB units) for ``length`` bytes, and the state after them."""
    state, caps = seed, []
    for _ in range((length >> SHIFT) + 1):
        if length > 0:
            caps.append((state & 7) + 1)
            length = max(0, length - (caps[-1] << SHIFT))
        state = splitmix(state)
    return caps, state


def _slice_key(state: int) -> tuple[bytes, int]:
    key = bytearray(32)
    for i in range(16):
        state = splitmix(state)
        key[i], key[16 + i] = state & 0xFF, (state >> 8) & 0xFF
    return bytes(key), state


# ---- account IDs ---------------------------------------------------------------

def parse_id(account_id: int, variant: int) -> int:
    """A Steam-style 32-bit account ID as the 64-bit value a game's variant feeds the cipher."""
    account_id &= 0xFFFFFFFF
    sid = 0x0110000100000000 | account_id
    if variant == 0:
        return sid
    if variant == 1:
        return 0xFFFFFFFF00000000 | (~account_id & 0xFFFFFFFF)
    if variant == 2:
        return ~sid & M64
    if variant == 3:
        x = sid ^ 0x1A3B5C7DD0C2B4A8
        return ~(((x >> 32) & 0xFFFFFFFF) | ((x & 0xFFFFFFFF) << 32)) & M64
    raise DsssError(f'unknown ID variant {variant}')


class File:
    """A DSSS file's header, encrypted body and footer."""

    def __init__(self, data: bytes):
        if len(data) < HEAD + SLICE_HEAD + FOOT or data[:4] != MAGIC:
            raise DsssError('not a Capcom DSSS save')
        self.version, self.flavor, self.reserved = struct.unpack_from('<III', data, 4)
        self.body = data[HEAD:-FOOT]
        self.length = struct.unpack_from('<Q', data, len(data) - 12)[0]
        if struct.unpack_from('<I', data, len(data) - 4)[0] != murmur3(data[:-4]):
            raise DsssError('DSSS signature does not match (file damaged?)')

    def _id_state(self, seed: int) -> int:
        return _slices(seed, self.length)[1]

    def target_mask(self) -> int:
        return struct.unpack_from('<Q', self.body, 0)[0] ^ (HEADER_KEY & M64)


def id_matches(f: File, seed: int, parsed_id: int) -> bool:
    s = (f._id_state(seed) + parsed_id) & M64
    for _ in range(16):
        s = splitmix(s)
    return int.from_bytes(_stream(s, 8)[0], 'little') == f.target_mask()


def find_id(f: File, seed: int, variant: int, candidates=()) -> int | None:
    """The 32-bit account ID that wrote ``f``: tries ``candidates``, then all 2^32."""
    for c in candidates:
        if id_matches(f, seed, parse_id(c, variant)):
            return c & 0xFFFFFFFF
    lib = native()
    if lib is None:
        raise DsssError('finding the account ID of this save needs the native helper '
                        '(savebridge/_native/dsss_find.dll; see native/README.md)')
    found = lib.dsss_find_id(f._id_state(seed), f.target_mask(), variant)
    return None if found < 0 else found


_lib = False


def native():
    global _lib
    if _lib is False:
        _lib = None
        p = Path(__file__).with_name('_native') / 'dsss_find.dll'
        if os.name == 'nt' and p.is_file():
            lib = ctypes.CDLL(str(p))
            lib.dsss_find_id.restype = ctypes.c_int64
            lib.dsss_find_id.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_int]
            _lib = lib
    return _lib


# ---- decrypt / encrypt ---------------------------------------------------------

def decrypt(data: bytes, seed: int, parsed_id: int) -> tuple[bytes, File]:
    """Plaintext of a DSSS file written by ``parsed_id`` (see ``parse_id``)."""
    f = File(data)
    caps, state = _slices(seed, f.length)
    state = (state + parsed_id) & M64
    out, pos, remaining = bytearray(), 0, f.length
    for n, cap in enumerate(caps):
        size = cap << SHIFT
        if pos + SLICE_HEAD + size > len(f.body):
            raise DsssError('DSSS file is shorter than its length field says')
        _, state = _slice_key(state)
        mask, state = _stream(state, SLICE_HEAD)
        head = aes.xor(f.body[pos:pos + SLICE_HEAD], mask)
        key = bytearray()
        for i in range(4):
            a = int.from_bytes(head[i * 128:i * 128 + 64], 'little')
            d = int.from_bytes(head[i * 128 + 64:i * 128 + 128], 'little')
            key += ((d // pow(a, parsed_id, PK1)) & M64).to_bytes(8, 'little')
        body = f.body[pos + SLICE_HEAD:pos + SLICE_HEAD + size]
        plain = aes.xor(body, aes.ofb_keystream(bytes(key[:16]), bytes(key[16:]), size))
        take = min(size, remaining)
        if n == 0 and cityhash64(plain[:take]) != struct.unpack_from('<Q', head, 512)[0]:
            raise DsssError('wrong account ID for this save (checksum mismatch)')
        out += plain[:take]
        pos += SLICE_HEAD + size
        remaining -= take
    return bytes(out), f


def encrypt(plain: bytes, seed: int, parsed_id: int, flavor: int = FLAVOR_PLAIN,
            version: int = 2, reserved: int = 0) -> bytes:
    caps, state = _slices(seed, len(plain))
    state = (state + parsed_id) & M64
    personal = pow(pow(PK3, parsed_id % PK2, PK1), KEY_TYPE, PK1)
    hk = HEADER_KEY.to_bytes(64, 'little')
    body, pos, remaining = bytearray(), 0, len(plain)
    for cap in caps:
        size = cap << SHIFT
        key, state = _slice_key(state)
        take = min(size, remaining)
        chunk = plain[pos:pos + take]
        head = bytearray()
        for i in range(4):
            head += hk + (personal * int.from_bytes(key[i * 8:i * 8 + 8], 'little')).to_bytes(64, 'little')
        head += struct.pack('<QQ', cityhash64(chunk), splitmix(remaining))
        mask, state = _stream(state, SLICE_HEAD)
        body += aes.xor(bytes(head), mask)
        body += aes.xor(chunk.ljust(size, b'\0'), aes.ofb_keystream(key[:16], key[16:], size))
        pos += take
        remaining -= take
    out = bytearray(MAGIC + struct.pack('<III', version, flavor, reserved) + body)
    out += os.urandom(0x80) + struct.pack('<QI', len(plain), 0)
    struct.pack_into('<I', out, len(out) - 4, murmur3(bytes(out[:-4])))
    return bytes(out)


def reencrypt(data: bytes, seed: int, from_id: int, to_id: int) -> bytes:
    plain, f = decrypt(data, seed, from_id)
    return encrypt(plain, seed, to_id, f.flavor, f.version, f.reserved)


def murmur3(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    """Murmur3-32 over whole 32-bit words (DSSS files are always a multiple of 4 long)."""
    h = seed
    for (k,) in struct.iter_unpack('<I', data[:len(data) & ~3]):
        k = (k * 0xCC9E2D51) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        h ^= (k * 0x1B873593) & 0xFFFFFFFF
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
    h ^= len(data) & 0xFFFFFFFF
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    return h ^ (h >> 16)
