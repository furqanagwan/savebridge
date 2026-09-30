"""AES-128 keystreams without third-party packages.

Uses Windows CNG (bcrypt.dll) when available and a small pure-Python AES
otherwise (slow, but only needed off Windows, e.g. in tests).
"""

from __future__ import annotations

import ctypes
import sys


def ofb_keystream(key: bytes, iv: bytes, length: int) -> bytes:
    """AES-128-OFB keystream: E(iv), E(E(iv)), ... (``length`` is a multiple of 16).

    OFB's keystream is CBC encryption of zeros, which CNG does in one call.
    """
    if len(key) != 16 or len(iv) != 16 or length % 16:
        raise ValueError('AES-128 OFB needs a 16-byte key/iv and whole blocks')
    if sys.platform == 'win32':
        return _cng_cbc_zeros(key, iv, length)
    out, block = bytearray(), iv
    rk = _expand(key)
    for _ in range(length // 16):
        block = _encrypt_block(rk, block)
        out += block
    return bytes(out)


def xor(data: bytes, stream: bytes) -> bytes:
    n = len(data)
    return (int.from_bytes(data, 'little') ^ int.from_bytes(stream[:n], 'little')).to_bytes(n, 'little')


# ---- Windows CNG -------------------------------------------------------------

_alg = None


def _cng_cbc_zeros(key: bytes, iv: bytes, length: int) -> bytes:
    global _alg
    bc = ctypes.windll.bcrypt
    if _alg is None:
        h = ctypes.c_void_p()
        _check(bc.BCryptOpenAlgorithmProvider(ctypes.byref(h), 'AES', None, 0))
        mode = ctypes.create_unicode_buffer('ChainingModeCBC')
        _check(bc.BCryptSetProperty(h, 'ChainingMode', mode, ctypes.sizeof(mode), 0))
        _alg = h
    hkey = ctypes.c_void_p()
    _check(bc.BCryptGenerateSymmetricKey(_alg, ctypes.byref(hkey), None, 0, key, len(key), 0))
    try:
        src = (ctypes.c_ubyte * length)()
        dst = (ctypes.c_ubyte * length)()
        ivb = (ctypes.c_ubyte * 16).from_buffer_copy(iv)
        done = ctypes.c_ulong()
        _check(bc.BCryptEncrypt(hkey, src, length, None, ivb, 16, dst, length, ctypes.byref(done), 0))
        return bytes(dst)
    finally:
        bc.BCryptDestroyKey(hkey)


def _check(status: int) -> None:
    if status:
        raise OSError(f'Windows CNG error 0x{status & 0xFFFFFFFF:08X}')


# ---- pure Python AES-128 (encryption only) ----------------------------------

def _sbox() -> list[int]:
    s, p, q = [0] * 256, 1, 1
    while True:
        p ^= (p << 1) ^ (0x1B if p & 0x80 else 0)
        p &= 0xFF
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4))
        s[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    s[0] = 0x63
    return s


SBOX = _sbox()


def _xt(b: int) -> int:
    return ((b << 1) ^ (0x1B if b & 0x80 else 0)) & 0xFF


def _expand(key: bytes) -> list[list[int]]:
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xt(rcon)
        w.append([a ^ b for a, b in zip(w[i - 4], t)])
    return [sum(w[r * 4:r * 4 + 4], []) for r in range(11)]


def _encrypt_block(rk: list[list[int]], block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, rk[0])]
    for r in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows (column-major state)
        if r != 10:
            m = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                m += [a[i] ^ t ^ _xt(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = m
        s = [b ^ k for b, k in zip(s, rk[r])]
    return bytes(s)
