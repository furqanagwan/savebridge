"""Kingdom Come: Deliverance II (Steam app 1771300, Xbox package DeepSilver.77536C3FE941).

Saves are grouped into playthroughs ("playlines"):

    Steam  %USERPROFILE%/Saved Games/kingdomcome2/saves/playline<N>/*.whs   (per PC)
    Xbox   WGS container 'saves/playline<N>', one blob per .whs file

A .whs file is the same on both: 0xFFFFFFFF, u32 length, an XML
<C_SaveGameDescription> (save id and type, time, level, build, DLCs and PC mods
used), then compressed game data. There is no account ID (PlayerId is 0) and
no playline number inside, so a playthrough can be imported into any free
playline. Newer builds load older saves. Profiles/settings are left alone.

Downloads often hold hundreds of saves; only the ones asked for (--only / the
newest by default) need to go across, which also keeps the Xbox cloud quota in
check.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import struct
from pathlib import Path

from ..platforms import Account
from .base import Game, ReadResult, Save, SaveError

PLAYLINE = re.compile(r'playline(\d+)')


def description(data: bytes) -> str:
    if len(data) < 8 or data[:4] != b'\xff\xff\xff\xff':
        raise SaveError('not a Kingdom Come: Deliverance II save')
    n = struct.unpack_from('<I', data, 4)[0]
    text = data[8:8 + n].decode('utf-8', 'replace')
    if '<C_SaveGameDescription' not in text:
        raise SaveError('not a Kingdom Come: Deliverance II save')
    return text


def attr(desc: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', desc)
    return m.group(1) if m else None


def newest_first(parts: dict[str, bytes]) -> list[str]:
    return sorted(parts, key=lambda n: int(attr(description(parts[n]), 'SaveId') or 0), reverse=True)


class Kcd2(Game):
    id = 'kcd2'
    name = 'Kingdom Come: Deliverance II'
    steam_app_id = 1771300
    xbox_package_prefix = 'DeepSilver.77536C3FE941_'
    process_prefixes = ('kingdomcome',)
    steam_per_account = False

    def key_order(self, key: str) -> tuple:
        m = PLAYLINE.fullmatch(key)
        return (int(m.group(1)),) if m else (999,)

    def slot_key(self, n: int) -> str:
        return f'playline{n}'

    def describe(self, save: Save) -> str:
        newest = description(save.parts[newest_first(save.parts)[0]])
        hours = float((attr(newest, 'UIDescription') or '').split('|')[-2] or 0)
        return (f'{len(save.parts)} saves, newest id {attr(newest, "SaveId")}: '
                f'{attr(newest, "LevelName")}, {hours:.1f} h, build {attr(newest, "BuildInfo")}')

    def _save(self, key: str, parts: dict[str, bytes], source: str) -> Save:
        newest = description(parts[newest_first(parts)[0]])
        created = dt.datetime.fromtimestamp(int(attr(newest, 'SaveTime') or 0))
        return Save(key, parts, source, created)

    # ---- Steam ------------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        return Path(os.environ.get('USERPROFILE', Path.home())) / 'Saved Games' / 'kingdomcome2' / 'saves'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        for d in sorted(root.iterdir()):
            if d.is_dir() and PLAYLINE.fullmatch(d.name):
                parts = {p.name: p.read_bytes() for p in d.glob('*.whs')}
                if parts:
                    r.saves[d.name] = self._save(d.name, parts, str(d))
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        d = root / save.key
        d.mkdir(parents=True, exist_ok=True)
        for name, data in save.parts.items():
            tmp = d / f'{name}.savebridge-tmp'
            tmp.write_bytes(data)
            os.replace(tmp, d / name)

    # ---- Xbox -------------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        folder, _, line = container.partition('/')
        return line if folder == 'saves' and PLAYLINE.fullmatch(line) else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return f'saves/{key}'

    def xbox_reserved(self, key: str) -> int:
        return 1  # what the game writes for its save containers

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        saves = {n: d for n, d in blobs.items() if n.endswith('.whs')}
        if not saves:
            raise SaveError(f'{container} has no .whs saves')
        return self._save(self.xbox_key(container), saves, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        return dict(save.parts)

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        folder, _, filename = name.replace('\\', '/').rpartition('/')
        if not filename.endswith('.whs'):
            return None
        description(data)
        m = PLAYLINE.search(folder.rpartition('/')[2]) or PLAYLINE.search(folder)
        key = f'playline{m.group(1)}' if m else 'playline0'
        return Save(key, {filename: data}, folder)

    def collect(self, found: list[Save]) -> ReadResult:
        parts: dict[str, dict[str, bytes]] = {}
        for s in found:
            parts.setdefault(s.key, {}).update(s.parts)
        return ReadResult({k: self._save(k, p, found[0].source) for k, p in parts.items()})

    def remap(self, save: Save, new_key: str) -> Save:
        if not PLAYLINE.fullmatch(new_key):
            raise SaveError(f'saves can only move to another playline<number>, not {new_key}')
        return Save(new_key, save.parts, save.source, save.created)

    def pick_files(self, save: Save, spec: str) -> Save:
        """Keep only some .whs files: 'newest', 'newest:N', or comma-separated names."""
        m = re.fullmatch(r'newest(?::(\d+))?', spec.strip())
        if m:
            names = newest_first(save.parts)[:int(m.group(1) or 1)]
        else:
            names = [n.strip() for n in spec.split(',') if n.strip()]
            missing = [n for n in names if n not in save.parts]
            if missing:
                raise SaveError(f'not in {save.key}: {", ".join(missing)}')
        return Save(save.key, {n: save.parts[n] for n in names}, save.source, save.created)
