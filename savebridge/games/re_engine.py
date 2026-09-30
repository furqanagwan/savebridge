"""Capcom RE Engine games: DSSS-encrypted saves tied to an account ID.

    Steam  Steam/userdata/<account id>/<app id>/remote/win64_save/data<X>.bin
    Xbox   container SaveData<X>, one blob SaveData<X>
           (X is e.g. 001Slot: data001Slot.bin <-> SaveData001Slot)

Both stores use the same DSSS format (see ``savebridge.dsss``); only the
account ID the file is encrypted with differs. On Steam that is the SteamID's
32-bit account ID. On Xbox it is a Steam-style 32-bit number Capcom assigns to
the Xbox account, unrelated to the XUID, so it is recovered from one of the
account's existing saves (a 2^32 search, a few seconds with the native helper)
and remembered in %LOCALAPPDATA%/savebridge/dsss-ids.json.

Saves are stored decrypted in ``Save.parts['Data']``; ``rebind`` picks the
receiving account's ID and writing encrypts for it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from pathlib import Path

from .. import dsss, platforms
from ..platforms import STEAM_ID64_BASE, Account, SteamAccount, XboxAccount, long_path, steam_install
from ..wgs import WgsError, WgsStore
from .base import Game, ReadResult, Save, SaveError

STEAM_FILE = re.compile(r'data(\w+?)\.bin', re.I)
XBOX_NAME = re.compile(r'SaveData(\w+)')


def _id_cache() -> Path:
    return platforms.LOCALAPPDATA / 'savebridge' / 'dsss-ids.json'


def known_ids() -> list[int]:
    try:
        return [int(x) for x in json.loads(_id_cache().read_text())['ids']]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def remember_id(account_id: int) -> None:
    ids = known_ids()
    if account_id in ids:
        return
    p = _id_cache()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'ids': ids + [account_id]}))


class ReEngineGame(Game):
    seed: int = 0
    variant: int = 1
    flavor: int = dsss.FLAVOR_PLAIN

    # ---- keys ---------------------------------------------------------------

    def key_order(self, key: str) -> tuple:
        m = re.match(r'(-?\d+)', key)
        return (int(m.group(1)) if m else 1 << 30, key)

    def slot_key(self, n: int) -> str:
        return f'{n:03d}Slot'

    def describe(self, save: Save) -> str:
        return f'{len(save.parts["Data"]) / 1e6:.1f} MB'

    # ---- account IDs ----------------------------------------------------------

    def _decrypt(self, data: bytes, name: str, hints=()) -> bytes:
        """Plaintext of a DSSS file, finding which account wrote it."""
        try:
            f = dsss.File(data)
            cands = [*hints, *known_ids(), *(a.steamid64 - STEAM_ID64_BASE for a in platforms.steam_users())]
            account_id = dsss.find_id(f, self.seed, self.variant, cands)
        except dsss.DsssError as e:
            raise SaveError(f'{name}: {e}') from None
        if account_id is None:
            raise SaveError(f'{name}: no account ID decrypts this save (not a {self.name} save?)')
        remember_id(account_id)
        return dsss.decrypt(data, self.seed, dsss.parse_id(account_id, self.variant))[0]

    def _xbox_id(self, account: XboxAccount) -> int:
        """The Capcom ID of an Xbox account, from one of its existing saves of this game."""
        try:
            store = WgsStore(long_path(account.folder))
            for e in store.live_entries():
                if self.xbox_key(e.name) is None:
                    continue
                data = store.read_blobs(e).get(e.name)
                if data:
                    f = dsss.File(data)
                    found = dsss.find_id(f, self.seed, self.variant, known_ids())
                    if found is not None:
                        remember_id(found)
                        return found
        except (WgsError, OSError, dsss.DsssError) as ex:
            raise SaveError(f'could not read the Xbox saves to find the account key: {ex}') from None
        raise SaveError(f'{self.name} saves are locked to an account key that only an existing '
                        f'save reveals. Start the Xbox version, save once, close it, then try again.')

    def rebind(self, save: Save, target: Account) -> Save:
        if isinstance(target, SteamAccount):
            account_id = target.steamid64 - STEAM_ID64_BASE
        elif isinstance(target, XboxAccount):
            account_id = self._xbox_id(target)
        else:
            raise SaveError(f'{self.name} saves need a Steam or Xbox account')
        return replace(save, bind=dsss.parse_id(account_id, self.variant))

    def _encrypt(self, save: Save) -> bytes:
        if save.bind is None:
            raise SaveError(f'{save.key}: no target account to encrypt for')
        return dsss.encrypt(save.parts['Data'], self.seed, save.bind, self.flavor)

    # ---- Steam --------------------------------------------------------------

    def save_dir(self, platform: str, account: Account) -> Path:
        steam = steam_install()
        if steam is None or not isinstance(account, SteamAccount):
            raise SaveError('Steam is not installed')
        return steam / 'userdata' / str(account.steamid64 - STEAM_ID64_BASE) / \
            str(self.steam_app_id) / 'remote' / 'win64_save'

    def read_files(self, platform: str, root: Path) -> ReadResult:
        r = ReadResult()
        owner = root.parts[-4] if len(root.parts) >= 4 and root.parts[-4].isdigit() else None
        for p in sorted(root.iterdir()):
            m = STEAM_FILE.fullmatch(p.name)
            if not m or not p.is_file():
                continue
            try:
                plain = self._decrypt(p.read_bytes(), p.name, [int(owner)] if owner else [])
            except SaveError as e:
                r.warnings.append(str(e))
                continue
            r.saves[m.group(1)] = Save(m.group(1), {'Data': plain}, p.name)
        return r

    def write_files(self, platform: str, root: Path, save: Save) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = root / f'data{save.key}.bin'
        tmp = p.with_name(p.name + '.savebridge-tmp')
        tmp.write_bytes(self._encrypt(save))
        os.replace(tmp, p)

    # ---- Xbox -----------------------------------------------------------------

    def xbox_key(self, container: str) -> str | None:
        m = XBOX_NAME.fullmatch(container)
        return m.group(1) if m else None

    def xbox_container(self, key: str, existing: list[str]) -> str:
        return f'SaveData{key}'

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        if container not in blobs:
            raise SaveError(f'{container}: blob {container} missing')
        key = self.xbox_key(container)
        return Save(key, {'Data': self._decrypt(blobs[container], container)}, container)

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        name = self.xbox_container(save.key, [])
        return {name: self._encrypt(save)}

    # ---- importing --------------------------------------------------------------

    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        path = name.replace('\\', '/')
        folder, _, filename = path.rpartition('/')
        m = STEAM_FILE.fullmatch(filename)
        key = m.group(1) if m else self.xbox_key(filename)
        if key is None or data[:4] != dsss.MAGIC:
            return None
        # A Steam folder path names its owner: .../userdata/<account id>/<app>/remote/...
        hints = [int(x) for x in re.findall(r'(?:^|/)(\d{4,10})(?=/)', path) if int(x) < 1 << 32]
        return Save(key, {'Data': self._decrypt(data, filename, hints)}, folder)

    def remap(self, save: Save, new_key: str) -> Save:
        return save.with_key(new_key)


class Onimusha(ReEngineGame):
    id = 'onimusha'
    name = 'Onimusha: Way of the Sword'
    verified = ('steam-to-xbox',)
    note = "loaded in game from the first conversion; savebridge's code matches it byte for byte"
    steam_app_id = 2638890
    xbox_package_prefix = 'F024294D.63383C66B8708_'
    process_prefixes = ('onimusha',)
    seed = 0xA235A0818E21A7A6
    variant = 1
