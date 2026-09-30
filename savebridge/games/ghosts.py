"""Call of Duty: Ghosts, campaign (Steam app 209160, Xbox package 38985CA0.CallofDutyGhostsPCMS).

    Steam  <Steam library>/steamapps/common/Call of Duty Ghosts/players2/savegame.svg   (per PC)
    Xbox   WGS container 'Gamerprofile_gdk':
               savegame.svg                    campaign progress
               save\\internal/snd_restart.svg  restart point for the current mission
               settings_c.zip.iw6, settings_s.zip.iw6   settings
           plus the game's own copy of those files in
           <drive>:/XboxGames/Call of Duty Ghosts/Content/players2/<decimal XUID>/

savegame.svg is the same IW6 format on both (u32 version 0x47, level name at
offset 32) with no owner ID and no checksum found, so it is copied unchanged.
When it is replaced, the old restart point is removed because it belongs to the
previous save; the game makes a new one when a mission starts. Multiplayer
progress is online and isn't handled.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..platforms import Account, XboxAccount, steam_game_dir, xbox_game_content
from .base import Game, ReadResult, Save, SaveError

CAMPAIGN = 'campaign'
SAVE = 'savegame.svg'
RESTART = 'save\\internal/snd_restart.svg'
CONTAINER = 'Gamerprofile_gdk'


def level(svg: bytes) -> str:
    return svg[32:64].split(b'\0')[0].decode('latin1', 'replace') or '?'


def check(data: bytes) -> None:
    if data[:4] != b'\x47\0\0\0':
        raise SaveError('savegame.svg is not a Call of Duty: Ghosts campaign save')


class Ghosts(Game):
    id = 'ghosts'
    name = 'Call of Duty: Ghosts (campaign)'
    verified = ('steam-to-xbox',)
    note = 'campaign progress; mission select only partly (Rorke Files not unlocked)'
    steam_app_id = 209160
    xbox_package_prefix = '38985CA0.CallofDutyGhostsPCMS_'
    process_prefixes = ('iw6sp', 'iw6mp', 'ghosts')
    steam_per_account = False
    xbox_keep_other_blobs = True

    def describe(self, save: Save) -> str:
        return f'level {level(save.parts[SAVE])}'

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        d = steam_game_dir('Call of Duty Ghosts')
        if d is None:
            raise SaveError('Steam is not installed')
        return d / 'players2'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        p = root / SAVE
        if not p.is_file():
            return ReadResult()
        data = p.read_bytes()
        try:
            check(data)
        except SaveError as e:
            return ReadResult(warnings=[str(e)])
        return ReadResult({CAMPAIGN: Save(CAMPAIGN, {SAVE: data}, str(root))})

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        tmp = root / f'{SAVE}.savebridge-tmp'
        tmp.write_bytes(save.parts[SAVE])
        os.replace(tmp, root / SAVE)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return CAMPAIGN if container == CONTAINER else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return CONTAINER

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if SAVE not in blobs:
            raise SaveError(f'{container} has no {SAVE}')
        check(blobs[SAVE])
        return Save(CAMPAIGN, {SAVE: blobs[SAVE]}, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {SAVE: save.parts[SAVE]}

    def xbox_stale_blobs(self, save: Save) -> tuple[str, ...]:
        return (RESTART,)

    def xbox_mirror(self, account: Account, container: str) -> Path | None:
        if container != CONTAINER:
            return None
        dirs = self.xbox_mirror_dirs(account)
        return dirs[0] if dirs else None

    def xbox_mirror_dirs(self, account: Account) -> list[Path]:
        content = xbox_game_content('Call of Duty Ghosts')
        if content is None or not isinstance(account, XboxAccount):
            return []
        return [content / 'players2' / str(account.xuid)]

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        if filename != SAVE or 'internal' in folder.rpartition('/')[2]:
            return None
        check(data)
        return Save(CAMPAIGN, {SAVE: data}, folder)
