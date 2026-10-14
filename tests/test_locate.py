import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, locate, platforms
from savebridge.games import get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs


class InstallsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_steam_install_from_app_manifest_in_any_library(self):
        steam, lib = self.root / 'Steam', self.root / 'Library2'
        (steam / 'steamapps').mkdir(parents=True)
        (lib / 'steamapps' / 'common' / 'Cuphead').mkdir(parents=True)
        (steam / 'steamapps' / 'libraryfolders.vdf').write_text(
            '"libraryfolders" { "1" { "path" "%s" } }' % str(lib).replace('\\', '\\\\'))
        (lib / 'steamapps' / 'appmanifest_268910.acf').write_text('"AppState" { "installdir" "Cuphead" }')
        with mock.patch.object(locate, 'steam_install', lambda: steam):
            self.assertEqual(locate.steam_app_dir(268910), lib / 'steamapps' / 'common' / 'Cuphead')
            self.assertIsNone(locate.steam_app_dir(1))

    def test_gdk_games_found_through_gaming_root(self):
        drive = self.root / 'D'
        game = drive / 'Games' / 'Cuphead' / 'Content'
        game.mkdir(parents=True)
        (drive / '.GamingRoot').write_bytes(b'RGBX\x01\x00\x00\x00' + 'Games\0'.encode('utf-16-le'))
        (game / 'appxmanifest.xml').write_text(
            '<Package><Identity Name="StudioMDHR.20872A364DAA1" Version="1.0.0.0" /></Package>')
        found = locate.xbox_game_installs([drive, self.root / 'missing'])
        self.assertEqual(found, {'StudioMDHR.20872A364DAA1': str(game)})
        packages = {'__gdk__': found, 'Other.App_1.0_x64__abc': r'C:\Program Files\WindowsApps\Other'}
        hit = locate.xbox_install('StudioMDHR.20872A364DAA1_', packages)
        self.assertEqual((hit['installed'], hit['install_dir']), (True, str(game)))
        self.assertFalse(locate.xbox_install('Nope.Game_', packages)['installed'])


class LocateCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'StudioMDHR.20872A364DAA1_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'GameSaveContainer': {'cuphead_player_data_v1_slot_0': b'{}'}})
        appdata = self.local / 'Roaming'
        (appdata / 'Cuphead').mkdir(parents=True)
        (appdata / 'Cuphead' / 'cuphead_player_data_v1_slot_0.sav').write_bytes(b'{}')
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.dict('os.environ', {'APPDATA': str(appdata)}),
                  mock.patch.object(locate, 'installed_packages', lambda: {'__gdk__': {}}),
                  mock.patch.object(locate, 'steam_install', lambda: None)):
            p.start()
            self.addCleanup(p.stop)

    def test_json_reports_both_stores(self):
        with mock.patch('sys.stdout') as out:
            self.assertEqual(cli.main(['locate', 'cuphead', '--json']), 0)
        [info] = json.loads(''.join(c.args[0] for c in out.write.call_args_list))
        self.assertEqual(info['id'], 'cuphead')
        steam = info['steam']
        self.assertTrue(steam['per_pc'])
        self.assertEqual((steam['saves'][0]['exists'], steam['saves'][0]['files']), (True, 1))
        xbox = info['xbox']
        self.assertTrue(xbox['cloud_saves'])
        self.assertEqual(xbox['saves'][0]['containers'], 1)
        self.assertIsNotNone(xbox['saves'][0]['modified'])
        self.assertFalse(xbox['installed'])

    def test_every_game_locates_without_errors(self):
        for g in locate.locate_all([get_game('cuphead'), get_game('witcher3')]):
            self.assertIsNone(g['xbox']['error'])


if __name__ == '__main__':
    unittest.main()
