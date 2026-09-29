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


def gvas(save_class: str, props: bytes, engine=(4, 22, 3, 0), package: int = 517) -> bytes:
    """A real-shaped UE4 GVAS file (empty custom-version table)."""
    return (b'GVAS' + struct.pack('<ii', 2, package) + struct.pack('<HHHI', *engine)
            + _fstr(f'++UE4+Release-{engine[0]}.{engine[1]}') + struct.pack('<ii', 3, 0)
            + _fstr(save_class) + props + _fstr('None') + b'\0\0\0\0')


def prop(name: str, typ: str, value: bytes, extra: bytes = b'') -> bytes:
    return _fstr(name) + _fstr(typ) + struct.pack('<q', len(value)) + extra + b'\0' + value


def str_prop(name: str, value: str) -> bytes:
    return prop(name, 'StrProperty', _fstr(value))


def tags_prop(name: str, tags: list[str]) -> bytes:
    value = struct.pack('<i', len(tags)) + b''.join(_fstr(t) for t in tags)
    return prop(name, 'StructProperty', value, _fstr('GameplayTagContainer') + b'\0' * 16)


def dah_save(ticks: int = 637_300_000_000_000_000, world: str = 'Rockwell') -> bytes:
    desc = (_fstr('m_oDateTime') + _fstr('StructProperty') + struct.pack('<q', 8)
            + _fstr('DateTime') + b'\0' * 17 + struct.pack('<Q', ticks)
            + str_prop('m_strMapLevelName', f'/Game/Maps/Worlds/{world}/{world}_main')
            + _fstr('None'))
    return gvas('/Script/BFGCore.BFGSaveGame',
                prop('m_iVersion', 'IntProperty', struct.pack('<i', 1))
                + prop('m_description', 'StructProperty', desc,
                       _fstr('BFGSaveDescription') + b'\0' * 16))


def dah_options(tags: list[str], last_used: str = 'DevAutoSave_0', res: int = 1920) -> bytes:
    return gvas('/Script/BFGCore.BFGSaveOptions',
                str_prop('m_strLastUsedSavegame', last_used)
                + prop('m_iAAQuality', 'IntProperty', struct.pack('<i', res))
                + tags_prop('m_profileUnlockTags', tags))


def empty_wgs(root: Path, xuid: int = 0x0009000001234567) -> Path:
    folder = root / f'{xuid:016X}_0000000000000000000000000A1B2C3D'
    folder.mkdir(parents=True)
    idx = Index(14, 0, 'KonamiDigitalEntertainmen.RG5_168atcksx2mfc!AppMGSDeltaShipping',
                133000000000000000, 3, str(uuid.uuid4()), bytes.fromhex('0000001000000000'))
    (folder / 'containers.index').write_bytes(idx.build())
    return folder
