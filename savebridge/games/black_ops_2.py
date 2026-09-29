"""Call of Duty: Black Ops II, campaign (Steam app 202970, Xbox package 38985CA0.CallofDutyBlackOps2PCMS).

The campaign keeps its files in a 'players' folder:

    Steam  <Steam library>/steamapps/common/Call of Duty Black Ops II/players/   (per PC)
    Xbox   WGS container 'players', one blob per file, plus a plain-file copy of it
           in SystemAppData/xgs/<XUID>_<id>/players/ that the game reads
           (XGameSaveFiles). Both are written together.

    savegame.svg   campaign progress (starts u32 27; level name at offset 32)
    savegame.foo   campaign profile; stores the owner's SteamID or XUID at offset 64
                   and a checksum in the first 4 bytes (algorithm unknown)
    bindings_sp.bdg, user_sp.cgp, user_common.cgp   campaign settings (optional)

The multiplayer and zombies files are not handled. Files are copied unchanged,
including the owner ID in savegame.foo: shared 100% saves load for other
accounts on Steam, so the game doesn't reject a foreign owner.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from ..platforms import Account, steam_game_dir
from .base import Game, ReadResult, Save, SaveError

CAMPAIGN = 'campaign'
SETTINGS = 'settings'
FILES = {CAMPAIGN: ('savegame.svg', 'savegame.foo'),
         SETTINGS: ('bindings_sp.bdg', 'user_sp.cgp', 'user_common.cgp')}
KEY_OF = {f: k for k, files in FILES.items() for f in files}
STEAM_ID64_BASE = 76561197960265728


def owner(foo: bytes) -> str:
    if len(foo) < 72:
        return '?'
    oid = struct.unpack_from('<Q', foo, 64)[0]
    if STEAM_ID64_BASE <= oid < STEAM_ID64_BASE + 2 ** 32:
        return f'Steam {oid}'
    if oid >> 48 == 0x0009:
        return f'Xbox {oid}'
    return f'id {oid}'


def level(svg: bytes) -> str:
    return svg[32:64].split(b'\0')[0].decode('latin1', 'replace') or '?'


class BlackOps2(Game):
    id = 'black-ops-2'
    name = 'Call of Duty: Black Ops II (campaign)'
    steam_app_id = 202970
    xbox_package_prefix = '38985CA0.CallofDutyBlackOps2PCMS_'
    process_prefixes = ('t6sp', 't6mp', 't6zm')
    steam_per_account = False
    xbox_keep_other_blobs = True

    def key_order(self, key: str) -> tuple:
        return (list(FILES).index(key),) if key in FILES else (9,)

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if k == CAMPAIGN]

    def describe(self, save: Save) -> str:
        if save.key == CAMPAIGN:
            return f'level {level(save.parts["savegame.svg"])}, owner {owner(save.parts["savegame.foo"])}'
        return f'{len(save.parts)} settings files'

    def _check(self, key: str, parts: dict[str, bytes]) -> None:
        if key == CAMPAIGN:
            missing = [f for f in FILES[CAMPAIGN] if f not in parts]
            if missing:
                raise SaveError(f'campaign save needs {", ".join(missing)} too')
            if parts['savegame.svg'][:4] != b'\x1b\0\0\0':
                raise SaveError('savegame.svg is not a Black Ops II campaign save')
            if parts['savegame.foo'][8:14] != b'\x02\0\0\x02\xbe\xef':
                raise SaveError('savegame.foo is not a Black Ops II campaign profile')

    def _group(self, files: dict[str, bytes], source: str) -> tuple[dict[str, Save], list[str]]:
        saves, warnings = {}, []
        for key, names in FILES.items():
            parts = {n: files[n] for n in names if n in files}
            if not parts:
                continue
            try:
                self._check(key, parts)
            except SaveError as e:
                warnings.append(str(e))
                continue
            saves[key] = Save(key, parts, source)
        return saves, warnings

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        d = steam_game_dir('Call of Duty Black Ops II')
        if d is None:
            raise SaveError('Steam is not installed')
        return d / 'players'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        files = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file() and p.name in KEY_OF}
        saves, warnings = self._group(files, str(root))
        return ReadResult(saves, warnings)

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name, data in save.parts.items():
            tmp = root / f'{name}.savebridge-tmp'
            tmp.write_bytes(data)
            os.replace(tmp, root / name)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return CAMPAIGN if container == 'players' else None

    def decode_xbox_all(self, container: str, blobs: dict[str, bytes]) -> list[Save]:
        if container != 'players':
            return []
        saves, warnings = self._group(blobs, container)
        if warnings and not saves:
            raise SaveError('; '.join(warnings))
        return list(saves.values())

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        return self.decode_xbox_all(container, blobs)[0]

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return 'players'

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return dict(save.parts)

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        key = KEY_OF.get(filename)
        return Save(key, {filename: data}, folder) if key else None

    def collect(self, found: list[Save]) -> ReadResult:
        files: dict[str, bytes] = {}
        for s in found:
            files.update(s.parts)
        saves, warnings = self._group(files, found[0].source if found else '')
        return ReadResult(saves, warnings)
