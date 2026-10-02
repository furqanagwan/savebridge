import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from savebridge import cli, core, diagnostics, platforms
from savebridge.games import SaveError, get_game
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs
from tests.test_halo_campaign_evolved import save_set, SOURCE, TARGET, checkpoint
from tests.test_onimusha import enc, UPLOADER


class DiagnosticsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = get_game('halo')
        self.xbox = empty_wgs(self.root / 'Packages/Microsoft.198377053870B_test/SystemAppData/wgs')
        self.download = self.root / 'private-user-76561198012345678'
        self.download.mkdir()
        for key, data in save_set(SOURCE).items():
            (self.download / (key + '.sav')).write_bytes(data)
        WgsStore(self.xbox).write({k: {'Data': b} for k, b in save_set(TARGET).items()})
        for patch in (mock.patch.object(platforms, 'LOCALAPPDATA', self.root),
                      mock.patch('savebridge.games.unreal_files.LOCALAPPDATA', self.root),
                      mock.patch.object(core, 'running_processes', return_value=set()),
                      mock.patch('savebridge.games.halo_campaign_evolved.ooz_path', return_value=self.root / 'ooz.exe'),
                      mock.patch.object(diagnostics, 'ooz_path', return_value=self.root / 'ooz.exe')):
            patch.start()
            self.addCleanup(patch.stop)
        (self.root / 'ooz.exe').write_bytes(b'present')

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def run_json(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main([*args, '--json'])
        self.assertEqual(result, 0)
        return json.loads(output.getvalue())

    def test_readiness_and_inspection_do_not_write(self):
        before = self.snapshot()
        report = self.run_json('check', 'halo', '--to', 'xbox')
        self.assertTrue(report['ready'])
        inspection = self.run_json('inspect', str(self.download))
        self.assertEqual(inspection['games'][0]['id'], self.game.id)
        self.assertEqual(len(inspection['games'][0]['saves']), 3)
        self.assertEqual(before, self.snapshot())

    def test_missing_helper_has_action_and_structured_response(self):
        (self.root / 'ooz.exe').unlink()
        report = self.run_json('check', 'halo', '--to', 'xbox')
        self.assertFalse(report['ready'])
        failure = next(c for c in report['checks'] if c['code'] == 'oodle-helper')
        self.assertEqual(failure['status'], 'fail')
        self.assertIn('build_ooz.ps1', failure['action'])

    def test_uninitialized_target_profile_is_explained(self):
        with mock.patch.object(core.Target, 'read', return_value=self.game.collect([])):
            report = self.run_json('check', 'halo', '--to', 'xbox')
        self.assertFalse(report['ready'])
        self.assertEqual(next(c for c in report['checks'] if c['code'] == 'target-profile')['status'], 'fail')

    def test_running_game_blocks_readiness_without_writes(self):
        before = self.snapshot()
        with mock.patch.object(core, 'running_processes', return_value={'halocampaignevolved.exe'}):
            report = self.run_json('check', 'halo', '--to', 'xbox')
        self.assertFalse(report['ready'])
        self.assertEqual(before, self.snapshot())

    def test_missing_source_blocks_copy_but_not_import(self):
        self.assertTrue(self.run_json('check', 'halo', '--to', 'xbox')['ready'])
        report = self.run_json('check', 'halo', '--to', 'xbox', '--from', 'steam')
        self.assertFalse(report['ready'])
        self.assertEqual(next(c for c in report['checks'] if c['code'] == 'source-saves')['status'], 'fail')

    def test_inspects_zip_and_wgs(self):
        archive = self.root / 'download.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for p in self.download.iterdir():
                z.write(p, p.name)
        for path in (archive, self.xbox):
            report = self.run_json('inspect', str(path), '--game', 'halo')
            self.assertEqual(len(report['games'][0]['saves']), 3)

    def test_shareable_report_omits_paths_ids_and_payload(self):
        report = self.run_json('inspect', str(self.download), '--game', 'halo')
        serialized = json.dumps(report) + diagnostics.inspection_text(report)
        for private in (str(self.root), self.download.name, '76561198012345678', SOURCE.hex(),
                        TARGET.hex(), 'opaque game state'):
            self.assertNotIn(private, serialized)
        self.assertIn('engine_version', serialized)

    def test_missing_companion_files_are_named(self):
        report = self.run_json('inspect', str(self.download / 'CoreSave_0.sav'), '--game', 'halo')
        self.assertEqual(report['games'][0]['required_companions'], ['Progress'])

    def test_mixed_sets_reported_without_leaking_folder_names(self):
        other = self.root / 'another-private-account'
        other.mkdir()
        (other / 'CoreSave_0.sav').write_bytes(checkpoint())
        report = self.run_json('inspect', str(self.download), str(other), '--game', 'halo')
        self.assertIn('Multiple save sets', report['games'][0]['warnings'][0])
        self.assertNotIn(other.name, json.dumps(report))

    def test_corrupt_save_report_does_not_leak_exception_text(self):
        with mock.patch.object(type(self.game), 'identify', side_effect=SaveError(str(self.download))):
            report = self.run_json('inspect', str(self.download), '--game', 'halo')
        self.assertTrue(report['problems'])
        self.assertNotIn(str(self.download), json.dumps(report))

    def test_capcom_inspection_never_remembers_recovered_ids(self):
        path = self.root / 'data001Slot.bin'
        path.write_bytes(enc(b'secret payload', UPLOADER))
        before = self.snapshot()
        with mock.patch('savebridge.dsss.find_id', return_value=UPLOADER), \
                mock.patch('savebridge.games.re_engine.remember_id') as remember:
            report = self.run_json('inspect', str(path), '--game', 'onimusha')
            remember.assert_not_called()
        self.assertEqual(report['games'][0]['id'], 'onimusha')
        self.assertEqual(before, self.snapshot())
        self.assertTrue(get_game('onimusha').remember_ids)

    def test_invalid_wgs_target_does_not_report_ready(self):
        (self.xbox / 'containers.index').write_bytes(b'corrupt')
        self.assertFalse(self.run_json('check', 'halo', '--to', 'xbox')['ready'])

    def test_unknown_files_are_reported(self):
        p = self.root / 'unknown.bin'
        p.write_bytes(b'not a save')
        report = self.run_json('inspect', str(p))
        self.assertEqual(report['unrecognized_inputs'], 1)
        self.assertEqual(report['games'], [])

    def test_inspection_limit_is_reported(self):
        files = (('private', 'unknown.bin', b'x') for _ in range(1025))
        with mock.patch.object(core, '_iter_files', return_value=files):
            report = diagnostics.inspect_saves([], self.game)
        self.assertTrue(report['limited'])
        self.assertEqual(report['inputs_examined'], 1024)
        self.assertEqual(report['input_bytes'], 1024)

    def test_failed_collection_does_not_leak_error_paths(self):
        with mock.patch.object(type(self.game), 'collect', side_effect=SaveError(str(self.download))):
            report = self.run_json('inspect', str(self.download), '--game', 'halo')
        self.assertTrue(report['games'][0]['warnings'])
        self.assertNotIn(str(self.download), json.dumps(report))

    def test_capcom_readiness_never_persists_profile_keys(self):
        game = get_game('onimusha')
        with mock.patch.object(diagnostics, 'helper_checks', return_value=[]), \
                mock.patch.object(core, 'resolve', return_value=core.Target(
                    game, 'xbox', platforms.XboxAccount(0, self.xbox))), \
                mock.patch('savebridge.dsss.find_id', return_value=UPLOADER), \
                mock.patch('savebridge.games.re_engine.remember_id') as remember:
            WgsStore(self.xbox).write({'SaveData001Slot': {'SaveData001Slot': enc(b'x', UPLOADER)}})
            before = self.snapshot()
            report = diagnostics.readiness(game, 'xbox')
            remember.assert_not_called()
        self.assertTrue(report['ready'])
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
