"""Registry of supported games. To add one, subclass ``Game`` and list it here."""

from .base import Game, ReadResult, Save, SaveError
from .black_ops_2 import BlackOps2
from .control_resonant import ControlResonant
from .dawnwalker import Dawnwalker
from .destroy_all_humans import DestroyAllHumans
from .ghosts import Ghosts
from .mgs_delta import MgsDelta
from .samson import Samson

GAMES: dict[str, Game] = {g.id: g for g in (MgsDelta(), DestroyAllHumans(), ControlResonant(),
                                             Samson(), Dawnwalker(), BlackOps2(), Ghosts())}

ALIASES = {
    'mgs3': 'mgs-delta',
    'mgsdelta': 'mgs-delta',
    'snake-eater': 'mgs-delta',
    'dah': 'destroy-all-humans',
    'dah1': 'destroy-all-humans',
    'control': 'control-resonant',
    'bo2': 'black-ops-2',
}


def get_game(name: str) -> Game:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in GAMES:
        raise SaveError(f'unknown game {name!r}; supported: {", ".join(GAMES)}')
    return GAMES[key]


__all__ = ['GAMES', 'Game', 'ReadResult', 'Save', 'SaveError', 'get_game']
