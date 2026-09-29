import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import dawnwalker as dw
from savebridge.wgs import NO_CLOUD_BLOB, WgsStore, guid_dir, parse_manifest
from tests.helpers import empty_wgs

GAME = get_game('dawnwalker')


def meta(name: str, day: int = 13, kind: str = 'Manual') -> bytes:
    fields = [('Day', day), ('Quest', 'ABC'), ('PlayTime', 69837), ('SaveName', name),
              ('Date', '2026.09.10-18.50.20'), ('Type', dw.TYPES[kind]),
              ('BuildVersion', 256181), ('SaveVersion', 134), ('TypeString', kind)]
    body = ',\r\n'.join(f'\t\t"{k}": {json.dumps(v)}' for k, v in fields)
    return ('{\r\n\t"Meta":\r\n\t{\r\n' + body + '\r\n\t}\r\n}').encode()


def save_files(name: str, day: int = 13, kind: str = 'Manual') -> dict[str, bytes]:
    return {'.sav': b'DSAV$\0\0\0' + name.encode() * 10 + b'VASD', '.meta': meta(name, day, kind),
            '.png': b'\x89PNG\r\n\x1a\n' + name.encode()}


class MetaTest(unittest.TestCase):
    def test_remap_rewrites_only_slot_fields_and_keeps_formatting(self):
        s = GAME.collect([GAME.identify(d, f'dl/Autosave2{ext}')
                          for ext, d in save_files('Autosave2', kind='Auto').items()]).saves['Autosave2']
        moved = GAME.remap(s, 'ManualSave31')
        m = json.loads(moved.parts['Meta'])['Meta']
        self.assertEqual((m['SaveName'], m['Type'], m['TypeString'], m['Day']),
                         ('ManualSave31', 0, 'Manual', 13))
        self.assertIn(b'\r\n\t\t"SaveName": "ManualSave31"', moved.parts['Meta'])
        self.assertEqual(moved.parts['Data'], s.parts['Data'])
        with self.assertRaises(SaveError):
            GAME.remap(s, 'Autosave9')

    def test_a_save_needs_sav_and_meta(self):
        r = GAME.collect([GAME.identify(save_files('ManualSave1')['.sav'], 'dl/ManualSave1.sav')])
        self.assertEqual(r.saves, {})
        self.assertTrue(r.warnings)

    def test_meta_must_name_its_slot(self):
        files = save_files('ManualSave1')
        r = GAME.collect([GAME.identify(files['.sav'], 'dl/ManualSave2.sav'),
                          GAME.identify(files['.meta'], 'dl/ManualSave2.meta')])
        self.assertEqual(r.saves, {})


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.xbox = empty_wgs(self.local / 'Packages' / 'NAMCOBANDAIGamesInc.TheBloodofDawnwalker_x'
                              / 'SystemAppData' / 'wgs')
        mine = save_files('ManualSave18', day=16)
        WgsStore(self.xbox).write({
            'ManualSave18': {'Data': mine['.sav'], 'Meta': mine['.meta'], 'SaveIcon': mine['.png']},
            'RebelSettings': {'Data': b'settings'}})
        self.steam = self.local / 'Dawnwalker' / 'Saved' / 'SaveGames'
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(dw, 'LOCALAPPDATA', self.local),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def download(self) -> Path:
        d = self.local / 'dl'
        d.mkdir()
        for ext, data in save_files('ManualSave18').items():
            (d / f'ManualSave18{ext}').write_bytes(data)
        return d

    def test_import_into_a_free_slot_leaves_existing_saves_alone(self):
        before = {e.name: WgsStore(self.xbox).read_blobs(e) for e in WgsStore(self.xbox).live_entries()}
        rc = self.run_cli('import', 'dawnwalker', str(self.download()), '--to', 'xbox',
                          '--slot-map', '18:31')
        self.assertEqual(rc, 0)
        store = WgsStore(self.xbox)
        entries = {e.name: e for e in store.live_entries()}
        for name, blobs in before.items():
            self.assertEqual(store.read_blobs(entries[name]), blobs)
        new = entries['ManualSave31']
        self.assertEqual((new.state, new.reserved), (5, 1))
        blobs = store.read_blobs(new)
        self.assertEqual(blobs['Data'], save_files('ManualSave18')['.sav'])
        self.assertEqual(json.loads(blobs['Meta'])['Meta']['SaveName'], 'ManualSave31')
        refs = parse_manifest((self.xbox / guid_dir(new.folder) / f'container.{new.number}').read_bytes())
        self.assertTrue(all(r.cloud == NO_CLOUD_BLOB for r in refs.values()))

    def test_import_without_slot_map_replaces_same_slot(self):
        self.run_cli('import', 'dawnwalker', str(self.download()), '--to', 'xbox')
        store = WgsStore(self.xbox)
        e = next(e for e in store.live_entries() if e.name == 'ManualSave18')
        self.assertEqual(json.loads(store.read_blobs(e)['Meta'])['Meta']['Day'], 13)

    def test_xbox_to_steam_writes_three_files_and_skips_settings(self):
        self.assertEqual(self.run_cli('convert', 'dawnwalker', 'xbox-to-steam'), 0)
        self.assertEqual(sorted(p.name for p in self.steam.iterdir()),
                         ['ManualSave18.meta', 'ManualSave18.png', 'ManualSave18.sav'])
        self.assertEqual((self.steam / 'ManualSave18.meta').read_bytes(), meta('ManualSave18', day=16))

    def test_import_a_raw_xbox_save_folder(self):
        self.assertEqual(self.run_cli('import', 'dawnwalker', str(self.xbox), '--to', 'steam'), 0)
        self.assertTrue((self.steam / 'ManualSave18.sav').is_file())


if __name__ == '__main__':
    unittest.main()
