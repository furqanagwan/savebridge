"""Draws Assets/savebridge.ico: a green rounded square with a white two-way arrow (no image libraries)."""
import struct
import zlib
from pathlib import Path

GREEN, WHITE = (16, 124, 16), (255, 255, 255)


def inside_arrow(x, y):
    # unit coordinates 0..1: upper arrow pointing right, lower arrow pointing left
    def arrow(y0, right):
        if abs(y - y0) < 0.055 and 0.24 <= x <= 0.70 if right else abs(y - y0) < 0.055 and 0.30 <= x <= 0.76:
            return True
        tip = 0.80 if right else 0.20
        base = 0.62 if right else 0.38
        d = (tip - x) / (tip - base) if right else (x - tip) / (base - tip)
        return 0 <= d <= 1 and abs(y - y0) <= 0.16 * d
    return arrow(0.36, True) or arrow(0.64, False)


def pixel(x, y, n):
    u, v = (x + 0.5) / n, (y + 0.5) / n
    r = 0.2  # corner radius
    cx, cy = min(max(u, r), 1 - r), min(max(v, r), 1 - r)
    if (u - cx) ** 2 + (v - cy) ** 2 > r * r:
        return (0, 0, 0, 0)
    return (*WHITE, 255) if inside_arrow(u, v) else (*GREEN, 255)


def png(n, ss=4):
    rows = []
    for y in range(n):
        row = bytearray([0])
        for x in range(n):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    p = pixel(x * ss + sx, y * ss + sy, n * ss)
                    for i in range(4):
                        acc[i] += p[i]
            row += bytes(a // (ss * ss) for a in acc)
        rows.append(bytes(row))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))


sizes = [16, 24, 32, 48, 64, 256]
images = [png(n) for n in sizes]
out = struct.pack('<HHH', 0, 1, len(sizes))
offset = 6 + 16 * len(sizes)
for n, img in zip(sizes, images):
    out += struct.pack('<BBBBHHII', n % 256, n % 256, 0, 0, 1, 32, len(img), offset)
    offset += len(img)
out += b''.join(images)
Path(__file__).with_name('SaveBridge').joinpath('Assets', 'savebridge.ico').write_bytes(out)
Path(__file__).with_name('SaveBridge').joinpath('Assets', 'savebridge.png').write_bytes(images[-1])
print('icon written')
