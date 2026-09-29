"""Finding Steam and Xbox accounts on this PC."""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

STEAM_ID64_BASE = 76561197960265728
LOCALAPPDATA = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))


@dataclass(frozen=True)
class SteamAccount:
    steamid64: int
    name: str = ''

    def __str__(self) -> str:
        return f'{self.steamid64}' + (f' ({self.name})' if self.name else '')


@dataclass(frozen=True)
class XboxAccount:
    xuid: int
    folder: Path  # the wgs/<XUID>_<SCID> directory

    def __str__(self) -> str:
        return f'{self.xuid} ({self.folder.name})'


def parse_steam_id(text: str) -> int:
    """Accept a SteamID64, a 32-bit account ID, or [U:1:n]."""
    m = re.fullmatch(r'\[?U:1:(\d+)\]?', text.strip())
    n = int(m.group(1)) if m else int(text.strip())
    return n if n >= STEAM_ID64_BASE else n + STEAM_ID64_BASE


def parse_xuid(text: str) -> int:
    """Accept a decimal XUID, 0x-prefixed hex, or the hex from a wgs folder name."""
    t = text.strip().split('_')[0]
    if t.lower().startswith('0x'):
        return int(t, 16)
    if len(t) == 16 and (t.startswith('000') or not t.isdigit()):
        return int(t, 16)
    return int(t)


def _reg_value(path: str, name: str):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except (ImportError, OSError):
        return None


def steam_install() -> Path | None:
    p = _reg_value(r'Software\Valve\Steam', 'SteamPath')
    if p and Path(p).is_dir():
        return Path(p)
    default = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Steam'
    return default if default.is_dir() else None


def steam_users() -> list[SteamAccount]:
    """Accounts that have signed in to Steam on this PC."""
    root = steam_install()
    f = root / 'config' / 'loginusers.vdf' if root else None
    if not f or not f.is_file():
        return []
    text = f.read_text(encoding='utf-8', errors='replace')
    users = []
    for m in re.finditer(r'"(\d{17})"\s*\{(.*?)\}', text, re.S):
        persona = re.search(r'"PersonaName"\s*"([^"]*)"', m.group(2))
        users.append(SteamAccount(int(m.group(1)), persona.group(1) if persona else ''))
    return users


def active_steam_user() -> int | None:
    aid = _reg_value(r'Software\Valve\Steam\ActiveProcess', 'ActiveUser')
    return aid + STEAM_ID64_BASE if aid else None


def xbox_accounts(package_prefix: str) -> list[XboxAccount]:
    """One per Xbox profile that has run the game (a wgs/<XUID>_<SCID> folder)."""
    out = []
    for pkg in sorted((LOCALAPPDATA / 'Packages').glob(package_prefix + '*')):
        wgs = pkg / 'SystemAppData' / 'wgs'
        if not wgs.is_dir():
            continue
        for d in sorted(wgs.iterdir()):
            m = re.fullmatch(r'([0-9A-Fa-f]{16})_[0-9A-Fa-f]+', d.name)
            if m and (d / 'containers.index').is_file():
                out.append(XboxAccount(int(m.group(1), 16), d))
    return out


def running_processes() -> set[str]:
    try:
        out = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}


def long_path(p: Path) -> Path:
    """Opt out of Windows' 260-character path limit (WGS paths get close to it)."""
    if os.name != 'nt':
        return p
    s = str(Path(p).absolute())
    return Path(s if s.startswith('\\\\?\\') else '\\\\?\\' + s)


BACKUP_ROOT = LOCALAPPDATA / 'savebridge' / 'backups'


def backup(src: Path, game_id: str, label: str) -> Path | None:
    """Zip up ``src`` before it is changed. Restore by extracting over it."""
    src = long_path(src)
    if not src.exists():
        return None
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    dest = BACKUP_ROOT / game_id / f'{stamp}-{label}.zip'
    long_path(dest.parent).mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(long_path(dest), 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob('*')):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return dest
