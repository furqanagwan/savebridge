import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('kcd2')


def whs(save_id: int, kind: str = 'ManualSave', hours: float = 1.0) -> bytes:
    desc = (f'<C_SaveGameDescription FormatVersion="0" SaveType="{kind}" SaveId="{save_id}" '
            f'SaveTime="{1740000000 + save_id}" LevelName="kutnohorsko" PlayerId="0" '
            f'UIDescription="2|{save_id}|@q||loc|0|date|{hours}|" BuildInfo="1.1.1-11377" '
            f'GameReleaseVersion="10101" GameMode="normal">\n</C_SaveGameDescription>\n').encode()
    return b'\xff\xff\xff\xff' + struct.pack('<I', len(desc)) + desc + b'\x78\x9c' + bytes([save_id % 256]) * 64


class FormatTest(unittest.TestCase):
    def test_identify_takes_playline_from_folder(self):
        s = GAME.identify(whs(5), 'dl/playline0_saves-779-1-9-6/save005.whs')
        self.assertEqual((s.key, list(s.parts)), ('playline0', ['save005.whs']))
        self.assertEqual(GAME.identify(whs(5), 'x/saves/playline3/exit.whs').key, 'playline3')
        self.assertIsNone(GAME.identify(whs(5), 'dl/readme.txt'))
        with self.assertRaises(SaveError):
            GAME.identify(b'GVAS', 'dl/save.whs')

    def test_pick_newest(self):
        s = GAME.collect([GAME.identify(whs(i), f'dl/playline0/save{i:03}.whs') for i in (3, 9, 7)]).saves['playline0']
        self.assertEqual(list(GAME.pick_files(s, 'newest').parts), ['save009.whs'])
        self.assertEqual(list(GAME.pick_files(s, 'newest:2').parts), ['save009.whs', 'save007.whs'])
        self.assertEqual(list(GAME.pick_files(s, 'save003.whs').parts), ['save003.whs'])
        with self.assertRaises(SaveError):
            GAME.pick_files(s, 'missing.whs')


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'DeepSilver.77536C3FE941_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'saves/playline0': {'exit.whs': whs(20, 'ExitSave')},
                                  'Profiles/me': {'profile.xml': b'<Profile/>'}})
        self.home = self.local / 'home'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.dict('os.environ', {'USERPROFILE': str(self.home)}),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox(self):
        store = WgsStore(self.wgs)
        return {e.name: (e, store.read_blobs(e)) for e in store.live_entries()}

    def test_newest_save_into_a_new_playline(self):
        d = self.local / 'playline0_saves-779'
        d.mkdir()
        for i in range(1, 6):
            (d / f'save{i:03}.whs').write_bytes(whs(i))
        (d / 'exit.whs').write_bytes(whs(6, 'ExitSave', 58.2))
        rc = self.run_cli('import', 'kcd2', str(d), '--to', 'xbox', '--files', 'newest', '--slot-map', '0:1')
        self.assertEqual(rc, 0)
        after = self.xbox()
        self.assertEqual(after['saves/playline1'][1], {'exit.whs': whs(6, 'ExitSave', 58.2)})
        self.assertEqual((after['saves/playline1'][0].state, after['saves/playline1'][0].reserved), (5, 1))
        self.assertEqual(after['saves/playline0'][1], {'exit.whs': whs(20, 'ExitSave')})
        self.assertEqual(after['Profiles/me'][1], {'profile.xml': b'<Profile/>'})

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'kcd2', 'xbox-to-steam'), 0)
        p = self.home / 'Saved Games' / 'kingdomcome2' / 'saves' / 'playline0' / 'exit.whs'
        self.assertEqual(p.read_bytes(), whs(20, 'ExitSave'))

    def test_files_option_rejected_for_games_without_it(self):
        s = GAME.collect([GAME.identify(whs(1), 'dl/playline0/save001.whs')]).saves['playline0']
        with self.assertRaisesRegex(SaveError, 'does not support --files'):
            get_game('samson').pick_files(s, 'newest')


if __name__ == '__main__':
    unittest.main()
