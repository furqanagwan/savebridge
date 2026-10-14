"""The community save library: saves/<game>/<platform>/<save>/ in this repository.

Each save is a folder with the package (save.zip, see ``savebridge.package``)
and a copy of its manifest (save.json) for reviewers. ``saves/index.json``
lists them all and is what the app and ``savebridge community list`` read,
locally from a clone or from GitHub.

Submissions arrive as pull requests; ``check`` runs on every one (format,
hashes, size, and a scan for personal data), and ``index`` rebuilds the index
when they are merged.
"""

from __future__ import annotations

import json
import os
import re
import struct
import urllib.error
import urllib.request
from pathlib import Path

from . import package
from .games import GAMES, Game, Save, SaveError

MAX_ZIP = 50 * 1024 * 1024        # GitHub refuses files over 100 MB; keep well clear
RAW = 'https://raw.githubusercontent.com/furqanagwan/savebridge/main/saves/'
INDEX = 'index.json'


def repo_library() -> Path | None:
    p = Path(__file__).resolve().parents[1] / 'saves'
    return p if p.is_dir() else None


def slug(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', text.lower().replace('+', ' plus ')).strip('-')
    return s[:60].strip('-') or 'save'


# ---- personal data ---------------------------------------------------------------

STEAM64_HIGH = b'\x01\x00\x10\x01'   # little-endian high dword of a SteamID64
# (A binary XUID's high dword, 00 00 09 00, is too common in ordinary data to scan
# for blindly; the exact XUIDs on the submitter's PC are checked at submit time.)
GENERIC = [
    ('a SteamID', re.compile(rb'7656119\d{10}')),
    ('an Xbox user ID', re.compile(rb'2533274\d{9}')),
    ('a Windows user folder', re.compile(rb'[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\x00]{2,}', re.I)),
    ('a Windows user folder', re.compile('[A-Za-z]:\\\\Users\\\\'.encode('utf-16-le'), re.I)),
    ('an email address', re.compile(rb'[A-Za-z0-9._%+-]{2,}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
]


def possible_binary_ids(saves: list[Save]) -> list[str]:
    """Little-endian SteamID64-shaped values. Ordinary binary data produces these by
    coincidence, so they are warnings for a reviewer, never a reason to refuse."""
    out = []
    for s in saves:
        for part, data in s.parts.items():
            i = data.find(STEAM64_HIGH, 4)
            while i >= 0:
                if struct.unpack_from('<I', data, i - 4)[0] > 0xFFFF:
                    out.append(f'{s.key}/{part}: a value shaped like a SteamID (often a coincidence)')
                    break
                i = data.find(STEAM64_HIGH, i + 1)
    return out


def local_ids() -> dict[str, list[bytes]]:
    """This PC's account IDs and user name, in the encodings saves tend to use."""
    from .platforms import STEAM_ID64_BASE, steam_users, xbox_accounts
    out: dict[str, list[bytes]] = {}
    for a in steam_users():
        acct = a.steamid64 - STEAM_ID64_BASE
        out.setdefault('your SteamID', []).extend(
            [str(a.steamid64).encode(), struct.pack('<Q', a.steamid64), str(acct).encode()])
    try:
        for a in xbox_accounts(''):
            out.setdefault('your Xbox user ID', []).extend(
                [str(a.xuid).encode(), f'{a.xuid:016X}'.encode(), struct.pack('<Q', a.xuid)])
    except OSError:
        pass
    user = os.environ.get('USERNAME', '')
    if len(user) >= 4:
        out.setdefault('your Windows user name', []).extend([user.encode(), user.encode('utf-16-le')])
    return out


def privacy_findings(saves: list[Save], personal: dict[str, list[bytes]] | None = None) -> list[str]:
    """Personal data in the saves' bytes: readable IDs, user folders, emails, and
    (given ``personal``) this PC's own IDs in any encoding. Described, never echoed."""
    findings = []
    for s in saves:
        for part, data in s.parts.items():
            kinds = {label for label, rx in GENERIC if rx.search(data)}
            for label, needles in (personal or {}).items():
                if any(n and n in data for n in needles):
                    kinds.add(label)
            findings += [f'{s.key}/{part}: contains {k}' for k in sorted(kinds)]
    return findings


# ---- submitting --------------------------------------------------------------------

def submit(game: Game, saves: list[Save], meta: dict, library: Path,
           allow_personal: bool = False) -> Path:
    """Write a new save folder into the library; returns it. Warnings: possible_binary_ids()."""
    if not allow_personal:
        problems = privacy_findings(saves, local_ids())
        if problems:
            raise SaveError('the save seems to contain personal data, so it was not packaged:\n  '
                            + '\n  '.join(problems))
    data, manifest = package.build(game, saves, meta)
    if len(data) > MAX_ZIP:
        raise SaveError(f'the package is {len(data) / 1e6:.0f} MB; the library takes up to '
                        f'{MAX_ZIP / 1e6:.0f} MB (pick fewer saves with --only)')
    folder = library / game.id / manifest['platform'] / slug(f'{manifest["title"]}-{manifest["author"]}')
    if folder.exists():
        raise SaveError(f'{folder} already exists; choose another title')
    folder.mkdir(parents=True)
    (folder / 'save.zip').write_bytes(data)
    (folder / package.MANIFEST).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
                                           encoding='utf-8')
    return folder


# ---- checking and indexing (CI) ------------------------------------------------------

def save_folders(library: Path) -> list[Path]:
    return sorted(p.parent for p in library.glob(f'*/*/*/{package.MANIFEST}'))


def check_folder(library: Path, folder: Path) -> list[str]:
    rel = folder.relative_to(library).parts
    problems = []
    try:
        outer = json.loads((folder / package.MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        return [f'save.json unreadable ({e})']
    zip_path = folder / 'save.zip'
    if not zip_path.is_file():
        return ['save.zip missing']
    if zip_path.stat().st_size > MAX_ZIP:
        problems.append(f'save.zip is over {MAX_ZIP // 2**20} MB')
    try:
        inner, files = package.read(zip_path)
    except SaveError as e:
        return problems + [str(e)]
    if inner != outer:
        problems.append('save.json differs from the one inside save.zip')
    problems += package.validate(inner)
    if inner.get('game') not in GAMES:
        problems.append(f'unknown game {inner.get("game")!r}')
    if len(rel) != 3 or rel[0] != inner.get('game') or rel[1] != inner.get('platform'):
        problems.append('folder must be saves/<game>/<platform>/<name>/ matching save.json')
    extra = set(os.listdir(folder)) - {'save.zip', package.MANIFEST}
    if extra:
        problems.append(f'unexpected files: {", ".join(sorted(extra))}')
    saves = [Save(s['key'], {p: files[i['file']] for p, i in s['parts'].items()}) for s in inner['saves']]
    problems += privacy_findings(saves)
    return problems


def folder_warnings(folder: Path) -> list[str]:
    """Things a reviewer should look at that don't fail the check."""
    try:
        manifest, files = package.read(folder / 'save.zip')
    except SaveError:
        return []
    return possible_binary_ids([Save(s['key'], {p: files[i['file']] for p, i in s['parts'].items()})
                                for s in manifest['saves']])


def check(library: Path) -> dict[str, list[str]]:
    return {str(f.relative_to(library)).replace('\\', '/'): check_folder(library, f) for f in save_folders(library)}


def build_index(library: Path) -> list[dict]:
    entries = []
    for folder in save_folders(library):
        m = json.loads((folder / package.MANIFEST).read_text(encoding='utf-8'))
        game = GAMES.get(m['game'])
        entries.append({
            'id': str(folder.relative_to(library)).replace('\\', '/'),
            'game': m['game'], 'game_name': game.name if game else m['game'],
            'title': m['title'], 'description': m.get('description', ''), 'author': m['author'],
            'platform': m['platform'], 'platform_name': package.PLATFORMS.get(m['platform'], m['platform']),
            'game_version': m['game_version'], 'tested': m.get('tested', []),
            'saves': [{'key': s['key'], 'summary': s.get('summary', '')} for s in m['saves']],
            'size': (folder / 'save.zip').stat().st_size, 'created': m.get('created'),
        })
    return sorted(entries, key=lambda e: (e['game_name'].lower(), e['platform'], e['title'].lower()))


def write_index(library: Path) -> Path:
    p = library / INDEX
    p.write_text(json.dumps(build_index(library), indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    return p


# ---- browsing and downloading ------------------------------------------------------

def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'savebridge'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def load_index(library: Path | None = None) -> list[dict]:
    """The library index: from a local clone when there is one, otherwise from GitHub."""
    if library is not None:
        return build_index(library)
    try:
        return json.loads(_get(RAW + INDEX))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # no saves published yet
        raise SaveError(f'could not load the community library ({e})') from None
    except Exception as e:  # noqa: BLE001 - network errors come in many types
        raise SaveError(f'could not load the community library ({e})') from None


def download(save_id: str, dest_root: Path, library: Path | None = None) -> Path:
    """Fetch one save's package; returns the local save.zip."""
    if not re.fullmatch(r'[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+', save_id):
        raise SaveError(f'not a community save id: {save_id}')
    dest = dest_root / save_id.replace('/', os.sep) / 'save.zip'
    dest.parent.mkdir(parents=True, exist_ok=True)
    if library is not None and (library / save_id / 'save.zip').is_file():
        dest.write_bytes((library / save_id / 'save.zip').read_bytes())
    else:
        try:
            dest.write_bytes(_get(RAW + save_id + '/save.zip'))
        except Exception as e:  # noqa: BLE001
            raise SaveError(f'could not download {save_id} ({e})') from None
    package.read(dest)  # verify hashes before anyone imports it
    return dest
