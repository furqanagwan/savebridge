import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs


def slot(coins: int) -> bytes:
    return json.dumps({'levelDataManager': {'levelObjects': []},
                       'coinManager': {'coins': [{}] * coins}}).encode()


class RestoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'StudioMDHR.20872A364DAA1_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'GameSaveContainer': {'cuphead_player_data_v1_slot_0': slot(3)}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv) -> tuple[int, str]:
        with mock.patch('sys.stdout') as out, mock.patch('sys.stderr'):
            rc = cli.main(list(argv))
        return rc, ''.join(c.args[0] for c in out.write.call_args_list)

    def slot0(self) -> bytes:
        store = WgsStore(self.wgs)
        return store.read_blobs(store.live_entries()[0])['cuphead_player_data_v1_slot_0']

    def test_restore_undoes_an_import_and_can_itself_be_undone(self):
        d = self.local / 'dl'
        d.mkdir()
        (d / 'cuphead_player_data_v1_slot_0.sav').write_bytes(slot(40))
        self.assertEqual(self.run_cli('import', 'cuphead', str(d), '--to', 'xbox')[0], 0)
        self.assertEqual(self.slot0(), slot(40))

        rc, text = self.run_cli('backups', 'cuphead', '--json')
        listed = json.loads(text)
        self.assertEqual((rc, len(listed), listed[0]['platform']), (0, 1, 'xbox'))

        self.assertEqual(self.run_cli('restore', 'cuphead')[0], 0)
        self.assertEqual(self.slot0(), slot(3))
        self.assertEqual(len(core.backups('cuphead')), 2)  # the restore backed up first

        newest_first = core.backups('cuphead')
        self.assertEqual(self.run_cli('restore', 'cuphead', newest_first[0].path.name)[0], 0)
        self.assertEqual(self.slot0(), slot(40))

    def test_unknown_backup_name(self):
        self.run_cli('import', 'cuphead', str(self.local), '--to', 'xbox', '--dry-run')
        rc, _ = self.run_cli('restore', 'cuphead', 'nope.zip')
        self.assertEqual(rc, 2)


if __name__ == '__main__':
    unittest.main()
