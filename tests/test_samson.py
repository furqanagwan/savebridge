import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.unreal import find_scalar_ue5, read_header
from savebridge.wgs import WgsStore
from tests.helpers import _fstr, empty_wgs

GAME = get_game('samson')


def ue5_prop(name: str, typ: str, fmt: str, value) -> bytes:
    raw = struct.pack(fmt, value)
    return _fstr(name) + _fstr(typ) + struct.pack('<ii', 0, len(raw)) + b'\0' + raw


def ue5_save(cls: str, day: int = 3, debt: float = 100.0) -> bytes:
    """A UE 5.7-shaped GVAS file (save-game version 3, UE5 package version)."""
    return (b'GVAS' + struct.pack('<iii', 3, 522, 1018) + struct.pack('<HHHI', 5, 7, 4, 1)
            + _fstr('++p1+devstable') + struct.pack('<ii', 3, 0) + _fstr(cls) + b'\0'
            + ue5_prop('GameDay', 'IntProperty', '<i', day)
            + ue5_prop('CurrentDebt', 'FloatProperty', '<f', debt)
            + _fstr('None') + b'\0\0\0\0')


SAVE = '/Script/CJ.CJSaveGameV2'
MANIFEST = '/Script/CJ.CJSaveGameManifestV1'
SETTINGS = '/Script/CJLyraBase.LyraSettingsShared'


def save_set(day: int) -> dict[str, bytes]:
    return {'SaveGame': ue5_save(SAVE, day), 'SaveGame_Checkpoint_StartOfDay': ue5_save(SAVE, day),
            'SaveGameManifest': ue5_save(MANIFEST, day)}


class Ue5Test(unittest.TestCase):
    def test_header_and_scalars(self):
        b = ue5_save(SAVE, day=19, debt=5561.0)
        h = read_header(b)
        self.assertEqual((h.engine[:2], h.save_class), ((5, 7), SAVE))
        self.assertEqual(find_scalar_ue5(b, 'GameDay'), 19)
        self.assertEqual(find_scalar_ue5(b, 'CurrentDebt'), 5561.0)
        self.assertIsNone(find_scalar_ue5(b, 'Missing'))

    def test_identify_by_name_and_class(self):
        self.assertEqual(GAME.identify(ue5_save(SAVE), 'x/SaveGame.sav').key, 'SaveGame')
        self.assertEqual(GAME.identify(ue5_save(SAVE), 'wgs/SaveGame/Data').key, 'SaveGame')
        self.assertIsNone(GAME.identify(ue5_save(SAVE), 'x/Other.sav'))
        with self.assertRaises(SaveError):
            GAME.identify(ue5_save(SETTINGS), 'x/SaveGame.sav')  # wrong class for the name


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.xbox = empty_wgs(self.local / 'Packages' / '29692LiquidSwords.CriminalJustice_29hft9r1nn9mt'
                              / 'SystemAppData' / 'wgs')
        WgsStore(self.xbox).write({**{k: {'Data': v} for k, v in save_set(2).items()},
                                   'SharedGameSettings': {'Data': ue5_save(SETTINGS)}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch('savebridge.games.unreal_files.LOCALAPPDATA', self.local),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def download(self, name: str, day: int, settings: bool = False) -> Path:
        d = self.local / 'dl' / name / 'Samson' / 'Saved' / 'SaveGames'
        d.mkdir(parents=True)
        for k, v in save_set(day).items():
            (d / f'{k}.sav').write_bytes(v)
        if settings:
            (d / 'SharedGameSettings.sav').write_bytes(ue5_save(SETTINGS, 99))
        return d

    def xbox_saves(self):
        store = WgsStore(self.xbox)
        return {e.name: store.read_blobs(e)['Data'] for e in store.live_entries()}

    def test_refuses_download_with_two_save_sets(self):
        self.download('Everything Unlocked', 24)
        self.download('Last Payment', 19)
        before = self.xbox_saves()
        self.assertEqual(self.run_cli('import', 'samson', str(self.local / 'dl'), '--to', 'xbox'), 2)
        self.assertEqual(self.xbox_saves(), before)

    def test_imports_one_set_and_keeps_settings(self):
        d = self.download('Everything Unlocked', 24, settings=True)
        self.assertEqual(self.run_cli('import', 'samson', str(d.parents[2]), '--to', 'xbox'), 0)
        after = self.xbox_saves()
        self.assertEqual(find_scalar_ue5(after['SaveGame'], 'GameDay'), 24)
        self.assertEqual(find_scalar_ue5(after['SaveGameManifest'], 'GameDay'), 24)
        self.assertEqual(find_scalar_ue5(after['SharedGameSettings'], 'GameDay'), 3)  # untouched

    def test_save_group_must_travel_together(self):
        d = self.download('x', 24)
        rc = self.run_cli('import', 'samson', str(d), '--to', 'xbox', '--only', 'SaveGame')
        self.assertEqual(rc, 2)
        self.assertEqual(find_scalar_ue5(self.xbox_saves()['SaveGame'], 'GameDay'), 2)

    def test_import_a_raw_xbox_save_folder_into_steam(self):
        self.assertEqual(self.run_cli('import', 'samson', str(self.xbox), '--to', 'steam'), 0)
        steam = self.local / 'Samson' / 'Saved' / 'SaveGames'
        self.assertEqual(sorted(p.name for p in steam.iterdir()),
                         ['SaveGame.sav', 'SaveGameManifest.sav', 'SaveGame_Checkpoint_StartOfDay.sav'])

    def test_xbox_to_steam_and_back(self):
        self.assertEqual(self.run_cli('convert', 'samson', 'xbox-to-steam'), 0)
        steam = self.local / 'Samson' / 'Saved' / 'SaveGames'
        self.assertEqual((steam / 'SaveGame.sav').read_bytes(), save_set(2)['SaveGame'])
        (steam / 'SaveGame.sav').write_bytes(ue5_save(SAVE, 7))
        (steam / 'SaveGame_Checkpoint_StartOfDay.sav').write_bytes(ue5_save(SAVE, 7))
        (steam / 'SaveGameManifest.sav').write_bytes(ue5_save(MANIFEST, 7))
        self.assertEqual(self.run_cli('convert', 'samson', 'steam-to-xbox'), 0)
        self.assertEqual(find_scalar_ue5(self.xbox_saves()['SaveGame'], 'GameDay'), 7)


if __name__ == '__main__':
    unittest.main()
