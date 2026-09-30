import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs, gvas

GAME = get_game('dispatch')
SAVE = '/Script/AdHocSaveGame.AdHocSaveGameV2'
INDEX = '/Script/AdHocSaveGame.AdHocSaveIndexV2'
SETTINGS = '/Script/Dispatch.DispatchCloudSettings'


def save(cls: str, tag: bytes) -> bytes:
    """A UE 4.27 GVAS file of the given class, followed by a marker to tell copies apart."""
    return gvas(cls, b'', engine=(4, 27, 2, 0), package=522) + tag


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'AdHocStudio.DispatchSeason1_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({n: {'Data': save(c, b'mine')} for n, c in (
            ('SaveSlot0', SAVE), ('SaveSlot0_BACKUP', SAVE), ('Index', INDEX), ('Index_BACKUP', INDEX),
            ('CloudSettings', SETTINGS))})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch('savebridge.games.unreal_files.LOCALAPPDATA', self.local),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox(self):
        store = WgsStore(self.wgs)
        return {e.name: store.read_blobs(e)['Data'] for e in store.live_entries()}

    def test_import_takes_save_and_index_keeps_settings_ignores_local_only(self):
        d = self.local / 'DispatchSave' / 'SaveGames'
        (d / 'LocalOnly' / '76561198000000009').mkdir(parents=True)
        for n, c in (('SaveSlot0', SAVE), ('SaveSlot0_BACKUP', SAVE), ('Index', INDEX),
                     ('Index_BACKUP', INDEX), ('CloudSettings', SETTINGS)):
            (d / f'{n}.sav').write_bytes(save(c, b'theirs'))
        (d / 'LocalOnly' / '76561198000000009' / 'SaveSlot0.bak').write_bytes(save(SAVE, b'bak'))
        self.assertEqual(self.run_cli('import', 'dispatch', str(d.parent), '--to', 'xbox'), 0)
        after = self.xbox()
        for n in ('SaveSlot0', 'SaveSlot0_BACKUP', 'Index', 'Index_BACKUP'):
            self.assertIn(b'theirs', after[n])
        self.assertIn(b'mine', after['CloudSettings'])
        self.assertEqual(len(after), 5)

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'dispatch', 'xbox-to-steam'), 0)
        steam = self.local / 'Dispatch' / 'Saved' / 'SaveGames'
        self.assertEqual(sorted(p.name for p in steam.iterdir()),
                         ['Index.sav', 'Index_BACKUP.sav', 'SaveSlot0.sav', 'SaveSlot0_BACKUP.sav'])


if __name__ == '__main__':
    unittest.main()
