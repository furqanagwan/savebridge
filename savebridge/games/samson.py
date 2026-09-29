"""Samson: A Tyndalston Story (Steam app 3634520, Xbox package 29692LiquidSwords.CriminalJustice).

Both builds run Unreal Engine 5.7 and write the same GVAS files, with the same
custom-version tables, no checksum and no account ID:

    Steam  %LOCALAPPDATA%/Samson/Saved/SaveGames/<Name>.sav   (per PC)
    Xbox   container <Name>, blob 'Data'

There is a single save slot made of three files that must travel together:
SaveGame (current state), SaveGame_Checkpoint_StartOfDay (restart point) and
SaveGameManifest (the menu summary: difficulty, day, level, debt, time played,
build). Settings and key bindings are optional.
"""

from __future__ import annotations

from ..unreal import find_name_ue5, find_scalar_ue5
from .base import Save
from .unreal_files import BLOB, SaveFile, UnrealFilesGame

SAVE = ('/Script/CJ.CJSaveGameV2',)


class Samson(UnrealFilesGame):
    id = 'samson'
    name = 'Samson: A Tyndalston Story'
    steam_app_id = 3634520
    xbox_package_prefix = '29692LiquidSwords.CriminalJustice_'
    process_prefixes = ('cjxpa', 'cj-win64', 'samson')
    steam_per_account = False
    steam_subdir = 'Samson/Saved/SaveGames'
    files = (
        SaveFile('SaveGame', SAVE, group='slot'),
        SaveFile('SaveGame_Checkpoint_StartOfDay', SAVE, group='slot'),
        SaveFile('SaveGameManifest', ('/Script/CJ.CJSaveGameManifestV1',), group='slot'),
        SaveFile('SharedGameSettings', ('/Script/CJLyraBase.LyraSettingsShared',), optional=True),
        SaveFile('EnhancedInputUserSettings', ('/Script/CJLyraBase.LyraInputUserSettings',),
                 optional=True),
    )

    def describe(self, save: Save) -> str:
        b = save.parts[BLOB]
        if save.key not in ('SaveGame', 'SaveGame_Checkpoint_StartOfDay', 'SaveGameManifest'):
            return 'settings'
        bits = []
        day, level = find_scalar_ue5(b, 'GameDay'), find_scalar_ue5(b, 'Level')
        if day is not None:
            bits.append(f'day {day}')
        if level is not None:
            bits.append(f'lvl {level}')
        debt = find_scalar_ue5(b, 'CurrentDebt')
        if debt is not None:
            bits.append(f'debt {debt:,.0f}')
        played = find_scalar_ue5(b, 'TotalTimePlayed')
        if played is not None:
            bits.append(f'{played / 3600:.1f} h')
        difficulty = find_name_ue5(b, 'DifficultyName')
        if difficulty:
            bits.append(difficulty)
        return ', '.join(bits) or 'present'
