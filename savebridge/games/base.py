"""The interface every supported game implements.

A game plugin answers four questions:

1. Where does the Steam build keep an account's saves?        steam_dir()
2. How do Steam files map to logical saves (and back)?         read_steam() / write_steam()
3. How do Xbox containers map to logical saves (and back)?     xbox_key() / decode_xbox() /
                                                               encode_xbox() / xbox_container()
4. Given an arbitrary file (someone else's save), what is it?  identify()

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

from ..platforms import SteamAccount, XboxAccount


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

    # ---- which saves exist -------------------------------------------------

    def key_order(self, key: str) -> tuple:
        return (key,)

    def default_keys(self, keys: list[str]) -> list[str]:
        """Saves copied when the user doesn't pick any explicitly."""
        return keys

    def describe(self, save: Save) -> str:
        return save.created.strftime('%Y-%m-%d %H:%M') if save.created else 'present'

    # ---- Steam -------------------------------------------------------------

    @abstractmethod
    def steam_dir(self, account: SteamAccount) -> Path: ...

    @abstractmethod
    def read_steam(self, root: Path) -> ReadResult: ...

    @abstractmethod
    def write_steam(self, root: Path, save: Save) -> None: ...

    # ---- Xbox --------------------------------------------------------------

    @abstractmethod
    def xbox_key(self, container: str) -> str | None:
        """Logical key for a container name, or None to ignore it."""

    @abstractmethod
    def xbox_container(self, key: str, existing: list[str]) -> str:
        """Container name to write ``key`` into (reuse one in ``existing`` if it fits)."""

    @abstractmethod
    def decode_xbox(self, container: str, blobs: dict[str, bytes]) -> Save: ...

    @abstractmethod
    def encode_xbox(self, save: Save) -> dict[str, bytes]: ...

    def xbox_reserved(self, key: str) -> int:
        """Value of the index entry's reserved field for new containers."""
        return 0

    # ---- importing foreign files ------------------------------------------

    @abstractmethod
    def identify(self, data: bytes, name: str, strict: bool = True) -> Save | None:
        """Recognise a single file from either platform, or return None."""

    def remap(self, save: Save, new_key: str) -> Save:
        """Move a save to a different logical slot."""
        raise SaveError(f'{self.name} does not support moving saves between slots')

    def rebind(self, save: Save, target: SteamAccount | XboxAccount) -> Save:
        """Rewrite any account ID stored inside a save. Default: nothing to do."""
        return save
