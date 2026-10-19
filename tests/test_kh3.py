import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import kh3
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('kh3')
UPLOADER = '76561197960265851'   # made-up SteamID64s (account numbers 123 and 456)
MINE = 76561197960266184


def plain(level: int, playtime: int = 3600, size: int = 0x200) -> bytes:
    body = bytearray(size)
    body[0x2C - 16] = level
    struct.pack_into('<III', body, 0x20 - 16, playtime, 0, 500)
    struct.pack_into('<q', body, 0x58 - 16, 638000000000000000)
    head = bytearray(b'S@vE' + struct.pack('<IHHI', size, 5, 2, 0))
    struct.pack_into('<I', head, 12, zlib.crc32(body))
    return bytes(head + body)


class FormatTest(unittest.TestCase):
    def test_key_derivation_matches_the_published_example(self):
        # thirteenth-order/kh3-save-editor documents the zero-block ciphertext for this ID
        from savebridge import aes
        block = aes.ecb(kh3.key_for('76561190000000000'), b'\0' * 16)
        self.assertEqual(block.hex(), '21a096684e79fdd3097df481c91600d8')

    def test_wrap_unwrap_and_account_binding(self):
        p = plain(40)
        wrapped = kh3.encrypt(p, UPLOADER)
        self.assertEqual((len(wrapped) - 17) % 16, 0)
        self.assertEqual(wrapped[-17], 8)
        self.assertEqual(kh3.decrypt(wrapped, UPLOADER), p)
        self.assertIsNone(kh3.decrypt(wrapped, str(MINE)))
        with self.assertRaisesRegex(SaveError, 'checksum'):
            kh3.check_plain(p[:-1] + b'\x01', 'x')

    def test_identify_uses_the_folder_name_or_epic(self):
        s = GAME.identify(kh3.encrypt(plain(12), UPLOADER), f'dl/Steam/{UPLOADER}/SaveGames/kh3sv2/data/KHIII_slot2.bin')
        self.assertEqual((s.key, GAME.describe(s).split(',')[0]), ('slot2', 'Lv 12'))
        s = GAME.identify(kh3.encrypt(plain(5), kh3.EPIC_ACCOUNT), 'dl/kh3sv2/data/KHIII_slot0.bin')
        self.assertEqual(s.key, 'slot0')
        with mock.patch.object(platforms, 'steam_users', lambda: []):
            with self.assertRaisesRegex(SaveError, 'cannot identify'):
                GAME.identify(kh3.encrypt(plain(5), UPLOADER), 'dl/kh3sv2/data/KHIII_slot0.bin')


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.docs = self.local / 'Documents'
        self.wgs = empty_wgs(self.local / 'Packages' / '39EA002F.KH3REMIND_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'kh3sv2/data': {'_ph_': b'\0', 'slot0.bin': plain(1), 'system.bin': plain(0, size=0x80)},
                                  'kh3setting/data': {'GameSettings.dat': b'settings'}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(platforms, 'steam_users', lambda: [platforms.SteamAccount(MINE)]),
                  mock.patch.object(kh3, 'documents_dir', lambda: self.docs),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox(self) -> dict[str, dict[str, bytes]]:
        store = WgsStore(self.wgs)
        return {e.name: store.read_blobs(e) for e in store.live_entries()}

    def test_download_into_xbox_keeps_your_slot_and_settings(self):
        d = self.local / 'dl' / 'SaveGames' / 'kh3sv2' / 'data'
        d.mkdir(parents=True)
        (d / 'KHIII_slot0.bin').write_bytes(kh3.encrypt(plain(99), kh3.EPIC_ACCOUNT))
        (d / 'KHIII_slot2.bin').write_bytes(kh3.encrypt(plain(32), kh3.EPIC_ACCOUNT))
        (d / 'KHIII_system.bin').write_bytes(kh3.encrypt(plain(7, size=0x80), kh3.EPIC_ACCOUNT))
        self.assertEqual(self.run_cli('import', 'kh3', str(self.local / 'dl'), '--to', 'xbox', '--slot-map', '0:4'), 0)
        after = self.xbox()
        data = after['kh3sv2/data']
        self.assertEqual((data['slot0.bin'], data['slot4.bin'], data['slot2.bin']), (plain(1), plain(99), plain(32)))
        self.assertEqual(data['system.bin'], plain(0, size=0x80))   # system only with --all
        self.assertEqual(data['_ph_'], b'\0')
        self.assertEqual(after['kh3setting/data'], {'GameSettings.dat': b'settings'})

    def test_xbox_to_steam_encrypts_for_your_account(self):
        self.assertEqual(self.run_cli('convert', 'kh3', 'xbox-to-steam', '--steam-account', str(MINE)), 0)
        f = (self.docs / 'My Games' / 'KINGDOM HEARTS III' / 'Steam' / str(MINE) / 'SaveGames' / 'kh3sv2'
             / 'data' / 'KHIII_slot0.bin')
        self.assertEqual(kh3.decrypt(f.read_bytes(), str(MINE)), plain(1))


if __name__ == '__main__':
    unittest.main()
