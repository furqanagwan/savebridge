"""Recognising console saves (PlayStation 3/4/5) handed to import or submit.

PlayStation saves are encrypted on the console. A PC can only use them once a
save tool has decrypted them (Apollo Save Tool on a jailbroken console, or Save
Wizard): the export is a folder with the game's files plus the save's metadata,

    PS3   <save dir>/PARAM.SFO, PARAM.PFD, ...            (PFD: per-file keys and hashes)
    PS4   <save dir>/sce_sys/param.sfo, ... game files
    PS5   <save dir>/sce_sys/param.sfo, ... game files

PARAM.SFO ("\\0PSF") names the game (TITLE_ID like BLES01234, CUSA01234 or
PPSA01234) and holds the owner's account ID, so it is never copied into a
package. Each game then maps the console's files to its platform-neutral save
(Game.from_console); a console layout is only supported once a real save has
been tested, so most games answer "not yet".

Xbox Series X|S saves need nothing here: games that share cloud saves with
their PC version sync them into the PC save folder (see research.md).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

PLATFORM_NAMES = {'ps3': 'PlayStation 3', 'ps4': 'PlayStation 4', 'ps5': 'PlayStation 5'}


class SfoError(Exception):
    pass


def parse_sfo(data: bytes) -> dict[str, object]:
    """PARAM.SFO entries: key -> str, int or bytes."""
    if len(data) < 20 or data[:4] != b'\x00PSF':
        raise SfoError('not a PARAM.SFO file')
    _, keys_at, data_at, count = struct.unpack_from('<IIII', data, 4)
    out: dict[str, object] = {}
    for i in range(count):
        key_off, fmt, length, _max, value_off = struct.unpack_from('<HHIII', data, 20 + 16 * i)
        end = data.index(b'\0', keys_at + key_off)
        key = data[keys_at + key_off:end].decode('latin-1')
        raw = data[data_at + value_off:data_at + value_off + length]
        if fmt == 0x0404:
            out[key] = struct.unpack('<I', raw[:4])[0]
        elif fmt in (0x0204, 0x0004) and key not in ('ACCOUNT_ID', 'PARAMS', 'PARAMS2'):
            out[key] = raw.rstrip(b'\0').decode('utf-8', 'replace')
        else:
            out[key] = raw
    return out


@dataclass
class ConsoleSave:
    platform: str               # ps3, ps4, ps5
    folder: Path                # the save directory
    title_id: str
    title: str
    subtitle: str = ''
    files: dict[str, bytes] = field(default_factory=dict)  # game files only, paths relative to folder

    @property
    def platform_name(self) -> str:
        return PLATFORM_NAMES[self.platform]

    def label(self) -> str:
        sub = f' ({self.subtitle})' if self.subtitle else ''
        return f'{self.platform_name} save of {self.title}{sub}, {self.title_id}'


def _platform(title_id: str, sfo_in_sce_sys: bool) -> str:
    if title_id.startswith('PPSA'):
        return 'ps5'
    if title_id.startswith('CUSA') or sfo_in_sce_sys:
        return 'ps4'
    return 'ps3'


def find(paths: list[Path]) -> list[ConsoleSave]:
    """Console save folders among ``paths`` (folders searched recursively)."""
    found = []
    for root in paths:
        if not root.is_dir():
            continue
        for sfo in sorted(p for p in root.rglob('*') if p.name.upper() == 'PARAM.SFO' and p.is_file()):
            try:
                info = parse_sfo(sfo.read_bytes())
            except (SfoError, OSError, struct.error, ValueError):
                continue
            in_sce_sys = sfo.parent.name.lower() == 'sce_sys'
            folder = sfo.parent.parent if in_sce_sys else sfo.parent
            title_id = str(info.get('TITLE_ID', '') or info.get('SAVEDATA_DIRECTORY', ''))[:9]
            if not re.fullmatch(r'[A-Z]{4}\d{5}', title_id):
                continue
            files = {}
            for f in sorted(folder.rglob('*')):
                rel = f.relative_to(folder).as_posix()
                if f.is_file() and not rel.lower().startswith('sce_sys/') \
                        and f.name.upper() not in ('PARAM.SFO', 'PARAM.PFD', 'ICON0.PNG', 'PIC1.PNG'):
                    files[rel] = f.read_bytes()
            platform = _platform(title_id, in_sce_sys)
            found.append(ConsoleSave(
                platform, folder, title_id, str(info.get('TITLE', '')), str(info.get('SUB_TITLE', '')),
                files=files))
    return found
