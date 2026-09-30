import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs, gvas

GAME = get_game('beast-of-reincarnation')
CLS = '/Script/BeastOfReincarnation.AibouSaveDataContainer'


def sav(tag: bytes) -> bytes:
    return gvas(CLS, b'', engine=(5, 4, 4, 0), package=522) + tag


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'Fictions.ProjectAibou_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({n: {'Data': sav(b'mine')} for n in (
            'borSaveDataNormal_0', 'borSaveDataNormal_AutoSave_0', 'borSaveDataMeta',
            'borSaveDataMetabup0', 'borSaveDataMetabup1', 'borSaveDataConfig')})
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

    def download(self) -> Path:
        d = self.local / 'dl'
        d.mkdir()
        for n in ('borSaveDataNormal_0', 'borSaveDataNormal_1', 'borSaveDataNormal_AutoSave_0',
                  'borSaveDataMeta', 'borSaveDataMetabup0', 'borSaveDataMetabup1', 'borSaveDataConfig',
                  'borSaveDataLocalConfig'):
            (d / f'{n}.sav').write_bytes(sav(b'theirs'))
        return d

    def test_import_takes_slots_with_their_index_and_keeps_settings(self):
        self.assertEqual(self.run_cli('import', 'bor', str(self.download()), '--to', 'xbox'), 0)
        after = self.xbox()
        for n in ('borSaveDataNormal_0', 'borSaveDataNormal_1', 'borSaveDataMeta', 'borSaveDataMetabup1'):
            self.assertTrue(after[n].endswith(b'theirs'), n)
        self.assertTrue(after['borSaveDataConfig'].endswith(b'mine'))
        self.assertNotIn('borSaveDataLocalConfig', after)

    def test_slots_without_the_index_are_refused(self):
        rc = self.run_cli('import', 'bor', str(self.download()), '--to', 'xbox', '--only', 'borSaveDataNormal_1')
        self.assertEqual(rc, 2)
        self.assertNotIn('borSaveDataNormal_1', self.xbox())


if __name__ == '__main__':
    unittest.main()
