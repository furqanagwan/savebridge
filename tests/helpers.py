"""Synthetic saves and stores, so tests never need anyone's real save files."""

from __future__ import annotations

import struct
import uuid
from pathlib import Path

from savebridge.wgs import Index


def _fstr(s: str) -> bytes:
    b = s.encode() + b'\0'
    return struct.pack('<I', len(b)) + b


def mgs_payload(slot: int | None, ticks: int = 638_900_000_000_000_000,
                cls: str = '/Script/MGS3.SaveGameData', filler: bytes = b'') -> bytes:
    """A minimal GVAS body with the fields the MGS Δ plugin reads."""
    out = b'GVAS' + b'\0' * 60 + _fstr(cls)
    if cls.endswith('SaveGameData'):
        out += (_fstr('CreatedTime') + _fstr('StructProperty') + struct.pack('<Q', 8)
                + _fstr('DateTime') + b'\0' * 17 + struct.pack('<Q', ticks))
        if slot is not None:
            out += (_fstr('DisplaySlotNo') + _fstr('ByteProperty') + struct.pack('<Q', 1)
                    + _fstr('None') + b'\0' + bytes([slot]))
        out += (_fstr('PlayTime') + _fstr('IntProperty') + struct.pack('<Q', 4) + b'\0'
                + struct.pack('<i', 3725))
    return out + filler + _fstr('None') + b'\0\0\0\0'


def empty_wgs(root: Path, xuid: int = 0x0009000001234567) -> Path:
    folder = root / f'{xuid:016X}_0000000000000000000000000A1B2C3D'
    folder.mkdir(parents=True)
    idx = Index(14, 0, 'KonamiDigitalEntertainmen.RG5_168atcksx2mfc!AppMGSDeltaShipping',
                133000000000000000, 3, str(uuid.uuid4()), bytes.fromhex('0000001000000000'))
    (folder / 'containers.index').write_bytes(idx.build())
    return folder
