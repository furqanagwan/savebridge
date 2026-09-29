"""Just enough of Unreal Engine 4's GVAS SaveGame format to inspect and patch saves.

Layout: 'GVAS', save/package versions, engine version, custom-version table,
the SaveGame class path, then tagged properties ending with 'None' and a
4-byte zero.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class GvasError(Exception):
    pass


def read_fstring(b: bytes, o: int) -> tuple[str, int]:
    n = struct.unpack_from('<i', b, o)[0]
    o += 4
    if n < 0:
        return b[o:o - 2 * n].decode('utf-16le')[:-1], o - 2 * n
    return b[o:o + n - 1].decode('latin1'), o + n


def fstring(s: str) -> bytes:
    try:
        raw = s.encode('latin1') + b'\0'
        return struct.pack('<i', len(raw)) + raw
    except UnicodeEncodeError:
        raw = s.encode('utf-16le') + b'\0\0'
        return struct.pack('<i', -(len(raw) // 2)) + raw


@dataclass
class Header:
    package_version: int
    engine: tuple[int, int, int, int]  # major, minor, patch, changelist
    branch: str
    save_class: str
    body_start: int                    # offset of the first property


def read_header(b: bytes) -> Header:
    if b[:4] != b'GVAS':
        raise GvasError('not an Unreal Engine save file')
    try:
        _, package = struct.unpack_from('<ii', b, 4)
        engine = struct.unpack_from('<HHHI', b, 12)
        branch, o = read_fstring(b, 22)
        _, count = struct.unpack_from('<ii', b, o)
        o += 8 + count * 20
        cls, o = read_fstring(b, o)
    except (struct.error, UnicodeDecodeError) as e:
        raise GvasError(f'bad save header: {e}') from None
    return Header(package, engine, branch, cls, o)


@dataclass
class Prop:
    name: str
    type: str
    start: int        # first byte of the property tag
    value: int        # first byte of the value
    end: int          # one past the value
    size_field: int   # offset of the int64 value size in the tag


def read_props(b: bytes, o: int) -> tuple[dict[str, Prop], int]:
    """Top-level tagged properties from ``o``; returns them and the 'None' offset."""
    out = {}
    try:
        while True:
            start = o
            name, o = read_fstring(b, o)
            if name == 'None':
                return out, start
            typ, o = read_fstring(b, o)
            size_field = o
            size = struct.unpack_from('<q', b, o)[0]
            o += 8
            if typ == 'StructProperty':
                _, o = read_fstring(b, o)
                o += 16
            elif typ in ('ArrayProperty', 'SetProperty', 'ByteProperty', 'EnumProperty'):
                _, o = read_fstring(b, o)
            elif typ == 'MapProperty':
                _, o = read_fstring(b, o)
                _, o = read_fstring(b, o)
            elif typ == 'BoolProperty':
                o += 1
            o += 1  # has property guid
            if size < 0 or o + size > len(b):
                raise GvasError(f'property {name} runs past end of file')
            out[name] = Prop(name, typ, start, o, o + size, size_field)
            o += size
    except (struct.error, UnicodeDecodeError) as e:
        raise GvasError(f'bad property data: {e}') from None


def replace_value(b: bytes, p: Prop, value: bytes) -> bytes:
    """Swap a property's value and fix the size recorded in its tag."""
    tag = bytearray(b[p.start:p.value])
    struct.pack_into('<q', tag, p.size_field - p.start, len(value))
    return b[:p.start] + bytes(tag) + value + b[p.end:]
