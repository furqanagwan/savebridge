import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import Save, SaveError, get_game
from savebridge.games.halo_campaign_evolved import (
    CORE_CLASS, MAPPING_TAG, PROGRESS_CLASS, decode_checkpoint,
    encode_checkpoint, player_mapping,
)
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs
from tests.test_samson import ue5_save

GAME = get_game('halo')
SOURCE = bytes.fromhex('123456789abcdef0')
TARGET = bytes.fromhex('fedcba9876543210')


def checkpoint(mapping=SOURCE, copies=7):
    raw = (ue5_save(CORE_CLASS) + MAPPING_TAG + mapping
           + b'\x00opaque game state\x00' + (b'player:' + mapping) * (copies - 1)
           + bytes(150000))
    return encode_checkpoint(raw)


def save_set(mapping):
    return {'CoreSave_0': checkpoint(mapping), 'CoreSave_1': checkpoint(mapping),
            'Progress': ue5_save(PROGRESS_CLASS)}


class FormatTest(unittest.TestCase):
    def test_multiple_chunks_round_trip(self):
        packed = checkpoint()
        raw = decode_checkpoint(packed)
        self.assertEqual(player_mapping(raw), SOURCE)
        self.assertEqual(raw.count(SOURCE), 7)
        self.assertEqual(encode_checkpoint(raw), packed)

    def test_rejects_corrupt_archive_before_native_decoder(self):
        packed = checkpoint()
        for data in (packed[:40], packed[:-1], packed + b'junk',
                     packed[:12] + struct.pack('<I', 0xffffffff) + packed[16:]):
            with self.subTest(size=len(data)), self.assertRaises(SaveError):
                decode_checkpoint(data)

    def test_rejects_bad_chunk_sizes(self):
        packed = bytearray(checkpoint())
        struct.pack_into('<Q', packed, 57, 1)
        with self.assertRaises(SaveError):
            decode_checkpoint(bytes(packed))

    def test_validates_name_and_class(self):
        self.assertEqual(GAME.identify(checkpoint(), 'CoreSave_0.sav').key, 'CoreSave_0')
        self.assertEqual(GAME.identify(checkpoint(), 'CoreSave_1/Data').key, 'CoreSave_1')
        self.assertIsNone(GAME.identify(checkpoint(), 'Other.sav'))
        with self.assertRaises(SaveError):
            GAME.identify(ue5_save(CORE_CLASS), 'Progress.sav')

    def test_unknown_mapping_layout_is_refused(self):
        saves = [Save('CoreSave_0', {'Data': checkpoint(copies=8)}),
                 Save('Progress', {'Data': ue5_save(PROGRESS_CLASS)})]
        with self.assertRaises(SaveError):
            GAME.prepare(saves, {'CoreSave_0': Save('CoreSave_0', {'Data': checkpoint(TARGET)})})


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.local = Path(tmp.name)
        self.xbox = empty_wgs(self.local / 'Packages' / 'Microsoft.198377053870B_8wekyb3d8bbwe'
                              / 'SystemAppData' / 'wgs')
        WgsStore(self.xbox).write({k: {'Data': v} for k, v in save_set(TARGET).items()})
        for patch in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                      mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                      mock.patch('savebridge.games.unreal_files.LOCALAPPDATA', self.local),
                      mock.patch.object(core, 'running_processes', lambda: set())):
            patch.start()
            self.addCleanup(patch.stop)
        self.download = self.local / 'download'
        self.download.mkdir()
        for k, data in save_set(SOURCE).items():
            (self.download / (k + '.sav')).write_bytes(data)

    def run_cli(self, *args):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(args))

    def test_import_rebinds_all_copies_and_preserves_other_bytes(self):
        self.assertEqual(self.run_cli('import', 'halo', str(self.download), '--to', 'xbox'), 0)
        after = core.Target(GAME, 'xbox', platforms.XboxAccount(0, self.xbox)).read().saves
        for k in ('CoreSave_0', 'CoreSave_1'):
            raw = decode_checkpoint(after[k].parts['Data'])
            self.assertEqual(raw, decode_checkpoint(checkpoint()).replace(SOURCE, TARGET))
        self.assertEqual(after['Progress'].parts['Data'], ue5_save(PROGRESS_CLASS))
        self.assertTrue(list((self.local / 'backups').rglob('*.zip')))

    def test_dry_run_leaves_store_unchanged(self):
        before = {p.relative_to(self.xbox): p.read_bytes() for p in self.xbox.rglob('*') if p.is_file()}
        self.assertEqual(self.run_cli('import', 'halo', str(self.download), '--to', 'xbox', '--dry-run'), 0)
        self.assertEqual(before, {p.relative_to(self.xbox): p.read_bytes()
                                 for p in self.xbox.rglob('*') if p.is_file()})

    def test_missing_progress_is_refused(self):
        self.assertEqual(self.run_cli('import', 'halo', str(self.download), '--to', 'xbox',
                                      '--only', 'CoreSave_0'), 2)

    def test_target_without_checkpoint_is_refused(self):
        existing = {'Progress': Save('Progress', {'Data': ue5_save(PROGRESS_CLASS)})}
        prepared = GAME.prepare([Save(k, {'Data': v}) for k, v in save_set(SOURCE).items()], existing)
        with self.assertRaises(SaveError):
            GAME.rebind(prepared[0], platforms.XboxAccount(0, self.xbox))

    def test_conflicting_target_ids_are_refused(self):
        existing = {k: Save(k, {'Data': checkpoint(v)})
                    for k, v in [('CoreSave_0', SOURCE), ('CoreSave_1', TARGET)]}
        with self.assertRaises(SaveError):
            GAME.prepare([Save(k, {'Data': v}) for k, v in save_set(SOURCE).items()], existing)

    def test_xbox_to_steam_and_back(self):
        self.assertEqual(self.run_cli('convert', 'halo', 'xbox-to-steam'), 0)
        steam = self.local / 'Meteorite/Saved/SaveGames'
        for k, data in save_set(SOURCE).items():
            (steam / (k + '.sav')).write_bytes(data)
        self.assertEqual(self.run_cli('convert', 'halo', 'steam-to-xbox'), 0)
        saves = core.Target(GAME, 'xbox', platforms.XboxAccount(0, self.xbox)).read().saves
        self.assertEqual(player_mapping(decode_checkpoint(saves['CoreSave_0'].parts['Data'])), TARGET)


if __name__ == '__main__':
    unittest.main()
