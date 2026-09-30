import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import mouse_pi as mp
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('mouse-pi')
MAGIC = 'SaveSystem.GameMetadata, Mouse'.encode('utf-16le')


def save(tag: bytes) -> bytes:
    return b'\x01\x00\xab\x01' + bytes(30) + MAGIC + tag * 40


def profile(pointer: str, boomtown: int, language: str = '0') -> bytes:
    return ('{\r\n  "a": "%s",\r\n  "b": "%s",\r\n  "c": {\r\n    "SettingLanguage": "%s"\r\n  },\r\n'
            '  "f": {\r\n    "BoomTown": %d\r\n  }\r\n}' % (pointer, pointer, language, boomtown)).encode()


class FormatTest(unittest.TestCase):
    def test_continue_pointer_edit_keeps_everything_else(self):
        mine = profile('save0', 3, language='9')
        out = mp.set_continue(mine, {'a': 'checkpoint1', 'b': 'checkpoint1'})
        self.assertEqual(mp.continue_pointer(out), {'a': 'checkpoint1', 'b': 'checkpoint1'})
        self.assertEqual(out.replace(b'checkpoint1', b'save0'), mine)

    def test_identify(self):
        self.assertEqual(GAME.identify(save(b'x'), 'dl/25/Save/save3.rsf').key, 'game')
        self.assertEqual(GAME.identify(profile('a', 1), 'dl/25/Save/profile.rsf').key, 'profile')
        self.assertEqual(GAME.identify(b'{}', 'dl/25/Local/local-profile.rsf').key, 'local')
        self.assertIsNone(GAME.identify(b'x', 'dl/25/Save/readme.txt'))
        with self.assertRaises(SaveError):
            GAME.identify(b'GVAS', 'dl/25/Save/save0.rsf')
        self.assertEqual(GAME.import_root('dl/25/Save'), 'dl/25')


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'PlaySideStudiosLTD.MOUSEP.I.ForHire_x'
                             / 'SystemAppData' / 'wgs')
        mine = profile('save0', 3, language='9')
        WgsStore(self.wgs).write({'MouseContainer': {
            'save0.rsf': save(b'mine'), 'save7.rsf': save(b'old'), 'checkpoint0.rsf': save(b'mcp'),
            'profile.rsf': mine, 'profile_backup.rsf': mine, 'local-profile.rsf': b'{"c": "mine"}'}})
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

    def container(self):
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])

    def chapter(self, root: Path) -> Path:
        (root / 'Save').mkdir(parents=True)
        (root / 'Local').mkdir()
        for n in ('save0', 'save1', 'checkpoint1'):
            (root / 'Save' / f'{n}.rsf').write_bytes(save(n.encode()))
        (root / 'Save' / 'profile.rsf').write_bytes(profile('checkpoint1', 20))
        (root / 'Local' / 'local-profile.rsf').write_bytes(b'{"c": "theirs"}')
        return root

    def test_import_replaces_saves_and_keeps_my_profile(self):
        d = self.chapter(self.local / 'dl' / '25 - 99% after final')
        self.assertEqual(self.run_cli('import', 'mouse', str(d), '--to', 'xbox'), 0)
        blobs = self.container()
        self.assertEqual(sorted(n for n in blobs if not n.startswith(('profile', 'local'))),
                         ['checkpoint1.rsf', 'save0.rsf', 'save1.rsf'])  # old save7/checkpoint0 gone
        self.assertEqual(blobs['save0.rsf'], save(b'save0'))
        for n in ('profile.rsf', 'profile_backup.rsf'):
            self.assertEqual(mp.continue_pointer(blobs[n])['a'], 'checkpoint1')
            self.assertIn(b'"BoomTown": 3', blobs[n])        # my counters
            self.assertIn(b'"SettingLanguage": "9"', blobs[n])  # my settings
        self.assertEqual(blobs['local-profile.rsf'], b'{"c": "mine"}')

    def test_whole_chapter_pack_is_refused(self):
        self.chapter(self.local / 'pack' / '24 final boss')
        self.chapter(self.local / 'pack' / '25 - 99% after final')
        before = self.container()
        self.assertEqual(self.run_cli('import', 'mouse', str(self.local / 'pack'), '--to', 'xbox'), 2)
        self.assertEqual(self.container(), before)

    def test_xbox_to_steam_uses_save_and_local_folders(self):
        self.assertEqual(self.run_cli('convert', 'mouse', 'xbox-to-steam', '--all'), 0)
        root = self.home / 'AppData' / 'LocalLow' / 'Fumi Games' / 'MOUSE'
        self.assertEqual(sorted(p.name for p in (root / 'Save').iterdir()),
                         ['checkpoint0.rsf', 'profile.rsf', 'profile_backup.rsf', 'save0.rsf', 'save7.rsf'])
        self.assertEqual((root / 'Local' / 'local-profile.rsf').read_bytes(), b'{"c": "mine"}')


if __name__ == '__main__':
    unittest.main()
