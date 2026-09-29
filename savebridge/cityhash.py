"""CityHash64 (v1.1), the variant bundled with Unreal Engine.

Pure Python so the tool has no compiled dependencies.
"""

MASK = (1 << 64) - 1

K0 = 0xC3A5C85C97CB3127
K1 = 0xB492B66FBE98F273
K2 = 0x9AE16A3B2F90404F
KMUL = 0x9DDFEA08EB382D69


def _f64(s: bytes, i: int) -> int:
    return int.from_bytes(s[i:i + 8], 'little')


def _f32(s: bytes, i: int) -> int:
    return int.from_bytes(s[i:i + 4], 'little')


def rotr(v: int, n: int) -> int:
    return v if n == 0 else ((v >> n) | (v << (64 - n))) & MASK


def _bswap(v: int) -> int:
    return int.from_bytes(v.to_bytes(8, 'little'), 'big')


def _shift_mix(v: int) -> int:
    return v ^ (v >> 47)


def _hash16(u: int, v: int, mul: int = KMUL) -> int:
    a = ((u ^ v) * mul) & MASK
    a ^= a >> 47
    b = ((v ^ a) * mul) & MASK
    b ^= b >> 47
    return (b * mul) & MASK


def _len0to16(s: bytes) -> int:
    n = len(s)
    if n >= 8:
        mul = K2 + n * 2
        a = (_f64(s, 0) + K2) & MASK
        b = _f64(s, n - 8)
        c = (rotr(b, 37) * mul + a) & MASK
        d = ((rotr(a, 25) + b) * mul) & MASK
        return _hash16(c, d, mul)
    if n >= 4:
        mul = K2 + n * 2
        return _hash16(n + (_f32(s, 0) << 3), _f32(s, n - 4), mul)
    if n > 0:
        y = s[0] + (s[n >> 1] << 8)
        z = n + (s[n - 1] << 2)
        return (_shift_mix(((y * K2) ^ (z * K0)) & MASK) * K2) & MASK
    return K2


def _len17to32(s: bytes) -> int:
    n = len(s)
    mul = K2 + n * 2
    a = (_f64(s, 0) * K1) & MASK
    b = _f64(s, 8)
    c = (_f64(s, n - 8) * mul) & MASK
    d = (_f64(s, n - 16) * K2) & MASK
    return _hash16((rotr((a + b) & MASK, 43) + rotr(c, 30) + d) & MASK,
                   (a + rotr((b + K2) & MASK, 18) + c) & MASK, mul)


def _len33to64(s: bytes) -> int:
    n = len(s)
    mul = K2 + n * 2
    a = (_f64(s, 0) * K2) & MASK
    b = _f64(s, 8)
    c = _f64(s, n - 24)
    d = _f64(s, n - 32)
    e = (_f64(s, 16) * K2) & MASK
    f = (_f64(s, 24) * 9) & MASK
    g = _f64(s, n - 8)
    h = (_f64(s, n - 16) * mul) & MASK
    u = (rotr((a + g) & MASK, 43) + (rotr(b, 30) + c) * 9) & MASK
    v = ((((a + g) & MASK) ^ d) + f + 1) & MASK
    w = (_bswap(((u + v) * mul) & MASK) + h) & MASK
    x = (rotr((e + f) & MASK, 42) + c) & MASK
    y = ((_bswap(((v + w) * mul) & MASK) + g) * mul) & MASK
    z = (e + f + c) & MASK
    a = (_bswap(((x + z) * mul + y) & MASK) + b) & MASK
    b = (_shift_mix(((z + a) * mul + d + h) & MASK) * mul) & MASK
    return (b + x) & MASK


def _weak32(s: bytes, i: int, a: int, b: int) -> tuple[int, int]:
    w, x, y, z = _f64(s, i), _f64(s, i + 8), _f64(s, i + 16), _f64(s, i + 24)
    a = (a + w) & MASK
    b = rotr((b + a + z) & MASK, 21)
    c = a
    a = (a + x + y) & MASK
    b = (b + rotr(a, 44)) & MASK
    return (a + z) & MASK, (b + c) & MASK


def cityhash64(s: bytes) -> int:
    n = len(s)
    if n <= 32:
        return _len0to16(s) if n <= 16 else _len17to32(s)
    if n <= 64:
        return _len33to64(s)
    x = _f64(s, n - 40)
    y = (_f64(s, n - 16) + _f64(s, n - 56)) & MASK
    z = _hash16((_f64(s, n - 48) + n) & MASK, _f64(s, n - 24))
    v = _weak32(s, n - 64, n, z)
    w = _weak32(s, n - 32, (y + K1) & MASK, x)
    x = (x * K1 + _f64(s, 0)) & MASK
    remaining = (n - 1) & ~63
    p = 0
    while True:
        x = (rotr((x + y + v[0] + _f64(s, p + 8)) & MASK, 37) * K1) & MASK
        y = (rotr((y + v[1] + _f64(s, p + 48)) & MASK, 42) * K1) & MASK
        x ^= w[1]
        y = (y + v[0] + _f64(s, p + 40)) & MASK
        z = (rotr((z + w[0]) & MASK, 33) * K1) & MASK
        v = _weak32(s, p, (v[1] * K1) & MASK, (x + w[0]) & MASK)
        w = _weak32(s, p + 32, (z + w[1]) & MASK, (y + _f64(s, p + 16)) & MASK)
        z, x = x, z
        p += 64
        remaining -= 64
        if remaining == 0:
            break
    return _hash16((_hash16(v[0], w[0]) + _shift_mix(y) * K1 + z) & MASK,
                   (_hash16(v[1], w[1]) + x) & MASK)
