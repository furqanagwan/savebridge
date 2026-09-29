"""The interface every supported game implements.

A game plugin answers these questions:

1. Where does each build keep saves, and how do its files map to logical
   saves (and back)?                                   save_dir() / read_files() / write_files()
2. If the Xbox build uses Xbox cloud saves (WGS), how do containers map to
   logical saves?                                      xbox_key() / xbox_container() /
                                                       decode_xbox() / encode_xbox()
3. Given an arbitrary file (someone else's save), what is it?   identify()
4. Optionally: how to combine an incoming save with the one already there
   (prepare), move a save to another slot (remap), and rewrite an account ID
   stored inside a save (rebind).

A logical save (``Save``) holds platform-neutral bytes: whatever per-platform
wrapping a game applies (checksums, headers, encryption) is removed on read and
re-applied on write. That is what lets one account's save be written into
another platform or another account.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..platforms import Account


class SaveError(Exception):
    pass


@dataclass
class Save:
    key: str                  # logical save id, e.g. 'slot1', 'autosave', 'profile'
    parts: dict[str, bytes]   # part name -> platform-neutral bytes (most games: one part)
    source: str = ''          # where it was read from, for display
    created: dt.datetime | None = None  # used to pick the newest copy

    def with_key(self, key: str) -> 'Save':
        return replace(self, key=key)


@dataclass
class ReadResult:
    saves: dict[str, Save] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    _ranks: dict = field(default_factory=dict, repr=False)

    def offer(self, save: Save, rank) -> None:
        """Keep the highest-ranked copy of each key."""
        if save.key not in self._ranks or rank > self._ranks[save.key]:
            self._ranks[save.key] = rank
            self.saves[save.key] = save


class Game(ABC):
    id: str = ''
    name: str = ''
    steam_app_id: int | None = None
    xbox_package_prefix: str = ''       # e.g. 'KonamiDigitalEntertainmen.RG5_'
    process_prefixes: tuple[str, ...] = ()
    xbox_uses_wgs: bool = True          # False: the Xbox build writes plain files
    steam_per_account: bool = True      # False: one save folder per PC, not per SteamID

    # ---- which saves exist -------------------------------------------------

    def key_order(self, key: str) -> tuple:
        return (key,)

    def slot_key(self, n: int) -> str:
        """Logical key for slot number ``n`` (used by --slot-map)."""
        return f'slot{n}'

    def default_keys(self, keys: list[str]) -> list[str]:
        """Saves copied when the user doesn't pick any explicitly."""
        return keys

    def describe(self, save: Save) -> str:
        return save.created.strftime('%Y-%m-%d %H:%M') if save.created else 'present'

    # ---- plain save files (Steam, and Xbox when xbox_uses_wgs is False) -----

    @abstractmethod
    def save_dir(self, platform: str, account: Account) -> Path:
        """Folder holding ``account``'s saves on ``platform`` ('steam' or 'xbox')."""

    @abstractmethod
    def read_files(self, platform: str, root: Path) -> ReadResult: ...

    @abstractmethod
    def write_files(self, platform: str, root: Path, save: Save) -> None: ...

    # ---- Xbox cloud saves (only when xbox_uses_wgs) ------------------------

    def xbox_key(self, container: str) -> str | None:
        """Logical key for a container name, or None to ignore it."""
        raise NotImplementedError

    def xbox_container(self, key: str, existing: list[str]) -> str:
        """Container name to write ``key`` into (reuse one in ``existing`` if it fits)."""
        raise NotImplementedError

    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save:
        raise NotImplementedError

    def encode_xbox(self, save: Save) -> dict[str, bytes]:
        raise NotImplementedError

    def xbox_reserved(self, key: str) -> int:
        """Value of the index entry's reserved field for new containers."""
        return 0

    # Several logical saves share one container: writing one keeps the others' blobs.
    xbox_keep_other_blobs: bool = False

    def xbox_stale_blobs(self, save: Save) -> tuple[str, ...]:
        """Blobs to delete from the container when ``save`` is written (e.g. its old checkpoint)."""
        return ()

    def xbox_mirror(self, account: Account, container: str) -> Path | None:
        """A folder where the game keeps its own copy of ``container``'s files, if any."""
        return None

    def xbox_mirror_dirs(self, account: Account) -> list[Path]:
        """All such folders, for backups."""
        return []

    def decode_xbox_all(self, container: str, blobs: dict[str, bytes]) -> list[Save]:
        """All logical saves in a container. Default: one, if xbox_key knows the container."""
        if self.xbox_key(container) is None:
            return []
        return [self.decode_xbox(container, blobs)]

    # ---- importing and combining ------------------------------------------

    @abstractmethod
    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        """Recognise a single file from either platform, or return None."""

    def collect(self, found: list[Save]) -> ReadResult:
        """Combine identified files into saves. Default: keep the newest copy of each key.

        Games whose save spans several files return one part per file from
        identify() and override this to reassemble them.
        """
        r = ReadResult()
        for s in found:
            r.offer(s, (s.created or dt.datetime.min,))
        return r

    def prepare(self, saves: list[Save], existing: dict[str, Save]) -> list[Save]:
        """Final form of ``saves`` given what the target already holds. Default: as is."""
        return saves

    def remap(self, save: Save, new_key: str) -> Save:
        """Move a save to a different logical slot."""
        raise SaveError(f'{self.name} does not support moving saves between slots')

    def rebind(self, save: Save, target: Account) -> Save:
        """Rewrite any account ID stored inside a save. Default: nothing to do."""
        return save
