import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, community, core, package, platforms
from savebridge.games import Save, SaveError, get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('cuphead')
META = {'title': 'All bosses, before King Dice', 'author': 'tester', 'platform': 'steam',
        'game_version': '1.3.4', 'description': 'Every level done except the casino.'}


def slot(coins: int) -> bytes:
    return json.dumps({'levelDataManager': {'levelObjects': [{'completed': True}] * 30},
                       'coinManager': {'coins': [{}] * coins}}).encode()


def saves(*parts: bytes) -> list[Save]:
    return [Save(f'cuphead_player_data_v1_slot_{i}', {'Data': p}) for i, p in enumerate(parts)]


class PackageTest(unittest.TestCase):
    def test_round_trip_and_tamper_check(self):
        data, manifest = package.build(GAME, saves(slot(40)), META)
        self.assertEqual((manifest['game'], manifest['platform'], manifest['saves'][0]['summary']),
                         ('cuphead', 'steam', '30/30 levels, 40 coins'))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'save.zip'
            p.write_bytes(data)
            self.assertTrue(package.is_package(p))
            m, r = package.saves_of(GAME, p)
            self.assertEqual(r.saves['cuphead_player_data_v1_slot_0'].parts['Data'], slot(40))
            with self.assertRaisesRegex(SaveError, 'not witcher3'):
                package.saves_of(get_game('witcher3'), p)
            # flip one byte of a part
            bad = Path(tmp) / 'bad.zip'
            with zipfile.ZipFile(p) as zin, zipfile.ZipFile(bad, 'w') as zout:
                for i in zin.infolist():
                    b = zin.read(i)
                    zout.writestr(i, b[:-1] + bytes([b[-1] ^ 1]) if i.filename.startswith('parts/') else b)
            with self.assertRaisesRegex(SaveError, 'do not match'):
                package.read(bad)

    def test_manifest_needs_the_basics(self):
        with self.assertRaisesRegex(SaveError, 'author'):
            package.build(GAME, saves(slot(1)), {**META, 'author': ''})
        with self.assertRaisesRegex(SaveError, 'unknown platform'):
            package.build(GAME, saves(slot(1)), {**META, 'platform': 'dreamcast'})


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lib = Path(self.tmp.name) / 'saves'
        self.lib.mkdir()
        p = mock.patch.object(community, 'local_ids', lambda: {'your SteamID': [b'76561190000000001']})
        p.start()
        self.addCleanup(p.stop)

    def test_submit_check_index(self):
        folder = community.submit(GAME, saves(slot(40)), META, self.lib)
        self.assertEqual(folder.relative_to(self.lib).as_posix(),
                         'cuphead/steam/all-bosses-before-king-dice-tester')
        self.assertEqual(community.check(self.lib), {'cuphead/steam/all-bosses-before-king-dice-tester': []})
        [entry] = community.build_index(self.lib)
        self.assertEqual((entry['game_name'], entry['author'], entry['game_version']), ('Cuphead', 'tester', '1.3.4'))
        with self.assertRaisesRegex(SaveError, 'already exists'):
            community.submit(GAME, saves(slot(40)), META, self.lib)

    def test_personal_data_is_refused(self):
        with self.assertRaisesRegex(SaveError, 'your SteamID'):
            community.submit(GAME, saves(b'{"levelDataManager": 1, "owner": "76561190000000001"}'), META, self.lib)
        with self.assertRaisesRegex(SaveError, 'email'):
            community.submit(GAME, saves(b'{"levelDataManager": 1, "by": "someone@example.com"}'), META, self.lib)
        with self.assertRaisesRegex(SaveError, 'user folder'):
            community.submit(GAME, saves(b'{"levelDataManager": 1, "p": "D:/Users/alice/x"}'), META, self.lib)
        self.assertEqual(list(self.lib.iterdir()), [])

    def test_binary_steamid_shape_only_warns(self):
        data = b'{"levelDataManager": 1}' + b'\x00\x5c\x03\x96\x01\x00\x10\x01'
        folder = community.submit(GAME, saves(data), META, self.lib)
        self.assertEqual(community.check_folder(self.lib, folder), [])
        self.assertEqual(len(community.folder_warnings(folder)), 1)

    def test_check_catches_layout_and_edits(self):
        folder = community.submit(GAME, saves(slot(1)), META, self.lib)
        moved = self.lib / 'cuphead' / 'ps5' / folder.name
        moved.parent.mkdir()
        shutil.move(folder, moved)
        (moved / 'notes.txt').write_text('hi')
        problems = ' '.join(community.check_folder(self.lib, moved))
        self.assertIn('folder must be', problems)
        self.assertIn('unexpected files', problems)
        m = json.loads((moved / 'save.json').read_text())
        m['author'] = 'someone else'
        (moved / 'save.json').write_text(json.dumps(m))
        self.assertIn('differs', ' '.join(community.check_folder(self.lib, moved)))

    def test_get_from_a_local_clone(self):
        folder = community.submit(GAME, saves(slot(3)), META, self.lib)
        save_id = folder.relative_to(self.lib).as_posix()
        out = community.download(save_id, Path(self.tmp.name) / 'dl', self.lib)
        self.assertTrue(package.is_package(out))
        with self.assertRaises(SaveError):
            community.download('../../etc', Path(self.tmp.name) / 'dl', self.lib)


class ImportPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / 'StudioMDHR.20872A364DAA1_x' / 'SystemAppData' / 'wgs')
        WgsStore(self.wgs).write({'GameSaveContainer': {'cuphead_player_data_v1_slot_0': slot(0)}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def test_package_imports_like_any_save(self):
        data, _ = package.build(GAME, saves(slot(55)), META)
        zip_path = self.local / 'save.zip'
        zip_path.write_bytes(data)
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            self.assertEqual(cli.main(['import', 'cuphead', str(zip_path), '--to', 'xbox']), 0)
        store = WgsStore(self.wgs)
        blobs = store.read_blobs(store.live_entries()[0])
        self.assertEqual(blobs['cuphead_player_data_v1_slot_0'], slot(55))


if __name__ == '__main__':
    unittest.main()
