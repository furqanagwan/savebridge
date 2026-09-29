import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import get_game
from savebridge.games import black_ops_2 as bo2
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('black-ops-2')
XUID = 0x0009000001234567
STEAMID = 76561198000000009


def svg(level: str) -> bytes:
    return b'\x1b\0\0\0' + b'\0' * 28 + level.encode().ljust(32, b'\0') + b'progress' * 20


def foo(owner: int) -> bytes:
    b = bytearray(b'\x12\x34\x56\x78\0\0\0\x1b\x02\0\0\x02\xbe\xef' + b'\0' * 12272)
    struct.pack_into('<Q', b, 64, owner)
    return bytes(b)


class FormatTest(unittest.TestCase):
    def test_describe_shows_level_and_owner(self):
        s = GAME.collect([GAME.identify(svg('frontend'), 'dl/players/savegame.svg'),
                          GAME.identify(foo(STEAMID), 'dl/players/savegame.foo')]).saves['campaign']
        self.assertEqual(GAME.describe(s), f'level frontend, owner Steam {STEAMID}')

    def test_campaign_needs_both_files(self):
        r = GAME.collect([GAME.identify(svg('angola'), 'dl/players/savegame.svg')])
        self.assertNotIn('campaign', r.saves)

    def test_multiplayer_and_zombies_files_are_ignored(self):
        for name in ('bindings_mp.bdg', 'user_zm.cgp', 'hardware.chp'):
            self.assertIsNone(GAME.identify(b'x', f'dl/players/{name}'))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        sysapp = self.local / 'Packages' / '38985CA0.CallofDutyBlackOps2PCMS_x' / 'SystemAppData'
        self.wgs = empty_wgs(sysapp / 'wgs', XUID)
        mine = {'savegame.svg': svg('angola'), 'savegame.foo': foo(XUID),
                'bindings_sp.bdg': b'my bindings', 'user_sp.cgp': b'my sp', 'user_common.cgp': b'my common'}
        WgsStore(self.wgs).write({'players': mine})
        self.xgs = sysapp / 'xgs' / self.wgs.name / 'players'
        self.xgs.mkdir(parents=True)
        for n, d in mine.items():
            (self.xgs / n).write_bytes(d)
        self.steam = self.local / 'Steam' / 'steamapps' / 'common' / 'Call of Duty Black Ops II' / 'players'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(bo2, 'steam_game_dir', lambda name: self.steam.parent),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def container(self):
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])

    def download(self) -> Path:
        d = self.local / 'dl' / 'players'
        d.mkdir(parents=True)
        for n, data in {'savegame.svg': svg('frontend'), 'savegame.foo': foo(STEAMID),
                        'bindings_sp.bdg': b'their bindings', 'bindings_zm.bdg': b'zm',
                        'user_mp.cgp': b'mp', 'hardware.chp': b'hw'}.items():
            (d / n).write_bytes(data)
        return d.parent

    def test_campaign_import_keeps_settings_and_updates_xgs_copy(self):
        self.assertEqual(self.run_cli('import', 'bo2', str(self.download()), '--to', 'xbox'), 0)
        blobs = self.container()
        self.assertEqual(blobs['savegame.svg'], svg('frontend'))
        self.assertEqual(blobs['savegame.foo'], foo(STEAMID))  # copied unchanged
        self.assertEqual(blobs['bindings_sp.bdg'], b'my bindings')
        self.assertEqual(sorted(blobs), sorted(p.name for p in self.xgs.iterdir()))
        for n, d in blobs.items():
            self.assertEqual((self.xgs / n).read_bytes(), d)
        z = next((self.local / 'backups').rglob('*.zip'))
        self.assertIn('xgs/players/savegame.svg', zipfile.ZipFile(z).namelist())

    def test_reads_the_xgs_copy_the_game_uses(self):
        (self.xgs / 'savegame.svg').write_bytes(svg('karma'))  # game saved, not yet synced
        t = core.resolve(GAME, 'xbox', None, None)
        self.assertIn('karma', GAME.describe(t.read().saves['campaign']))

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'bo2', 'xbox-to-steam'), 0)
        self.assertEqual(sorted(p.name for p in self.steam.iterdir()), ['savegame.foo', 'savegame.svg'])
        self.assertEqual((self.steam / 'savegame.svg').read_bytes(), svg('angola'))


if __name__ == '__main__':
    unittest.main()
