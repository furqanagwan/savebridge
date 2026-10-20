"""Registry of supported games. To add one, subclass ``Game`` and list it here."""

from .base import Game, ReadResult, Save, SaveError
from .beast_of_reincarnation import BeastOfReincarnation
from .black_ops_2 import BlackOps2
from .control_resonant import ControlResonant
from .crimson_desert import CrimsonDesert
from .cuphead import Cuphead
from .darksiders_genesis import DarksidersGenesis
from .dawnwalker import Dawnwalker
from .destroy_all_humans import DestroyAllHumans
from .dispatch import Dispatch
from .ff7_remake import Ff7Rebirth, Ff7Remake
from .ghosts import Ghosts
from .halo_campaign_evolved import HaloCampaignEvolved
from .kcd2 import Kcd2
from .kh1525 import KingdomHearts1525
from .kh3 import KingdomHearts3
from .mgs_delta import MgsDelta
from .mouse_pi import MousePi
from .re_engine import Onimusha
from .samson import Samson
from .silent_hill_2 import SilentHill2
from .witcher3 import Witcher3

GAMES: dict[str, Game] = {g.id: g for g in (MgsDelta(), DestroyAllHumans(), ControlResonant(),
                                             Samson(), Dawnwalker(), BlackOps2(), Ghosts(), Kcd2(),
                                             CrimsonDesert(), SilentHill2(), Ff7Remake(),
                                             Ff7Rebirth(), MousePi(), Dispatch(),
                                             BeastOfReincarnation(), Cuphead(), Onimusha(),
                                             HaloCampaignEvolved(), Witcher3(), KingdomHearts3(),
                                             KingdomHearts1525(), DarksidersGenesis())}

ALIASES = {
    'dsg': 'darksiders-genesis',
    'genesis': 'darksiders-genesis',
    'kh1.5': 'kh1525',
    'kh2.5': 'kh1525',
    'kh1': 'kh1525',
    'kh2': 'kh1525',
    'khiii': 'kh3',
    'kingdom-hearts-3': 'kh3',
    'w3': 'witcher3',
    'witcher': 'witcher3',
    'mgs3': 'mgs-delta',
    'mgsdelta': 'mgs-delta',
    'snake-eater': 'mgs-delta',
    'dah': 'destroy-all-humans',
    'dah1': 'destroy-all-humans',
    'control': 'control-resonant',
    'bo2': 'black-ops-2',
    'sh2': 'silent-hill-2',
    'ff7': 'ff7-remake',
    'ff7r': 'ff7-rebirth',
    'rebirth': 'ff7-rebirth',
    'mouse': 'mouse-pi',
    'bor': 'beast-of-reincarnation',
    'oni': 'onimusha',
    'halo': 'halo-campaign-evolved',
    'hce': 'halo-campaign-evolved',
}


def get_game(name: str) -> Game:
    key = ALIASES.get(name.lower(), name.lower())
    if key not in GAMES:
        raise SaveError(f'unknown game {name!r}; supported: {", ".join(GAMES)}')
    return GAMES[key]


__all__ = ['GAMES', 'Game', 'ReadResult', 'Save', 'SaveError', 'get_game']
