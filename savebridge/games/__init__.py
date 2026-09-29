"""Registry of supported games. To add one, subclass ``Game`` and list it here."""

from .base import Game, ReadResult, Save, SaveError
from .mgs_delta import MgsDelta

GAMES: dict[str, Game] = {g.id: g for g in (MgsDelta(),)}

ALIASES = {
    'mgs3': 'mgs-delta',
    'mgsdelta': 'mgs-delta',
    'snake-eater': 'mgs-delta',
}


def get_game(name: str) -> Game:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in GAMES:
        raise SaveError(f'unknown game {name!r}; supported: {", ".join(GAMES)}')
    return GAMES[key]


__all__ = ['GAMES', 'Game', 'ReadResult', 'Save', 'SaveError', 'get_game']
