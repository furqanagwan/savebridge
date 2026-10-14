"""LZ4 block decompression (pure Python, no frame format)."""

from __future__ import annotations


class Lz4Error(Exception):
    pass


def decompress_block(src: bytes, size: int) -> bytes:
    """Decode one raw LZ4 block that expands to ``size`` bytes."""
    out = bytearray()
    i, n = 0, len(src)
    try:
        while i < n:
            token = src[i]
            i += 1
            lit = token >> 4
            if lit == 15:
                while True:
                    b = src[i]
                    i += 1
                    lit += b
                    if b != 255:
                        break
            out += src[i:i + lit]
            i += lit
            if i >= n:
                break
            off = src[i] | src[i + 1] << 8
            i += 2
            ml = token & 15
            if ml == 15:
                while True:
                    b = src[i]
                    i += 1
                    ml += b
                    if b != 255:
                        break
            ml += 4
            start = len(out) - off
            if off == 0 or start < 0:
                raise Lz4Error('bad match offset')
            if off >= ml:
                out += out[start:start + ml]
            else:  # overlapping copy repeats the last ``off`` bytes
                chunk = out[start:]
                out += (chunk * (ml // off + 1))[:ml]
    except IndexError:
        raise Lz4Error('truncated LZ4 block') from None
    if len(out) != size:
        raise Lz4Error(f'LZ4 block decoded to {len(out)} bytes, expected {size}')
    return bytes(out)
