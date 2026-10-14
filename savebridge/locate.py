"""Where each game is installed and where its saves are, on both stores.

Read-only. Powers `savebridge locate` and the app's "Save locations" view.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from . import core
from .games import Game, SaveError
from .platforms import LocalAccount, long_path, steam_install, xbox_accounts
from .wgs import WgsError, WgsStore

APPMODEL = r'Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages'


def _iso(ts: float | None) -> str | None:
    return dt.datetime.fromtimestamp(ts).isoformat(timespec='seconds') if ts else None


def _filetime_iso(ft: int) -> str | None:
    """A Windows FILETIME (100 ns ticks since 1601) as local ISO time."""
    return _iso(ft / 1e7 - 11644473600) if ft else None


def folder_summary(path: Path) -> dict:
    """Whether a folder exists, how many files it holds and when one last changed."""
    p = long_path(path)
    out = {'path': str(path), 'exists': p.is_dir(), 'files': 0, 'modified': None}
    if not out['exists']:
        return out
    newest = 0.0
    try:
        for f in p.rglob('*'):
            if f.is_file():
                out['files'] += 1
                newest = max(newest, f.stat().st_mtime)
    except OSError:
        pass
    out['modified'] = _iso(newest)
    return out


# ---- Steam ----------------------------------------------------------------------

def steam_libraries() -> list[Path]:
    root = steam_install()
    if root is None:
        return []
    libs = [root]
    vdf = root / 'steamapps' / 'libraryfolders.vdf'
    if vdf.is_file():
        text = vdf.read_text(encoding='utf-8', errors='replace')
        libs += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s*"([^"]+)"', text)]
    seen, out = set(), []
    for lib in libs:
        key = str(lib).lower().rstrip('\\/')
        if key not in seen:
            seen.add(key)
            out.append(lib)
    return out


def steam_app_dir(app_id: int | None) -> Path | None:
    """The install folder from steamapps/appmanifest_<id>.acf, if Steam has the game installed."""
    if not app_id:
        return None
    for lib in steam_libraries():
        acf = lib / 'steamapps' / f'appmanifest_{app_id}.acf'
        if acf.is_file():
            m = re.search(r'"installdir"\s*"([^"]+)"', acf.read_text(encoding='utf-8', errors='replace'))
            if m:
                return lib / 'steamapps' / 'common' / m.group(1)
    return None


# ---- Xbox -----------------------------------------------------------------------

def xbox_packages() -> dict[str, str]:
    """Installed packages for this user: full name -> install folder (PackageRootFolder)."""
    try:
        import winreg
    except ImportError:
        return {}
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPMODEL) as root:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, name) as k:
                        out[name] = winreg.QueryValueEx(k, 'PackageRootFolder')[0]
                except OSError:
                    out[name] = ''
    except OSError:
        pass
    return out


def xbox_game_installs(roots: list[Path] | None = None) -> dict[str, str]:
    """GDK games in each drive's Xbox games folder: package name -> Content folder.

    Each drive's .GamingRoot names that folder ('RGBX', u32, UTF-16 path); every
    game has Content/appxmanifest.xml with its package Identity Name.
    """
    out = {}
    for root in roots if roots is not None else [Path(f'{c}:/') for c in 'CDEFGHIJKLMNOPQRSTUVWXYZ']:
        try:
            marker = (root / '.GamingRoot').read_bytes()
            folder = marker[8:].decode('utf-16-le').split('\0', 1)[0] or 'XboxGames'
            base = root / folder
            games = list(base.iterdir())
        except (OSError, UnicodeDecodeError):
            continue
        for g in games:
            manifest = g / 'Content' / 'appxmanifest.xml'
            try:
                m = re.search(r'<Identity\b[^>]*\bName="([^"]+)"', manifest.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                continue
            if m:
                out[m.group(1)] = str(g / 'Content')
    return out


def xbox_install(prefix: str, packages: dict[str, str]) -> dict:
    """Package name and install folder for a package-family prefix such as 'Foo.Bar_'."""
    name = prefix.rstrip('_')
    for ident, content in packages.get('__gdk__', {}).items():
        if ident.lower() == name.lower():
            return {'installed': True, 'package': ident, 'install_dir': content}
    for full, root in packages.items():
        if full == '__gdk__':
            continue
        if full.split('_', 1)[0].lower() == name.lower():
            return {'installed': True, 'package': full, 'install_dir': root or None}
    return {'installed': False, 'package': None, 'install_dir': None}


# ---- per game -------------------------------------------------------------------

def locate(game: Game, packages: dict[str, str] | None = None) -> dict:
    packages = installed_packages() if packages is None else packages
    steam_dir = steam_app_dir(game.steam_app_id)
    steam = {'app_id': game.steam_app_id, 'installed': bool(steam_dir and steam_dir.is_dir()),
             'install_dir': str(steam_dir) if steam_dir else None,
             'per_pc': not game.steam_per_account, 'saves': [], 'error': None}
    try:
        accounts = core.steam_candidates(game) if game.steam_per_account else [LocalAccount()]
        for a in accounts:
            entry = folder_summary(game.save_dir('steam', a))
            entry['account'] = str(getattr(a, 'steamid64', '') or 'this PC')
            entry['name'] = getattr(a, 'name', '') or ''
            steam['saves'].append(entry)
    except (SaveError, OSError) as e:
        steam['error'] = str(e)

    xbox = {'package_prefix': game.xbox_package_prefix.rstrip('_') or None, 'per_pc': not game.xbox_uses_wgs,
            'cloud_saves': game.xbox_uses_wgs, 'saves': [], 'error': None,
            **(xbox_install(game.xbox_package_prefix, packages) if game.xbox_package_prefix
               else {'installed': False, 'package': None, 'install_dir': None})}
    try:
        if game.xbox_package_prefix and game.xbox_uses_wgs:
            for a in xbox_accounts(game.xbox_package_prefix):
                entry = {'account': str(a.xuid), 'path': str(a.folder), 'exists': True,
                         'containers': 0, 'modified': None, 'extra': []}
                try:
                    live = WgsStore(long_path(a.folder)).live_entries()
                    mine = [e for e in live if game.xbox_key(e.name) is not None]
                    entry['containers'] = len(mine)
                    entry['modified'] = _filetime_iso(max((e.mtime for e in mine), default=0))
                except (WgsError, OSError):
                    pass
                t = core.Target(game, 'xbox', a)
                if t.xgs_path:
                    entry['extra'].append({'kind': 'Plain-file copy the game reads (xgs)', 'path': str(t.xgs_path).removeprefix('\\\\?\\')})
                for d in game.xbox_mirror_dirs(a):
                    entry['extra'].append({'kind': "Game's own copy", 'path': str(d)})
                xbox['saves'].append(entry)
        elif game.xbox_package_prefix:
            entry = folder_summary(game.save_dir('xbox', LocalAccount()))
            entry['account'] = 'this PC'
            xbox['saves'].append(entry)
    except (SaveError, OSError) as e:
        xbox['error'] = str(e)
    return {'id': game.id, 'name': game.name, 'steam': steam, 'xbox': xbox}


def installed_packages() -> dict:
    """Store packages (registry) plus GDK games (Xbox games folders, under '__gdk__')."""
    return {**xbox_packages(), '__gdk__': xbox_game_installs()}


def locate_all(games: list[Game]) -> list[dict]:
    packages = installed_packages()
    return [locate(g, packages) for g in games]
