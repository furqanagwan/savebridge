"""Dispatch (Steam app 2592160, Xbox package AdHocStudio.DispatchSeason1).

The usual Unreal layout, one file per Xbox container, same bytes (UE 4.27 GVAS):

    Steam  %LOCALAPPDATA%/Dispatch/Saved/SaveGames/<Name>.sav   (per PC)
    Xbox   container <Name>, blob 'Data'

SaveSlot<N> (+ _BACKUP) is the save (AdHocSaveGameV2), Index (+ _BACKUP) lists
each slot's latest scene and save time, so it travels with the saves.
CloudSettings is settings (--all). Steam also keeps LocalOnly/<SteamID64>/*.bak
copies of the same files; they are ignored. No account ID inside the files.
"""

from __future__ import annotations

from .unreal_files import SaveFile, UnrealFilesGame

SAVE = ('/Script/AdHocSaveGame.AdHocSaveGameV2',)
INDEX = ('/Script/AdHocSaveGame.AdHocSaveIndexV2',)


class Dispatch(UnrealFilesGame):
    id = 'dispatch'
    name = 'Dispatch'
    steam_app_id = 2592160
    xbox_package_prefix = 'AdHocStudio.DispatchSeason1_'
    process_prefixes = ('dispatch',)
    steam_per_account = False
    steam_subdir = 'Dispatch/Saved/SaveGames'
    files = tuple(
        f for n in range(5)
        for f in (SaveFile(f'SaveSlot{n}', SAVE), SaveFile(f'SaveSlot{n}_BACKUP', SAVE))
    ) + (
        SaveFile('Index', INDEX),
        SaveFile('Index_BACKUP', INDEX),
        SaveFile('CloudSettings', ('/Script/Dispatch.DispatchCloudSettings',), optional=True),
    )

    def slot_key(self, n: int) -> str:
        return f'SaveSlot{n}'
