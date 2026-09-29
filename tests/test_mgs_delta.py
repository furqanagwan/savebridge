import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import mgs_delta
from savebridge.games.mgs_delta import STEAM_VERSION, XBOX_VERSION, unwrap, wrap
from savebridge.platforms import SteamAccount
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs, mgs_payload

GAME = get_game('mgs-delta')
ME = 76561198000000001
FRIEND = 76561198000000002


class TrailerTest(unittest.TestCase):
    def test_both_versions_round_trip(self):
        payload = mgs_payload(3, filler=os.urandom(5000))
        for version in (STEAM_VERSION, XBOX_VERSION):
            data = wrap(payload, version)
            self.assertEqual(data[-1], version)
            self.assertEqual(unwrap(data), payload)

    def test_tampering_is_detected(self):
        data = bytearray(wrap(mgs_payload(3), STEAM_VERSION))
        data[100] ^= 1
        with self.assertRaises(SaveError):
            unwrap(bytes(data))
        self.assertEqual(len(unwrap(bytes(data), strict=False)), len(data) - 18)


class IdentifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            'slot4': mgs_payload(4),
            'autosave': mgs_payload(None),
            'profile': mgs_payload(None, cls='/Script/MGS3.UserProfileSaveGame'),
            'settings': mgs_payload(None, cls='/Script/Cobra.CobraCloudSaveSettings'),
        }
        for key, payload in cases.items():
            for version in (STEAM_VERSION, XBOX_VERSION):
                with self.subTest(key=key, version=version):
                    s = GAME.identify(wrap(payload, version), 'anything.bin')
                    self.assertEqual(s.key, key)

    def test_unrelated_files_are_ignored(self):
        self.assertIsNone(GAME.identify(b'not a save', 'x'))
        self.assertIsNone(GAME.identify(b'GVAS' + b'\0' * 100, 'x'))

    def test_remap_rewrites_slot_number(self):
        s = GAME.identify(wrap(mgs_payload(2), STEAM_VERSION), 'x')
        moved = GAME.remap(s, 'slot9')
        self.assertEqual(GAME.identify(wrap(moved.parts['Data'], XBOX_VERSION), 'y').key, 'slot9')
        with self.assertRaises(SaveError):
            GAME.remap(s, 'profile')


class EndToEndTest(unittest.TestCase):
    """Drive the CLI against a fake %LOCALAPPDATA% holding both builds' saves."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local = Path(self.tmp.name)
        wgs_parent = (self.local / 'Packages' / 'KonamiDigitalEntertainmen.RG5_168atcksx2mfc'
                      / 'SystemAppData' / 'wgs')
        self.xbox = empty_wgs(wgs_parent)
        self.steam = self.local / 'MGSDelta' / 'Saved' / 'SaveGames' / str(ME)
        self.steam.mkdir(parents=True)
        # slot1: _1 is newer than _0, so _1 is the current copy.
        (self.steam / 'SaveGames1_0.sav').write_bytes(wrap(mgs_payload(1, ticks=100), 2))
        (self.steam / 'SaveGames1_1.sav').write_bytes(wrap(mgs_payload(1, ticks=200), 2))
        (self.steam / 'SaveGames2_0.sav').write_bytes(wrap(mgs_payload(2), 2))
        (self.steam / 'UserProfile_0.sav').write_bytes(
            wrap(mgs_payload(None, cls='/Script/MGS3.UserProfileSaveGame'), 2))
        patches = [
            mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
            mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
            mock.patch.object(mgs_delta, 'LOCALAPPDATA', self.local),
            mock.patch.object(core, 'steam_users', lambda: [SteamAccount(ME, 'me')]),
            mock.patch.object(core, 'active_steam_user', lambda: None),
            mock.patch.object(cli, 'active_steam_user', lambda: None),
            mock.patch.object(core, 'running_processes', lambda: set()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'):
            return cli.main(list(argv))

    def xbox_saves(self):
        store = WgsStore(self.xbox)
        return {GAME.xbox_key(e.name): GAME.decode_xbox(e.name, store.read_blobs(e))
                for e in store.live_entries()}

    def test_steam_to_xbox_takes_newest_copy_and_skips_profile_by_default(self):
        self.assertEqual(self.run_cli('convert', 'mgs-delta', 'steam-to-xbox'), 0)
        saves = self.xbox_saves()
        self.assertEqual(sorted(saves), ['slot1', 'slot2'])
        self.assertEqual(saves['slot1'].parts['Data'], mgs_payload(1, ticks=200))
        names = [e.name for e in WgsStore(self.xbox).live_entries()]
        self.assertTrue(all(len(n) == len('SaveGames01') + 24 for n in names))
        self.assertEqual(len(list((self.local / 'backups').rglob('*.zip'))), 1)

    def test_round_trip_back_to_steam(self):
        self.run_cli('convert', 'mgs-delta', 'steam-to-xbox', '--all')
        for f in self.steam.iterdir():
            f.unlink()
        self.assertEqual(self.run_cli('convert', 'mgs-delta', 'xbox-to-steam', '--all'), 0)
        for n in (0, 1):
            data = (self.steam / f'SaveGames1_{n}.sav').read_bytes()
            self.assertEqual(data, wrap(mgs_payload(1, ticks=200), STEAM_VERSION))
        self.assertTrue((self.steam / 'UserProfile_0.sav').is_file())

    def test_second_convert_updates_existing_containers(self):
        self.run_cli('convert', 'mgs-delta', 'steam-to-xbox')
        self.run_cli('convert', 'mgs-delta', 'steam-to-xbox')
        self.assertEqual(len(WgsStore(self.xbox).live_entries()), 2)

    def test_import_friends_zip_into_my_xbox_with_slot_move(self):
        friend = self.local / 'download'
        (friend / str(FRIEND)).mkdir(parents=True)
        (friend / str(FRIEND) / 'SaveGames3_0.sav').write_bytes(wrap(mgs_payload(3), 2))
        (friend / 'readme.txt').write_text('my 100% save')
        z = self.local / 'friend.zip'
        with zipfile.ZipFile(z, 'w') as zf:
            for p in friend.rglob('*'):
                zf.write(p, p.relative_to(friend).as_posix())
        rc = self.run_cli('import', 'mgs-delta', str(z), '--to', 'xbox', '--slot-map', '3:7')
        self.assertEqual(rc, 0)
        saves = self.xbox_saves()
        self.assertEqual(list(saves), ['slot7'])
        self.assertEqual(GAME.identify(wrap(saves['slot7'].parts['Data'], 1), 'x').key, 'slot7')

    def test_dry_run_writes_nothing(self):
        before = (self.xbox / 'containers.index').read_bytes()
        self.run_cli('convert', 'mgs-delta', 'steam-to-xbox', '--dry-run')
        self.assertEqual((self.xbox / 'containers.index').read_bytes(), before)

    def test_refuses_while_game_running(self):
        with mock.patch.object(core, 'running_processes',
                               lambda: {'mgsdelta-wingdk-shipping.exe'}):
            with mock.patch('sys.stderr'):
                self.assertEqual(self.run_cli('convert', 'mgs-delta', 'steam-to-xbox'), 2)
        self.assertEqual(WgsStore(self.xbox).live_entries(), [])


if __name__ == '__main__':
    unittest.main()
