"""Cuphead (Steam app 268910, Xbox package StudioMDHR.20872A364DAA1).

    Steam  %APPDATA%/Cuphead/cuphead_player_data_v1_slot_<N>.sav   (per PC)
    Xbox   one container 'GameSaveContainer' with blobs named without '.sav':
               cuphead_player_data_v1_slot_<N>   the three save slots
               cuphead_settings_data_v1          settings (--all)
               r2|...                            Rewired controller map (left alone)

Saves are plain JSON with the same fields on both stores (a newer build adds a
few; Unity fills in missing ones on load). No account ID, and a save doesn't
record its own slot number, so it can move to any slot.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..platforms import Account
from .base import Game, ReadResult, Save, SaveError

CONTAINER = 'GameSaveContainer'
SLOT = re.compile(r'cuphead_player_data_v1_slot_(\d)')
SETTINGS = 'cuphead_settings_data_v1'


def parse(name: str, data: bytes) -> dict:
    try:
        j = json.loads(data.decode('utf-8-sig'))
    except (UnicodeDecodeError, ValueError):
        raise SaveError(f'{name}: not a Cuphead save (not JSON)') from None
    if name != SETTINGS and 'levelDataManager' not in j:
        raise SaveError(f'{name}: not a Cuphead save')
    return j


class Cuphead(Game):
    id = 'cuphead'
    name = 'Cuphead'
    verified = ('steam-to-xbox',)
    steam_app_id = 268910
    xbox_package_prefix = 'StudioMDHR.20872A364DAA1_'
    process_prefixes = ('cuphead',)
    steam_per_account = False
    xbox_keep_other_blobs = True

    def _key(self, stem: str) -> str | None:
        return stem if SLOT.fullmatch(stem) or stem == SETTINGS else None

    def key_order(self, key: str) -> tuple:
        m = SLOT.fullmatch(key)
        return (0, int(m.group(1))) if m else (1, 0)

    def slot_key(self, n: int) -> str:
        return f'cuphead_player_data_v1_slot_{n}'

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if k != SETTINGS]

    def describe(self, save: Save) -> str:
        if save.key == SETTINGS:
            return 'settings'
        j = parse(save.key, save.parts['Data'])
        levels = j.get('levelDataManager', {}).get('levelObjects', [])
        done = sum(1 for lv in levels if lv.get('completed'))
        coins = len(j.get('coinManager', {}).get('coins', []))
        return f'{done}/{len(levels)} levels, {coins} coins' if done or coins else 'empty'

    def _save(self, key: str, data: bytes, source: str) -> Save:
        parse(key, data)
        return Save(key, {'Data': data}, source)

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'Cuphead'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for p in sorted(root.glob('*.sav')):
            key = self._key(p.stem)
            if key is None:
                continue
            try:
                r.saves[key] = self._save(key, p.read_bytes(), p.name)
            except SaveError as e:
                r.warnings.append(str(e))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = root / f'{save.key}.sav'
        tmp = p.with_name(p.name + '.savebridge-tmp')
        tmp.write_bytes(save.parts['Data'])
        os.replace(tmp, p)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return 'cuphead_player_data_v1_slot_0' if container == CONTAINER else None

    def decode_xbox_all(self, container: str, blobs: dict[str, bytes]) -> list[Save]:
        if container != CONTAINER:
            return []
        return [self._save(k, blobs[k], container) for k in blobs if self._key(k)]

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        return self.decode_xbox_all(container, blobs)[0]

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return CONTAINER

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {save.key: save.parts['Data']}

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        key = self._key(filename.removesuffix('.sav'))
        return self._save(key, data, name) if key else None

    def remap(self, save: Save, new_key: str) -> Save:
        if not SLOT.fullmatch(new_key) or not SLOT.fullmatch(save.key):
            raise SaveError(f'can only move a save slot to another slot ({new_key})')
        return save.with_key(new_key)
