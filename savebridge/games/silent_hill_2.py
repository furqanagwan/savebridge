"""SILENT HILL 2 (2024 remake) (Steam app 2124490, Xbox package KonamiDigitalEntertainmen.SILENTHILL2).

The usual Unreal layout, one file per Xbox container:

    Steam  %LOCALAPPDATA%/SilentHill2/Saved/SaveGames/<SteamID64>/<Name>.sav
    Xbox   container <Name>, blob 'Data'

SaveGameData_<N> uses the game's own 'VASb' wrapper: u32 header length,
u16 1, u16 0xDEAD, the SaveGame class (/Script/SHProto.SHSaveGame), a save
point GUID and the map name, then a compressed body. The other files
(PlayerProfile, PersistentData, InputRebinding, UcaSave) are plain UE 5.1 GVAS.
No account ID in the readable parts; files copy unchanged.
"""

from __future__ import annotations

import re
import struct

from ..unreal import GvasError, read_fstring
from .base import Save, SaveError
from .unreal_files import BLOB, SaveFile, UnrealFilesGame

SAVE_CLASS = '/Script/SHProto.SHSaveGame'
SLOTS = 30


class SilentHill2(UnrealFilesGame):
    id = 'silent-hill-2'
    name = 'SILENT HILL 2'
    steam_app_id = 2124490
    xbox_package_prefix = 'KonamiDigitalEntertainmen.SILENTHILL2_'
    process_prefixes = ('silenthill2', 'shproto')
    steam_subdir = 'SilentHill2/Saved/SaveGames'
    files = tuple(SaveFile(f'SaveGameData_{n}', (SAVE_CLASS,)) for n in range(SLOTS)) + (
        SaveFile('PersistentData', (), optional=True),
        SaveFile('PlayerProfile', (), optional=True),
        SaveFile('InputRebinding', (), optional=True),
        SaveFile('UcaSave', (), optional=True),
    )

    def slot_key(self, n: int) -> str:
        return f'SaveGameData_{n}'

    def _check(self, key: str, data: bytes) -> None:
        if not key.startswith('SaveGameData_'):
            if data[:4] != b'GVAS':
                raise SaveError(f'{key}: not an Unreal save file')
            return
        if len(data) < 16 or data[:4] != b'VASb' or data[10:12] != b'\xad\xde':
            raise SaveError(f'{key}: not a SILENT HILL 2 save')
        try:
            cls, _ = read_fstring(data, 12)
        except (struct.error, UnicodeDecodeError, GvasError):
            raise SaveError(f'{key}: unreadable save header') from None
        if cls != SAVE_CLASS:
            raise SaveError(f'{key}: holds {cls}, not a SILENT HILL 2 save game')

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        stem = filename.removesuffix('.sav')
        if stem == BLOB:
            stem = folder.rpartition('/')[2]
        if self._file(stem) is None or data[:4] not in (b'VASb', b'GVAS'):
            return None
        self._check(stem, data)
        return Save(stem, {BLOB: data}, name)

    def describe(self, save: Save) -> str:
        if not save.key.startswith('SaveGameData_'):
            return 'profile/settings'
        m = re.search(rb'(M_\w+)\0', save.parts[BLOB][:256])
        return f'map {m.group(1).decode()}' if m else 'save'

    def remap(self, save: Save, new_key: str) -> Save:
        if not re.fullmatch(r'SaveGameData_\d+', new_key) or not save.key.startswith('SaveGameData_'):
            raise SaveError(f'can only move a save to another SaveGameData_<number> slot ({new_key})')
        return save.with_key(new_key)
