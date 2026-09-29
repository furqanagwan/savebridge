"""Reading and writing a game's saves for a given account, on either platform."""

from __future__ import annotations

import datetime as dt
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .games import Game, ReadResult, Save, SaveError
from .platforms import (Account, LocalAccount, SteamAccount, active_steam_user, backup,
                        long_path, parse_steam_id, parse_xuid, running_processes,
                        steam_users, xbox_accounts)
from .wgs import WgsError, WgsStore

MAX_IMPORT_FILE = 64 * 1024 * 1024


@dataclass
class Target:
    """One account's save location for one game on one platform."""
    game: Game
    platform: str  # 'steam' or 'xbox'
    account: Account

    @property
    def uses_wgs(self) -> bool:
        return self.platform == 'xbox' and self.game.xbox_uses_wgs

    @property
    def path(self) -> Path:
        if self.uses_wgs:
            return self.account.folder
        return self.game.save_dir(self.platform, self.account)

    @property
    def io_path(self) -> Path:
        return long_path(self.path)

    def __str__(self) -> str:
        return f'{self.platform.capitalize()}: {self.account}'

    # ---- read ---------------------------------------------------------------

    def read(self) -> ReadResult:
        if not self.uses_wgs:
            if not self.io_path.is_dir():
                return ReadResult()
            return self.game.read_files(self.platform, self.io_path)
        r = ReadResult()
        store = WgsStore(self.io_path)
        for e in store.live_entries():
            key = self.game.xbox_key(e.name)
            if key is None:
                continue
            try:
                s = self.game.decode_xbox(e.name, store.read_blobs(e))
            except (SaveError, WgsError, OSError) as ex:
                r.warnings.append(f'{e.name}: {ex}')
                continue
            r.offer(s, (s.created or dt.datetime.min, e.mtime))
        return r

    # ---- write --------------------------------------------------------------

    def prepare(self, saves: list[Save]) -> list[Save]:
        """What will actually be written: merged with existing saves, rebound to this account."""
        try:
            existing = self.read().saves
        except (SaveError, WgsError, OSError):
            existing = {}
        saves = self.game.prepare(saves, existing)
        return [self.game.rebind(s, self.account) for s in saves]

    def write(self, saves: list[Save]) -> None:
        """Write already-prepared saves."""
        if not self.uses_wgs:
            for s in saves:
                self.game.write_files(self.platform, self.io_path, s)
            return
        store = WgsStore(self.io_path)
        existing = [e.name for e in store.live_entries()]
        changes, reserved = {}, {}
        for s in saves:
            name = self.game.xbox_container(s.key, existing)
            changes[name] = self.game.encode_xbox(s)
            reserved[name] = self.game.xbox_reserved(s.key)
            existing.append(name)
        store.write(changes, reserved)

    def verify(self, saves: list[Save]) -> None:
        after = self.read().saves
        for s in saves:
            if s.key not in after or after[s.key].parts != s.parts:
                raise SaveError(f'verification failed for {s.key}')


# ---- choosing accounts -------------------------------------------------------

def steam_candidates(game: Game) -> list[SteamAccount]:
    """Steam accounts signed in on this PC, plus any with saves on disk."""
    known = {a.steamid64: a for a in steam_users()}
    parent = game.save_dir('steam', SteamAccount(0)).parent
    if parent.is_dir():
        for d in parent.iterdir():
            if d.is_dir() and re.fullmatch(r'\d{17}', d.name):
                known.setdefault(int(d.name), SteamAccount(int(d.name)))
    return sorted(known.values(), key=lambda a: a.steamid64)


def resolve_steam(game: Game, wanted: str | None) -> Account:
    if not game.steam_per_account:
        return LocalAccount()
    cands = steam_candidates(game)
    if wanted:
        sid = parse_steam_id(wanted)
        return next((a for a in cands if a.steamid64 == sid), SteamAccount(sid))
    with_saves = [a for a in cands if game.save_dir('steam', a).is_dir()]
    active = active_steam_user()
    for pool in (cands, with_saves):
        hit = next((a for a in pool if a.steamid64 == active), None)
        if hit:
            return hit
    if len(with_saves) == 1:
        return with_saves[0]
    if len(cands) == 1:
        return cands[0]
    if not cands:
        raise SaveError('no Steam account found; pass --steam-account <SteamID64>')
    listing = '\n  '.join(str(a) for a in cands)
    raise SaveError(f'several Steam accounts found, pick one with --steam-account:\n  {listing}')


def resolve_xbox(game: Game, wanted: str | None) -> Account:
    if not game.xbox_uses_wgs:
        return LocalAccount()
    cands = xbox_accounts(game.xbox_package_prefix)
    if wanted:
        xuid = parse_xuid(wanted)
        hit = next((a for a in cands if a.xuid == xuid), None)
        if hit is None:
            raise SaveError(f'no Xbox save folder for XUID {xuid}. Launch the Xbox version '
                            f'once while signed in to that account, then try again.')
        return hit
    if not cands:
        raise SaveError(f'no Xbox save folder for {game.name}. Launch the Xbox version once '
                        f'while signed in, then try again.')
    if len(cands) > 1:
        listing = '\n  '.join(str(a) for a in cands)
        raise SaveError(f'several Xbox accounts found, pick one with --xbox-account:\n  {listing}')
    return cands[0]


def resolve(game: Game, platform: str, steam: str | None, xbox: str | None) -> Target:
    if platform == 'steam':
        return Target(game, 'steam', resolve_steam(game, steam))
    return Target(game, 'xbox', resolve_xbox(game, xbox))


# ---- importing arbitrary files -----------------------------------------------

def _display(p) -> str:
    return str(p).removeprefix('\\\\?\\')


def _iter_wgs(store_dir: Path):
    """Blobs of an Xbox save folder, named <folder>/<container>/<blob>."""
    store = WgsStore(store_dir)
    for e in store.live_entries():
        try:
            blobs = store.read_blobs(e)
        except (WgsError, OSError):
            continue
        for blob, data in blobs.items():
            yield _display(store_dir), f'{_display(store_dir)}/{e.name}/{blob}', data


def _iter_files(paths: list[Path]):
    """(group, name, bytes) for every candidate file. A group is the folder a save set lives in."""
    for path in paths:
        if path.is_dir():
            if (path / 'containers.index').is_file():
                yield from _iter_wgs(path)
                continue
            for dirpath, dirnames, filenames in os.walk(path):
                d = Path(dirpath)
                if (d / 'containers.index').is_file():
                    dirnames.clear()
                    yield from _iter_wgs(d)
                    continue
                for f in sorted(filenames):
                    p = d / f
                    if p.stat().st_size <= MAX_IMPORT_FILE:
                        yield _display(d), _display(p), p.read_bytes()
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for info in z.infolist():
                    if not info.is_dir() and info.file_size <= MAX_IMPORT_FILE:
                        parent = info.filename.rpartition('/')[0]
                        yield (f'{path.name}:{parent}', f'{path.name}:{info.filename}',
                               z.read(info))
        elif path.is_file():
            if path.stat().st_size <= MAX_IMPORT_FILE:
                yield _display(path.parent), _display(path), path.read_bytes()
        else:
            raise SaveError(f'not found: {_display(path)}')


def scan(game: Game, paths: list[Path], strict: bool = True) -> ReadResult:
    """Find saves for ``game`` among any files, folders or zips, from either platform.

    Refuses input holding saves from more than one folder: a download often
    bundles several save sets, and mixing their files would corrupt the save.
    """
    found, warnings, groups = [], [], {}
    for group, name, data in _iter_files(paths):
        try:
            s = game.identify(data, name, strict)
        except SaveError as e:
            warnings.append(f'{name}: {e}')
            continue
        if s is not None:
            found.append(s)
            groups.setdefault(group, []).append(s.key)
    if len(groups) > 1:
        listing = '\n  '.join(f'{g}  ({", ".join(sorted(set(k)))})' for g, k in sorted(groups.items()))
        raise SaveError(f'found saves in {len(groups)} different folders; import one at a time:'
                        f'\n  {listing}')
    r = game.collect(found)
    r.warnings[:0] = warnings
    return r


# ---- safety ------------------------------------------------------------------

def ensure_game_closed(game: Game) -> None:
    running = sorted(p for p in running_processes()
                     if any(p.startswith(pre) for pre in game.process_prefixes))
    if running:
        raise SaveError(f'close {game.name} first (running: {", ".join(running)})')


def backup_target(t: Target) -> Path | None:
    who = getattr(t.account, 'steamid64', None) or getattr(t.account, 'xuid', None) or 'pc'
    return backup(t.path, t.game.id, f'{t.platform}-{who}')
