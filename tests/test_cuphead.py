import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('cuphead')


def slot(levels_done: int, coins: int) -> bytes:
    return json.dumps({
        'isPlayer1Mugman': False,
        'levelDataManager': {'levelObjects': [{'completed': i < levels_done} for i in range(10)]},
        'coinManager': {'coins': [{'id': i} for i in range(coins)]},
    }).encode()


class FormatTest(unittest.TestCase):
    def test_identify_and_describe(self):
        s = GAME.identify(slot(4, 7), 'dl/Cuphead/cuphead_player_data_v1_slot_0.sav')
        self.assertEqual((s.key, GAME.describe(s)), ('cuphead_player_data_v1_slot_0', '4/10 levels, 7 coins'))
        self.assertIsNone(GAME.identify(b'x', 'dl/Cuphead/steam_autocloud.vdf'))
        with self.assertRaises(SaveError):
            GAME.identify(b'not json', 'dl/cuphead_player_data_v1_slot_1.sav')


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'StudioMDHR.20872A364DAA1_x' / 'SystemAppData' / 'wgs')
        self.mine = {'cuphead_player_data_v1_slot_0': slot(0, 3), 'cuphead_player_data_v1_slot_1': slot(0, 0),
                     'cuphead_settings_data_v1': b'{"hasBootedUpGame": true}',
                     'r2|0|1|0|controller': b'<?xml version="1.0"?><JoystickMap/>'}
        WgsStore(self.wgs).write({'GameSaveContainer': self.mine})
        self.appdata = self.local / 'Roaming'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.dict('os.environ', {'APPDATA': str(self.appdata)}),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def container(self):
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])

    def test_download_slot_into_a_free_xbox_slot_keeps_everything_else(self):
        d = self.local / 'dl' / 'Cuphead'
        d.mkdir(parents=True)
        (d / 'cuphead_player_data_v1_slot_0.sav').write_bytes(slot(47, 56))
        (d / 'steam_autocloud.vdf').write_bytes(b'"steam_autocloud.vdf"{}')
        rc = self.run_cli('import', 'cuphead', str(d), '--to', 'xbox', '--only', '0', '--slot-map', '0:1')
        self.assertEqual(rc, 0)
        after = self.container()
        self.assertEqual(after['cuphead_player_data_v1_slot_1'], slot(47, 56))
        for k in ('cuphead_player_data_v1_slot_0', 'cuphead_settings_data_v1', 'r2|0|1|0|controller'):
            self.assertEqual(after[k], self.mine[k])

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'cuphead', 'xbox-to-steam'), 0)
        self.assertEqual(sorted(p.name for p in (self.appdata / 'Cuphead').iterdir()),
                         ['cuphead_player_data_v1_slot_0.sav', 'cuphead_player_data_v1_slot_1.sav'])


if __name__ == '__main__':
    unittest.main()
