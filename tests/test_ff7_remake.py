import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import ff7_remake as ff7
from savebridge.platforms import SteamAccount
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('ff7-remake')
ME = 76561198000000001


def raw_save(tag: bytes) -> bytes:
    return (b'\0\0\x01\0\x10\0\x05\0' + bytes(8) + b'RESD' * 4 + tag * 50).ljust(4096, b'\0')


class FormatTest(unittest.TestCase):
    def test_wrap_round_trip(self):
        raw = raw_save(b'x')
        wrapped = ff7.wrap(raw)
        self.assertEqual(wrapped[:4], b'bilz')
        self.assertEqual(struct.unpack_from('<II', wrapped, 4), (len(wrapped) - 20, len(raw)))
        self.assertEqual(ff7.unwrap(wrapped), raw)

    def test_unwrap_accepts_other_compressors(self):
        raw = raw_save(b'y')
        z = zlib.compress(raw, 1)  # the game's deflate output differs from ours
        other = b'bilz' + struct.pack('<II', len(z), len(raw)) + bytes(8) + z
        self.assertEqual(ff7.unwrap(other), raw)

    def test_rejects_damaged_files(self):
        wrapped = ff7.wrap(raw_save(b'z'))
        with self.assertRaises(SaveError):
            ff7.unwrap(wrapped[:-1])
        with self.assertRaises(SaveError):
            ff7.to_raw('ff7remake001', b'GVAS' + bytes(100))

    def test_identify_either_platform(self):
        raw = raw_save(b'a')
        self.assertEqual(GAME.identify(raw, 'dl/FF7/ff7remake007.sav').parts['Data'], raw)
        self.assertEqual(GAME.identify(ff7.wrap(raw), 'wgs/ff7remake003/Data').parts['Data'], raw)
        self.assertIsNone(GAME.identify(raw, 'dl/FF7R/ff7rebirth001.sav'))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / '39EA002F.EXED1_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'ff7remake000': {'Data': ff7.wrap(raw_save(b'm'))}})
        self.docs = self.local / 'Documents'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(ff7, 'documents_dir', lambda: self.docs),
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

    def test_steam_download_is_compressed_into_new_xbox_slots(self):
        d = self.local / 'FF7'
        d.mkdir()
        (d / 'ff7remake007.sav').write_bytes(raw_save(b'q'))
        (d / 'ff7remakeplus010.sav').write_bytes(raw_save(b'p'))
        self.assertEqual(self.run_cli('import', 'ff7', str(d), '--to', 'xbox'), 0)
        after = self.xbox()
        self.assertEqual(ff7.unwrap(after['ff7remake007']), raw_save(b'q'))
        self.assertEqual(ff7.unwrap(after['ff7remakeplus010']), raw_save(b'p'))
        self.assertEqual(ff7.unwrap(after['ff7remake000']), raw_save(b'm'))

    def test_xbox_to_steam_decompresses(self):
        self.assertEqual(self.run_cli('convert', 'ff7', 'xbox-to-steam'), 0)
        p = self.docs / 'My Games' / 'FINAL FANTASY VII REMAKE' / 'Steam' / str(ME) / 'ff7remake000.sav'
        self.assertEqual(p.read_bytes(), raw_save(b'm'))

    def test_slots_only_move_within_their_kind(self):
        s = GAME.identify(raw_save(b'a'), 'dl/ff7remakeplus010.sav')
        self.assertEqual(GAME.remap(s, 'ff7remakeplus003').key, 'ff7remakeplus003')
        with self.assertRaises(SaveError):
            GAME.remap(s, 'ff7remake003')


if __name__ == '__main__':
    unittest.main()
