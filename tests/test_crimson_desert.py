import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import crimson_desert as cd
from savebridge.platforms import SteamAccount
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('crimson-desert')
ME = 76561198000000001


def save_file(body: bytes, dsize: int = 1000) -> bytes:
    hdr = b'SAVE' + struct.pack('<HHIIH', 2, 0x80, 0, 2, 0) + struct.pack('<II', dsize, len(body))
    hdr += bytes(range(48))  # nonce + hmac
    return hdr.ljust(0x80, b'\0') + body


def slot(tag: bytes) -> dict[str, bytes]:
    return {'lobby': save_file(b'L' + tag * 30, 541), 'save': save_file(b'S' + tag * 300, 9_000_000)}


class FormatTest(unittest.TestCase):
    def test_check(self):
        cd.check('x', save_file(b'abc'))
        with self.assertRaises(SaveError):
            cd.check('x', save_file(b'abc')[:-1])  # truncated
        with self.assertRaises(SaveError):
            cd.check('x', b'GVAS' + b'\0' * 200)

    def test_identify_needs_a_slot_folder(self):
        s = GAME.identify(save_file(b'x'), 'dl/END GAME/slot100/save.save')
        self.assertEqual((s.key, list(s.parts)), ('slot100', ['save']))
        self.assertEqual(GAME.identify(save_file(b'x'), 'wgs/slot3/lobby').key, 'slot3')
        self.assertIsNone(GAME.identify(save_file(b'x'), 'dl/save.save'))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'PearlAbyss.CrimsonDesert_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'slot100': slot(b'a'), 'slot101': slot(b'b')})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(cd, 'LOCALAPPDATA', self.local),
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
        return {e.name: store.read_blobs(e) for e in store.live_entries()}

    def test_import_replaces_one_slot(self):
        d = self.local / 'dl' / 'slot100'
        d.mkdir(parents=True)
        for blob, data in slot(b'z').items():
            (d / f'{blob}.save').write_bytes(data)
        self.assertEqual(self.run_cli('import', 'crimson-desert', str(d.parent), '--to', 'xbox'), 0)
        after = self.xbox()
        self.assertEqual(after['slot100'], slot(b'z'))
        self.assertEqual(after['slot101'], slot(b'b'))

    def test_into_another_slot_and_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'crimson-desert', 'xbox-to-steam', '--only', 'slot101',
                                      '--slot-map', '101:2'), 0)
        d = self.local / 'Pearl Abyss' / 'CD' / 'save' / str(ME) / 'slot2'
        self.assertEqual((d / 'save.save').read_bytes(), slot(b'b')['save'])
        self.assertEqual((d / 'lobby.save').read_bytes(), slot(b'b')['lobby'])


if __name__ == '__main__':
    unittest.main()
