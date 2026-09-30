"""Registry of supported games. To add one, subclass ``Game`` and list it here."""

from .base import Game, ReadResult, Save, SaveError
from .black_ops_2 import BlackOps2
from .control_resonant import ControlResonant
from .crimson_desert import CrimsonDesert
from .dawnwalker import Dawnwalker
from .destroy_all_humans import DestroyAllHumans
from .ff7_remake import Ff7Remake
from .ghosts import Ghosts
from .kcd2 import Kcd2
from .mgs_delta import MgsDelta
from .mouse_pi import MousePi
from .samson import Samson
from .silent_hill_2 import SilentHill2

GAMES: dict[str, Game] = {g.id: g for g in (MgsDelta(), DestroyAllHumans(), ControlResonant(),
                                             Samson(), Dawnwalker(), BlackOps2(), Ghosts(), Kcd2(),
                                             CrimsonDesert(), SilentHill2(), Ff7Remake(),
                                             MousePi())}

ALIASES = {
    'mgs3': 'mgs-delta',
    'mgsdelta': 'mgs-delta',
    'snake-eater': 'mgs-delta',
    'dah': 'destroy-all-humans',
    'dah1': 'destroy-all-humans',
    'control': 'control-resonant',
    'bo2': 'black-ops-2',
    'sh2': 'silent-hill-2',
    'ff7': 'ff7-remake',
    'mouse': 'mouse-pi',
}


def get_game(name: str) -> Game:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in GAMES:
        raise SaveError(f'unknown game {name!r}; supported: {", ".join(GAMES)}')
    return GAMES[key]


__all__ = ['GAMES', 'Game', 'ReadResult', 'Save', 'SaveError', 'get_game']
