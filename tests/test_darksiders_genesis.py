import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import darksiders_genesis as dsg
from tests.helpers import gvas, prop, str_prop

GAME = get_game('darksiders-genesis')


def save(hours: int, level: int) -> bytes:
    props = (str_prop('CheckpointWorld', f'/Game/Maps/Levels/Level_{level:02d}/Level_{level:02d}')
             + prop('PlayTimeHours', 'IntProperty', struct.pack('<i', hours))
             + prop('PlayTimeMinutes', 'IntProperty', struct.pack('<i', 5)))
    return gvas(dsg.SAVE_CLASS, props, engine=(4, 22, 2, 0))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.folder = self.local / 'THQ Nordic' / 'Darksiders Genesis' / 'Saved' / 'SaveGames' / 'user'
        self.folder.mkdir(parents=True)
        (self.folder / 'SaveSlot_0.sav').write_bytes(save(0, 1))
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(dsg, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def test_describe(self):
        s = GAME.identify(save(40, 17), 'dl/Saved/SaveGames/user/SaveSlot_0.sav')
        self.assertEqual(GAME.describe(s), 'profile 1: 40h 05m played, level 17')

    def test_download_into_another_profile_keeps_yours_and_the_backup_in_step(self):
        d = self.local / 'dl' / 'Final Boss' / 'Saved' / 'SaveGames' / 'user'
        d.mkdir(parents=True)
        (d / 'SaveSlot_0.sav').write_bytes(save(40, 17))
        (d / 'SaveSlot_0.sav.bak').write_bytes(save(39, 16))
        self.assertEqual(self.run_cli('import', 'dsg', str(d), '--to', 'xbox', '--slot-map', '0:1'), 0)
        self.assertEqual((self.folder / 'SaveSlot_0.sav').read_bytes(), save(0, 1))
        self.assertEqual((self.folder / 'SaveSlot_1.sav').read_bytes(), save(40, 17))
        self.assertEqual((self.folder / 'SaveSlot_1.sav.bak').read_bytes(), save(40, 17))

    def test_other_games_and_profiles_are_refused(self):
        with self.assertRaisesRegex(SaveError, 'not a Darksiders Genesis save'):
            GAME.identify(gvas('/Script/Other.SaveGame', b''), 'SaveSlot_0.sav')
        with self.assertRaisesRegex(SaveError, 'three profiles'):
            GAME.remap(GAME.identify(save(1, 1), 'SaveSlot_0.sav'), 'slot5')


if __name__ == '__main__':
    unittest.main()
