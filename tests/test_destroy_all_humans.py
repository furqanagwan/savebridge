import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import destroy_all_humans as dah
from savebridge.unreal import read_header, read_props
from tests.helpers import dah_options, dah_save

GAME = get_game('destroy-all-humans')


class IdentifyTest(unittest.TestCase):
    def test_save_and_options(self):
        s = GAME.identify(dah_save(), 'x.zip:DH/Saved/SaveGames/DevAutoSave_3.sav')
        self.assertEqual(s.key, 'DevAutoSave_3')
        self.assertIsNotNone(s.created)
        self.assertEqual(GAME.identify(dah_options([]), 'SaveOptions.sav').key, 'options')

    def test_refuses_destroy_all_humans_2(self):
        newer = dah_save().replace(b'\x04\x00\x16\x00\x03\x00', b'\x04\x00\x1b\x00\x01\x00', 1)
        with self.assertRaisesRegex(SaveError, 'Reprobed'):
            GAME.identify(newer, 'DevAutoSave_0.sav')
        with self.assertRaisesRegex(SaveError, 'worlds'):
            GAME.identify(dah_save(world='Bay_City'), 'DevAutoSave_0.sav')

    def test_ignores_other_files(self):
        self.assertIsNone(GAME.identify(b'hello', 'readme.txt'))

    def test_unknown_slot_name_is_an_error(self):
        with self.assertRaises(SaveError):
            GAME.identify(dah_save(), 'my 100% save.sav')


class MergeOptionsTest(unittest.TestCase):
    def test_keeps_settings_unions_skins_and_sets_last_used(self):
        mine = dah_options(['Skin.Crypto.Default', 'Skin.Crypto.Krampus'], res=3)
        theirs = dah_options(['Skin.Crypto.Default', 'Skin.Crypto.Cowboy'], res=0)
        out = dah.merge_options(mine, theirs, 'DevAutoSave_1')
        self.assertEqual(dah.unlock_tags(out),
                         ['Skin.Crypto.Default', 'Skin.Crypto.Krampus', 'Skin.Crypto.Cowboy'])
        props, end = read_props(out, read_header(out).body_start)
        self.assertEqual(out[props['m_iAAQuality'].value], 3)  # target setting kept
        last = out[props['m_strLastUsedSavegame'].value + 4:props['m_strLastUsedSavegame'].end - 1]
        self.assertEqual(last, b'DevAutoSave_1')
        self.assertEqual(out[end:], b'\x05\x00\x00\x00None\x00\x00\x00\x00\x00')


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.saves = self.local / 'DH' / 'Saved' / 'SaveGames'
        self.saves.mkdir(parents=True)
        (self.saves / 'DevAutoSave_0.sav').write_bytes(dah_save(world='TurnipseedFarm'))
        (self.saves / 'SaveOptions.sav').write_bytes(dah_options(['Skin.Crypto.Krampus']))
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(dah, 'LOCALAPPDATA', self.local),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def download(self, **files) -> Path:
        z = self.local / 'download.zip'
        with zipfile.ZipFile(z, 'w') as zf:
            for name, data in files.items():
                zf.writestr(f'DH/Saved/SaveGames/{name}', data)
        return z

    def test_import_keeps_existing_save_and_merges_options(self):
        z = self.download(**{'DevAutoSave_1.sav': dah_save(world='UnionTown'),
                             'SaveOptions.sav': dah_options(['Skin.Crypto.Cowboy'])})
        self.assertEqual(self.run_cli('import', 'dah', str(z), '--to', 'xbox'), 0)
        self.assertEqual((self.saves / 'DevAutoSave_1.sav').read_bytes(), dah_save(world='UnionTown'))
        self.assertTrue((self.saves / 'DevAutoSave_0.sav').is_file())
        opts = (self.saves / 'SaveOptions.sav').read_bytes()
        self.assertEqual(dah.unlock_tags(opts), ['Skin.Crypto.Krampus', 'Skin.Crypto.Cowboy'])
        self.assertIn(b'DevAutoSave_1', opts)
        self.assertEqual(len(list((self.local / 'backups').rglob('*.zip'))), 1)

    def test_import_into_another_slot(self):
        z = self.download(**{'DevAutoSave_1.sav': dah_save()})
        self.run_cli('import', 'dah', str(z), '--to', 'steam', '--slot-map', '1:4')
        self.assertTrue((self.saves / 'DevAutoSave_4.sav').is_file())
        self.assertFalse((self.saves / 'DevAutoSave_1.sav').exists())

    def test_import_refuses_reprobed_save(self):
        z = self.download(**{'DevAutoSave_0.sav': dah_save(world='Bay_City')})
        before = (self.saves / 'DevAutoSave_0.sav').read_bytes()
        self.assertEqual(self.run_cli('import', 'dah', str(z), '--to', 'xbox'), 1)
        self.assertEqual((self.saves / 'DevAutoSave_0.sav').read_bytes(), before)

    def test_convert_explains_shared_folder(self):
        before = sorted(p.name for p in self.saves.iterdir())
        self.assertEqual(self.run_cli('convert', 'dah', 'steam-to-xbox'), 0)
        self.assertEqual(sorted(p.name for p in self.saves.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
