"""Darksiders Genesis (Steam app 710920, Xbox package NordicGames.60987E91223DD).

Both builds run the same Unreal Engine 4.22 game and write the same GVAS files,
no checksum and no account ID, to the same per-PC folder (the Xbox build does
not use Xbox cloud saves):

    %LOCALAPPDATA%/THQ Nordic/Darksiders Genesis/Saved/SaveGames/user/
        SaveSlot_<N>.sav       profile N+1 on the title screen (three profiles)
        SaveSlot_<N>.sav.bak   the game's previous copy of that profile

Class /Script/DarksidersGenesis.MayhemSaveGame. A save doesn't record its slot,
so it can move to any profile. It does list the achievements it has awarded
(AwardedAchievements); that list is kept as it is.
"""

from __future__ import annotations

import os
import re
import struct
from pathlib import Path

from ..platforms import LOCALAPPDATA, Account
from ..unreal import GvasError, read_fstring, read_header, read_props
from .base import Game, ReadResult, Save, SaveError

SAVE_CLASS = '/Script/DarksidersGenesis.MayhemSaveGame'
NAME = re.compile(r'SaveSlot_(\d+)\.sav', re.I)


def check(data: bytes, name: str) -> None:
    try:
        h = read_header(data)
    except GvasError as e:
        raise SaveError(f'{name}: not an Unreal save ({e})') from None
    if h.save_class != SAVE_CLASS:
        raise SaveError(f'{name}: not a Darksiders Genesis save ({h.save_class})')


def summary(data: bytes) -> str:
    try:
        h = read_header(data)
        props, _ = read_props(data, h.body_start)
    except GvasError:
        return 'unreadable'

    def num(key, fmt='<i'):
        p = props.get(key)
        return struct.unpack_from(fmt, data, p.value)[0] if p else 0

    hours, minutes = num('PlayTimeHours'), num('PlayTimeMinutes')
    level = ''
    if 'CheckpointWorld' in props:
        world = read_fstring(data, props['CheckpointWorld'].value)[0]
        m = re.search(r'Level_(\d+)$', world)
        level = f', level {int(m.group(1))}' if m else ''
    awarded = ''
    if 'AwardedAchievements' in props:
        count = struct.unpack_from('<i', data, props['AwardedAchievements'].value)[0]
        awarded = f', {count} achievements recorded'
    return f'{hours}h {minutes:02d}m played{level}{awarded}'


class DarksidersGenesis(Game):
    id = 'darksiders-genesis'
    name = 'Darksiders Genesis'
    steam_app_id = 710920
    xbox_package_prefix = 'NordicGames.60987E91223DD_'
    process_prefixes = ('darksidersgenesis', 'darksiders genesis', 'projectmayhem')
    xbox_uses_wgs = False
    steam_per_account = False
    verified = ('steam-to-xbox',)
    note = 'Steam and Xbox share one save folder; profiles 1-3 are SaveSlot_0-2'

    def key_order(self, key: str) -> tuple:
        return (int(key.removeprefix('slot')),) if key.removeprefix('slot').isdigit() else (99,)

    def slot_key(self, n: int) -> str:
        return f'slot{n}'

    def describe(self, save: Save) -> str:
        n = int(save.key.removeprefix('slot'))
        return f'profile {n + 1}: {summary(save.parts["Data"])}'

    def save_dir(self, platform: str, account: Account) -> Path:
        return LOCALAPPDATA / 'THQ Nordic' / 'Darksiders Genesis' / 'Saved' / 'SaveGames' / 'user'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for f in sorted(root.glob('SaveSlot_*.sav')):
            m = NAME.fullmatch(f.name)
            if not m:
                continue
            try:
                data = f.read_bytes()
                check(data, f.name)
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            key = f'slot{int(m.group(1))}'
            r.saves[key] = Save(key, {'Data': data}, f.name)
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        n = int(save.key.removeprefix('slot'))
        # The .bak is the game's fallback copy; keep it in step so it can't revert to an old save.
        for name in (f'SaveSlot_{n}.sav.bak', f'SaveSlot_{n}.sav'):
            p = root / name
            tmp = p.with_name(p.name + '.savebridge-tmp')
            tmp.write_bytes(save.parts['Data'])
            os.replace(tmp, p)

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        m = NAME.fullmatch(filename)
        if not m:
            return None
        check(data, filename)
        return Save(f'slot{int(m.group(1))}', {'Data': data}, folder)

    def remap(self, save: Save, new_key: str) -> Save:
        if not re.fullmatch(r'slot[0-2]', new_key):
            raise SaveError(f'Darksiders Genesis has three profiles: slot0, slot1 or slot2, not {new_key}')
        return save.with_key(new_key)
