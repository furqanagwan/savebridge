import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import ghosts
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('ghosts')
XUID = 0x0009000001234567


def svg(level: str) -> bytes:
    return b'\x47\0\0\0' + b'\x11' * 28 + level.encode().ljust(32, b'\0') + b'state' * 50


class FormatTest(unittest.TestCase):
    def test_identify(self):
        self.assertEqual(GAME.identify(svg('skyway'), 'dl/players2/savegame.svg').key, 'campaign')
        self.assertIsNone(GAME.identify(svg('x'), 'dl/players2/save/internal/snd_restart.svg'))
        with self.assertRaises(SaveError):
            GAME.identify(b'\x1b\0\0\0' + b'\0' * 60, 'dl/players2/savegame.svg')  # a BO2 save


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / '38985CA0.CallofDutyGhostsPCMS_x'
                             / 'SystemAppData' / 'wgs', XUID)
        mine = {'savegame.svg': svg('deer_hunt'), 'save\\internal/snd_restart.svg': svg('deer_hunt'),
                'settings_c.zip.iw6': b'SEMVc', 'settings_s.zip.iw6': b'SEMVs'}
        WgsStore(self.wgs).write({'Gamerprofile_gdk': mine})
        self.content = self.local / 'XboxGames' / 'Call of Duty Ghosts' / 'Content'
        self.mirror = self.content / 'players2' / str(XUID)
        self.mirror.mkdir(parents=True)
        for n in ('savegame.svg', 'settings_c.zip.iw6', 'settings_s.zip.iw6'):
            (self.mirror / n).write_bytes(mine[n])
        (self.content / 'players2' / 'config.cfg').write_text('seta r_mode "3840x2160"')
        self.steam = self.local / 'Steam' / 'steamapps' / 'common' / 'Call of Duty Ghosts'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(ghosts, 'xbox_game_content', lambda name: self.content),
                  mock.patch.object(ghosts, 'steam_game_dir', lambda name: self.steam),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def container(self):
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])

    def test_import_replaces_save_drops_old_restart_and_updates_game_copy(self):
        d = self.local / 'dl' / 'Call of Duty - Ghosts' / 'players2'
        d.mkdir(parents=True)
        (d / 'savegame.svg').write_bytes(svg('skyway'))
        self.assertEqual(self.run_cli('import', 'ghosts', str(d.parent.parent), '--to', 'xbox'), 0)
        blobs = self.container()
        self.assertEqual(sorted(blobs), ['savegame.svg', 'settings_c.zip.iw6', 'settings_s.zip.iw6'])
        self.assertEqual(blobs['savegame.svg'], svg('skyway'))
        self.assertEqual((self.mirror / 'savegame.svg').read_bytes(), svg('skyway'))
        self.assertEqual((self.mirror / 'settings_c.zip.iw6').read_bytes(), b'SEMVc')
        self.assertTrue((self.content / 'players2' / 'config.cfg').is_file())  # untouched
        names = zipfile.ZipFile(next((self.local / 'backups').rglob('*.zip'))).namelist()
        self.assertIn('mirror0/savegame.svg', names)

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'ghosts', 'xbox-to-steam'), 0)
        self.assertEqual((self.steam / 'players2' / 'savegame.svg').read_bytes(), svg('deer_hunt'))


if __name__ == '__main__':
    unittest.main()
