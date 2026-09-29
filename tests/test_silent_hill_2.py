import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.platforms import SteamAccount
from savebridge.wgs import WgsStore
from tests.helpers import _fstr, empty_wgs

GAME = get_game('silent-hill-2')
ME = 76561198000000001


def vasb(map_name: str, body: bytes = b'x' * 100) -> bytes:
    rest = (_fstr('/Script/SHProto.SHSaveGame') + struct.pack('<I', 1) + _fstr('SavePoint')
            + bytes(16) + bytes(8) + _fstr(map_name))
    hlen = 12 + len(rest)
    return b'VASb' + struct.pack('<IH', hlen, 1) + b'\xad\xde' + rest + body


def gvas(cls: str) -> bytes:
    return b'GVAS' + bytes(20) + _fstr(cls)


class FormatTest(unittest.TestCase):
    def test_identify(self):
        s = GAME.identify(vasb('M_HotelOW_1F'), 'dl/Bliss/SaveGameData_4.sav')
        self.assertEqual(s.key, 'SaveGameData_4')
        self.assertEqual(GAME.describe(s), 'map M_HotelOW_1F')
        self.assertEqual(GAME.identify(gvas('/Script/UCA.AchievementsSaveObject'), 'x/UcaSave.sav').key, 'UcaSave')
        self.assertIsNone(GAME.identify(vasb('M_X'), 'dl/Other.sav'))
        with self.assertRaises(SaveError):
            GAME.identify(gvas('/Script/SHProto.SHSaveGame'), 'dl/SaveGameData_1.sav')

    def test_settings_and_achievement_tracker_are_optional(self):
        keys = ['SaveGameData_0', 'SaveGameData_4', 'PersistentData', 'UcaSave']
        self.assertEqual(GAME.default_keys(keys), ['SaveGameData_0', 'SaveGameData_4'])


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'KonamiDigitalEntertainmen.SILENTHILL2_x'
                             / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'SaveGameData_4': {'Data': vasb('M_Woodside_1F')},
                                  'SaveGameData_5': {'Data': vasb('M_BlueCreek')},
                                  'UcaSave': {'Data': gvas('/Script/UCA.AchievementsSaveObject')}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch('savebridge.games.unreal_files.LOCALAPPDATA', self.local),
                  mock.patch.object(core, 'steam_users', lambda: [SteamAccount(ME, 'me')]),
                  mock.patch.object(core, 'active_steam_user', lambda: None),
                  mock.patch.object(cli, 'active_steam_user', lambda: None),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox(self):
        store = WgsStore(self.wgs)
        return {e.name: store.read_blobs(e)['Data'] for e in store.live_entries()}

    def test_import_one_slot(self):
        d = self.local / 'Bliss'
        d.mkdir()
        (d / 'SaveGameData_4.sav').write_bytes(vasb('M_HotelOW_1F'))
        self.assertEqual(self.run_cli('import', 'sh2', str(d), '--to', 'xbox'), 0)
        after = self.xbox()
        self.assertEqual(after['SaveGameData_4'], vasb('M_HotelOW_1F'))
        self.assertEqual(after['SaveGameData_5'], vasb('M_BlueCreek'))
        self.assertEqual(after['UcaSave'], gvas('/Script/UCA.AchievementsSaveObject'))

    def test_xbox_to_steam_into_another_slot(self):
        rc = self.run_cli('convert', 'sh2', 'xbox-to-steam', '--only', '5', '--slot-map', '5:9')
        self.assertEqual(rc, 0)
        p = self.local / 'SilentHill2' / 'Saved' / 'SaveGames' / str(ME) / 'SaveGameData_9.sav'
        self.assertEqual(p.read_bytes(), vasb('M_BlueCreek'))


if __name__ == '__main__':
    unittest.main()
