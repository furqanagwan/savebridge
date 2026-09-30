import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, dsss, platforms
from savebridge.games import SaveError, get_game
from savebridge.games.re_engine import known_ids, remember_id
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('onimusha')
UPLOADER, MINE_XBOX = 1234567, 7654321  # made-up account IDs


def enc(plain: bytes, account_id: int) -> bytes:
    return dsss.encrypt(plain, GAME.seed, dsss.parse_id(account_id, GAME.variant))


class DsssTest(unittest.TestCase):
    def test_round_trip_and_owner_check(self):
        plain = bytes(range(256)) * 300  # spans several 16 KiB slices
        data = enc(plain, UPLOADER)
        self.assertEqual(data[:4], b'DSSS')
        f = dsss.File(data)
        self.assertTrue(dsss.id_matches(f, GAME.seed, dsss.parse_id(UPLOADER, 1)))
        self.assertFalse(dsss.id_matches(f, GAME.seed, dsss.parse_id(UPLOADER + 1, 1)))
        self.assertEqual(dsss.find_id(f, GAME.seed, 1, [5, UPLOADER]), UPLOADER)
        self.assertEqual(dsss.decrypt(data, GAME.seed, dsss.parse_id(UPLOADER, 1))[0], plain)
        with self.assertRaises(dsss.DsssError):
            dsss.decrypt(data, GAME.seed, dsss.parse_id(UPLOADER + 1, 1))

    def test_signature_is_checked(self):
        data = bytearray(enc(b'x' * 100, UPLOADER))
        data[40] ^= 1
        with self.assertRaises(dsss.DsssError):
            dsss.File(bytes(data))

    def test_id_variants(self):
        self.assertEqual(dsss.parse_id(1, 0), 0x0110000100000001)
        self.assertEqual(dsss.parse_id(1, 1), 0xFFFFFFFFFFFFFFFE)
        self.assertEqual(dsss.parse_id(1, 2), 0xFEEFFFFEFFFFFFFE)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'F024294D.63383C66B8708_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'SaveData001Slot': {'SaveData001Slot': enc(b'my progress', MINE_XBOX)}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(platforms, 'steam_users', lambda: []),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)
        remember_id(MINE_XBOX)  # as if found earlier (a real run searches all 2^32 IDs)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox_blob(self) -> bytes:
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])['SaveData001Slot']

    def test_downloaded_steam_save_is_reencrypted_for_the_xbox_account(self):
        d = self.local / 'dl' / 'userdata' / str(UPLOADER) / '2638890' / 'remote' / 'win64_save'
        d.mkdir(parents=True)
        (d / 'data001Slot.bin').write_bytes(enc(b'their 100% save', UPLOADER))
        self.assertEqual(self.run_cli('import', 'onimusha', str(self.local / 'dl'), '--to', 'xbox'), 0)
        out = self.xbox_blob()
        plain, _ = dsss.decrypt(out, GAME.seed, dsss.parse_id(MINE_XBOX, 1))
        self.assertEqual(plain, b'their 100% save')
        self.assertIn(UPLOADER, known_ids())

    def test_no_existing_xbox_save_is_explained(self):
        save = GAME.identify(enc(b'x', UPLOADER), f'userdata/{UPLOADER}/a/data001Slot.bin')
        account = core.resolve_xbox(GAME, None)
        with mock.patch.object(WgsStore, 'live_entries', lambda self: []):
            with self.assertRaisesRegex(SaveError, 'existing save'):
                GAME.rebind(save, account)


if __name__ == '__main__':
    unittest.main()
