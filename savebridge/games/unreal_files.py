"""Base for the most common Unreal Engine layout: one .sav file per Xbox container.

    Steam  %LOCALAPPDATA%/<steam_subdir>/[<SteamID64>/]<Name>.sav
    Xbox   WGS container <Name>, single blob 'Data', same bytes

A game describes its files with ``SaveFile`` entries. Files sharing a
``group`` must travel together (e.g. a save and its menu summary), and
``optional`` files (settings) are only copied when asked for.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

from ..platforms import LOCALAPPDATA, Account, SteamAccount
from ..unreal import GvasError, read_header
from .base import Game, ReadResult, Save, SaveError

BLOB = 'Data'


@dataclass(frozen=True)
class SaveFile:
    name: str                  # file stem and Xbox container name
    classes: tuple[str, ...]   # SaveGame class paths this file may hold
    optional: bool = False     # settings etc.: copied only with --all / --only
    group: str = ''            # files in the same group must be copied together


class UnrealFilesGame(Game):
    steam_subdir: str = ''            # under %LOCALAPPDATA%
    files: tuple[SaveFile, ...] = ()

    # ---- keys ----------------------------------------------------------------

    def _file(self, key: str) -> SaveFile | None:
        return next((f for f in self.files if f.name == key), None)

    def key_order(self, key: str) -> tuple:
        names = [f.name for f in self.files]
        return (names.index(key),) if key in names else (len(names), key)

    def default_keys(self, keys: list[str]) -> list[str]:
        return [k for k in keys if (f := self._file(k)) and not f.optional]

    # ---- files -----------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        root = LOCALAPPDATA / self.steam_subdir
        if self.steam_per_account and isinstance(account, SteamAccount):
            root /= str(account.steamid64)
        return root

    def _check(self, key: str, data: bytes) -> None:
        f = self._file(key)
        try:
            cls = read_header(data).save_class
        except GvasError as e:
            raise SaveError(str(e)) from None
        if f and cls not in f.classes:
            raise SaveError(f'{key} holds {cls}, expected {" or ".join(f.classes)}')

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for f in self.files:
            p = root / f'{f.name}.sav'
            if not p.is_file():
                continue
            data = p.read_bytes()
            try:
                self._check(f.name, data)
            except SaveError as e:
                r.warnings.append(f'{p.name}: {e}')
                continue
            r.saves[f.name] = Save(f.name, {BLOB: data}, p.name,
                                   dt.datetime.fromtimestamp(p.stat().st_mtime))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = root / f'{save.key}.sav'
        tmp = p.with_name(p.name + '.tmp')
        tmp.write_bytes(save.parts[BLOB])
        os.replace(tmp, p)

    # ---- Xbox ------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        return container if self._file(container) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return key

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if BLOB not in blobs:
            raise SaveError('container has no Data blob')
        self._check(container, blobs[BLOB])
        return Save(container, {BLOB: blobs[BLOB]}, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return {BLOB: save.parts[BLOB]}

    # ---- importing ---------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        path = name.replace('\\', '/')
        folder, _, filename = path.rpartition('/')
        stem = filename.removesuffix('.sav')
        if stem == BLOB:  # a blob from an Xbox save folder: named after its container
            stem = folder.rpartition('/')[2]
        f = self._file(stem)
        if f is None or data[:4] != b'GVAS':
            return None
        self._check(stem, data)
        return Save(stem, {BLOB: data}, name)

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        keys = {s.key for s in saves}
        for group in {f.group for f in self.files if f.group}:
            members = [f.name for f in self.files if f.group == group]
            have = [m for m in members if m in keys]
            if have and len(have) != len(members):
                missing = [m for m in members if m not in keys]
                raise SaveError(f'{", ".join(have)} must be copied together with '
                                f'{", ".join(missing)}')
        return saves
