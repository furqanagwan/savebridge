"""Beast of Reincarnation (Steam app 2001760, Xbox package Fictions.ProjectAibou).

One UE 5.4 file per Xbox container, same bytes on both stores:

    Steam  %LOCALAPPDATA%/BeastOfReincarnation/Saved/SaveGames/<Name>.sav   (per PC)
    Xbox   container <Name>, blob 'Data'

Every file is an AibouSaveDataContainer (mContainerVersion, mUncompressedSize,
mCompressedDataSize, mBuffer): a GVAS shell around a compressed payload. No
account ID in the readable parts.

borSaveDataNormal_<N> are save slots, borSaveDataNormal_AutoSave_<N> the
autosaves, and borSaveDataMeta (+ bup0/bup1 backups) is one index describing
all of them, so the index always travels with the slots. borSaveDataConfig is
settings (--all). borSaveDataLocalConfig is per machine and not handled.
"""

from __future__ import annotations

from .base import Save, SaveError
from .unreal_files import SaveFile, UnrealFilesGame

CONTAINER = ('/Script/BeastOfReincarnation.AibouSaveDataContainer',)
META = ('borSaveDataMeta', 'borSaveDataMetabup0', 'borSaveDataMetabup1')


class BeastOfReincarnation(UnrealFilesGame):
    id = 'beast-of-reincarnation'
    name = 'Beast of Reincarnation'
    verified = ('steam-to-xbox',)
    steam_app_id = 2001760
    xbox_package_prefix = 'Fictions.ProjectAibou_'
    process_prefixes = ('beastofreincarnation',)
    steam_per_account = False
    steam_subdir = 'BeastOfReincarnation/Saved/SaveGames'
    files = (tuple(SaveFile(f'borSaveDataNormal_{n}', CONTAINER) for n in range(200))
             + tuple(SaveFile(f'borSaveDataNormal_AutoSave_{n}', CONTAINER) for n in range(10))
             + tuple(SaveFile(m, CONTAINER) for m in META)
             + (SaveFile('borSaveDataConfig', CONTAINER, optional=True),))

    def slot_key(self, n: int) -> str:
        return f'borSaveDataNormal_{n}'

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        keys = {s.key for s in saves}
        if any(k.startswith('borSaveDataNormal') for k in keys) and 'borSaveDataMeta' not in keys:
            raise SaveError('save slots must be copied together with borSaveDataMeta, the index '
                            'that describes them')
        return saves
