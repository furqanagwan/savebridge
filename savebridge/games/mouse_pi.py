"""MOUSE: P.I. For Hire (Steam app 2416450, Xbox package PlaySideStudiosLTD.MOUSEP.I.ForHire).

    Steam  %USERPROFILE%/AppData/LocalLow/Fumi Games/MOUSE/Save/*.rsf    (per PC)
           %USERPROFILE%/AppData/LocalLow/Fumi Games/MOUSE/Local/*.rsf
    Xbox   one container 'MouseContainer' holding all of those files, flat

Files are the same on both (a Unity game):
    save<N>.rsf, checkpoint<N>.rsf, auto.rsf   game saves (.NET-serialized
                                               SaveSystem.GameMetadata + data)
    profile.rsf (+ _backup)    JSON: "a"/"b" = save that Continue loads,
                               "c" settings, "d" bindings, "f" achievement
                               counters, "g" collection progress
    local-profile.rsf (+ _backup)   JSON machine settings (resolution etc.)

Logical saves: 'game' (all save/checkpoint/auto files, replaced as a set so two
playthroughs never mix), 'profile' (merged: the target keeps its settings and
achievement counters and only takes the Continue pointer), 'local' (--all).
No account ID anywhere.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..platforms import Account
from .base import Game, ReadResult, Save, SaveError

CONTAINER = 'MouseContainer'
GAME, PROFILE, LOCAL = 'game', 'profile', 'local'
GAME_FILE = re.compile(r'(save\d+|checkpoint\d+|auto)\.rsf')
PROFILE_FILES = ('profile.rsf', 'profile_backup.rsf')
LOCAL_FILES = ('local-profile.rsf', 'local-profile_backup.rsf')
ALL_GAME_NAMES = ([f'save{n}.rsf' for n in range(100)] + [f'checkpoint{n}.rsf' for n in range(10)]
                  + ['auto.rsf'])


def key_of(filename: str) -> str | None:
    if GAME_FILE.fullmatch(filename):
        return GAME
    if filename in PROFILE_FILES:
        return PROFILE
    if filename in LOCAL_FILES:
        return LOCAL
    return None


def continue_pointer(profile: bytes) -> dict[str, str]:
    text = profile.decode('utf-8-sig')
    return {k: m.group(1) for k in ('a', 'b')
            if (m := re.search(rf'^\s*"{k}":\s*"([^"]*)"', text, re.M))}


def set_continue(profile: bytes, pointer: dict[str, str]) -> bytes:
    text = profile.decode('utf-8-sig')
    for k, v in pointer.items():
        text, n = re.subn(rf'^(\s*"{k}":\s*)"[^"]*"', lambda m, v=v: f'{m.group(1)}"{v}"', text, count=1,
                          flags=re.M)
        if n != 1:
            raise SaveError(f'profile.rsf has no "{k}" field')
    return text.encode('utf-8')


class MousePi(Game):
    id = 'mouse-pi'
    name = 'MOUSE: P.I. For Hire'
    verified = ('steam-to-xbox',)
    steam_app_id = 2416450
    xbox_package_prefix = 'PlaySideStudiosLTD.MOUSEP.I.ForHire_'
    process_prefixes = ('mouse',)
    steam_per_account = False
    xbox_keep_other_blobs = True

    def key_order(self, key: str) -> tuple:
        return ([GAME, PROFILE, LOCAL].index(key),)

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if k != LOCAL]

    def describe(self, save: Save) -> str:
        if save.key == GAME:
            saves = sum(1 for n in save.parts if n.startswith('save'))
            return f'{saves} saves + {len(save.parts) - saves} checkpoints/auto'
        if save.key == PROFILE:
            ptr = continue_pointer(save.parts.get('profile.rsf', b'{}'))
            return f'settings + achievement counters; continue: {ptr.get("a", "?")}'
        return 'machine settings'

    def _group(self, files: dict[str, bytes], source: str) -> dict[str, Save]:
        out: dict[str, dict[str, bytes]] = {}
        for name, data in files.items():
            key = key_of(name)
            if key:
                out.setdefault(key, {})[name] = data
        return {k: Save(k, p, source) for k, p in out.items()}

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return (Path(os.environ.get('USERPROFILE', Path.home())) / 'AppData' / 'LocalLow'
                / 'Fumi Games' / 'MOUSE')

    def read_files(self, platform: str, root: Path) -> ReadResult:
        files = {}
        for sub in ('Save', 'Local'):
            d = root / sub
            if d.is_dir():
                files.update({p.name: p.read_bytes() for p in d.iterdir() if p.is_file()})
        return ReadResult(self._group(files, str(root)))

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        d = root / ('Local' if save.key == LOCAL else 'Save')
        d.mkdir(parents=True, exist_ok=True)
        if save.key == GAME:  # replace the whole set of saves
            for p in d.iterdir():
                if GAME_FILE.fullmatch(p.name) and p.name not in save.parts:
                    p.unlink()
        for name, data in save.parts.items():
            tmp = d / f'{name}.savebridge-tmp'
            tmp.write_bytes(data)
            os.replace(tmp, d / name)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return GAME if container == CONTAINER else None

    def decode_xbox_all(self, container: str, blobs: dict[str, bytes]) -> list[Save]:
        return list(self._group(blobs, container).values()) if container == CONTAINER else []

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        return self.decode_xbox_all(container, blobs)[0]

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return CONTAINER

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return dict(save.parts)

    def xbox_stale_blobs(self, save: Save) -> tuple[str, ...]:
        return tuple(n for n in ALL_GAME_NAMES if n not in save.parts) if save.key == GAME else ()

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        key = key_of(filename)
        if key is None:
            return None
        if key == GAME and b'S\x00a\x00v\x00e\x00S\x00y\x00s\x00t\x00e\x00m\x00' not in data[:200]:
            raise SaveError(f'{filename} is not a MOUSE: P.I. For Hire save')
        if key != GAME and not data.lstrip(b'\xef\xbb\xbf').startswith(b'{'):
            raise SaveError(f'{filename} is not a MOUSE: P.I. For Hire profile')
        top = folder.rpartition('/')[0] if folder.rpartition('/')[2] in ('Save', 'Local') else folder
        return Save(key, {filename: data}, top)

    def import_root(self, folder: str) -> str:
        head, _, last = folder.replace('\\', '/').rpartition('/')
        return head if last in ('Save', 'Local') else folder

    def collect(self, found: list[Save]) -> ReadResult:
        files: dict[str, bytes] = {}
        for s in found:
            files.update(s.parts)
        return ReadResult(self._group(files, found[0].source if found else ''))

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        out = []
        for s in saves:
            if s.key == PROFILE and PROFILE in existing:
                # Keep the target's settings and achievement counters; take only
                # which save Continue loads.
                pointer = continue_pointer(s.parts['profile.rsf'])
                mine = existing[PROFILE].parts
                s = Save(PROFILE, {n: set_continue(mine[n], pointer) for n in PROFILE_FILES if n in mine},
                         s.source)
            out.append(s)
        return out
