"""Destroy All Humans! (2020) (Steam app 803330, Xbox package NordicGames.DestroyAllHumans).

Both builds run Unreal Engine 4.22.3 and write identical GVAS files, with the
same header and no checksum, to the same per-PC folder:

    %LOCALAPPDATA%/DH/Saved/SaveGames/
        DevAutoSave_<N>.sav   game progress (class /Script/BFGCore.BFGSaveGame)
        SaveOptions.sav       settings, key bindings, unlocked skins, last used save
                              (class /Script/BFGCore.BFGSaveOptions)

The Xbox build does not use Xbox cloud saves. Saves carry no account ID.

Destroy All Humans! 2 - Reprobed uses the same save classes but Unreal 4.27
and different worlds, and hangs this game on load, so its saves are refused.

SaveOptions is merged rather than replaced: the target keeps its settings, gains
the incoming unlocked skins, and its "last used save" points at the newest
imported save so Continue loads it.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import struct
from pathlib import Path, PurePosixPath

from ..platforms import LOCALAPPDATA, Account
from ..unreal import GvasError, fstring, read_fstring, read_header, read_props, replace_value
from .base import Game, ReadResult, Save, SaveError

SAVE_CLASS = '/Script/BFGCore.BFGSaveGame'
OPTIONS_CLASS = '/Script/BFGCore.BFGSaveOptions'
OPTIONS = 'options'
OPTIONS_FILE = 'SaveOptions.sav'
ENGINE = (4, 22)
WORLDS = {'TurnipseedFarm', 'Rockwell', 'SantaModesta', 'Capitol', 'UnionTown'}
DAH2_WORLDS = {'Bay_City', 'Albion', 'Takoshima', 'Tunguska', 'Solaris'}
WORLD_RE = re.compile(rb'/Game/Maps/Worlds/([A-Za-z_0-9]+)/')
SAVE_NAME = re.compile(r'[A-Za-z]+_\d+')


def _created(payload: bytes) -> dt.datetime | None:
    i = payload.find(b'm_oDateTime\x00')
    j = payload.find(b'DateTime\x00', i + 12) if i >= 0 else -1
    if j < 0:
        return None
    try:
        ticks = struct.unpack_from('<Q', payload, j + 9 + 16 + 1)[0]
        return dt.datetime(1, 1, 1) + dt.timedelta(microseconds=ticks // 10)
    except (struct.error, OverflowError):
        return None


MAP_RE = re.compile(rb'/Game/Maps/[A-Za-z]+/([A-Za-z_0-9]+)/')


def _last_world(payload: bytes) -> str | None:
    """Where the save was made, e.g. 'Rockwell' or 'Mothership'."""
    i = payload.find(b'm_strMapLevelName\x00')
    m = MAP_RE.search(payload, i, i + 200) if i >= 0 else None
    return m.group(1).decode() if m else None


def unlock_tags(payload: bytes) -> list[str]:
    """Unlocked skins: a GameplayTagContainer (int32 count, then FStrings)."""
    props, _ = read_props(payload, read_header(payload).body_start)
    p = props.get('m_profileUnlockTags')
    if p is None:
        return []
    n = struct.unpack_from('<i', payload, p.value)[0]
    o, tags = p.value + 4, []
    for _ in range(n):
        t, o = read_fstring(payload, o)
        tags.append(t)
    return tags


def merge_options(target: bytes, incoming: bytes, last_used: str | None) -> bytes:
    """Target's settings, plus incoming unlocked skins, pointing at ``last_used``."""
    mine = unlock_tags(target)
    merged = mine + [t for t in unlock_tags(incoming) if t not in mine]
    out = target
    props, _ = read_props(out, read_header(out).body_start)
    if 'm_profileUnlockTags' in props:
        value = struct.pack('<i', len(merged)) + b''.join(fstring(t) for t in merged)
        out = replace_value(out, props['m_profileUnlockTags'], value)
    props, _ = read_props(out, read_header(out).body_start)
    if last_used and 'm_strLastUsedSavegame' in props:
        out = replace_value(out, props['m_strLastUsedSavegame'], fstring(last_used))
    return out


class DestroyAllHumans(Game):
    id = 'destroy-all-humans'
    name = 'Destroy All Humans! (2020)'
    steam_app_id = 803330
    xbox_package_prefix = 'NordicGames.DestroyAllHumans_'
    process_prefixes = ('dh-win64',)
    xbox_uses_wgs = False
    steam_per_account = False

    def key_order(self, key: str) -> tuple:
        if key == OPTIONS:
            return (1, 0, key)
        m = re.search(r'(\d+)$', key)
        return (0, int(m.group(1)) if m else 0, key)

    def slot_key(self, n: int) -> str:
        return f'DevAutoSave_{n}'

    def describe(self, save: Save) -> str:
        p = save.parts['Data']
        if save.key == OPTIONS:
            return f'{len(unlock_tags(p))} skins unlocked'
        bits = []
        if save.created:
            bits.append(save.created.strftime('%Y-%m-%d %H:%M'))
        world = _last_world(p)
        if world:
            bits.append(world)
        return ', '.join(bits) or 'present'

    # ---- files (same folder and format for Steam and Xbox) -----------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return LOCALAPPDATA / 'DH' / 'Saved' / 'SaveGames'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for f in sorted(root.glob('*.sav')):
            try:
                s = self.identify(f.read_bytes(), f.name)
            except SaveError as e:
                r.warnings.append(f'{f.name}: {e}')
                continue
            if s is not None:
                r.offer(s, (s.created or dt.datetime.min, f.stat().st_mtime))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = root / (OPTIONS_FILE if save.key == OPTIONS else f'{save.key}.sav')
        tmp = p.with_name(p.name + '.tmp')
        tmp.write_bytes(save.parts['Data'])
        os.replace(tmp, p)

    # ---- importing ----------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        try:
            h = read_header(data)
        except GvasError:
            return None
        if h.save_class not in (SAVE_CLASS, OPTIONS_CLASS):
            return None
        if h.engine[:2] != ENGINE:
            raise SaveError(f'saved by Unreal Engine {h.engine[0]}.{h.engine[1]}, not '
                            f'{ENGINE[0]}.{ENGINE[1]}: probably Destroy All Humans! 2 - '
                            f'Reprobed, which this game cannot load')
        worlds = {m.decode() for m in WORLD_RE.findall(data)}
        if worlds & DAH2_WORLDS:
            raise SaveError(f'contains Destroy All Humans! 2 worlds ({", ".join(sorted(worlds))})')
        try:
            read_props(data, h.body_start)
        except GvasError as e:
            raise SaveError(str(e)) from None
        stem = PurePosixPath(name.replace('\\', '/').split(':')[-1]).stem
        if h.save_class == OPTIONS_CLASS:
            return Save(OPTIONS, {'Data': data}, name)
        if not SAVE_NAME.fullmatch(stem) or stem == 'SaveOptions':
            raise SaveError(f'cannot tell which save slot "{stem}" is; '
                            f'rename it DevAutoSave_<number>.sav')
        return Save(stem, {'Data': data}, name, _created(data))

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        games = [s for s in saves if s.key != OPTIONS]
        newest = max(games, key=lambda s: s.created or dt.datetime.min).key if games else None
        out = []
        for s in saves:
            if s.key == OPTIONS and OPTIONS in existing:
                data = merge_options(existing[OPTIONS].parts['Data'], s.parts['Data'], newest)
                s = Save(OPTIONS, {'Data': data}, s.source)
            out.append(s)
        return out

    def remap(self, save: Save, new_key: str) -> Save:
        if save.key == OPTIONS or not SAVE_NAME.fullmatch(new_key):
            raise SaveError(f'can only move a save to another DevAutoSave_<number> slot '
                            f'({save.key} -> {new_key})')
        return save.with_key(new_key)
