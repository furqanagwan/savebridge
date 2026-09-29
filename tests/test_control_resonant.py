import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import control_resonant as ctl
from savebridge.platforms import SteamAccount
from savebridge.wgs import NO_CLOUD_BLOB, WgsStore, guid_dir, parse_manifest
from tests.helpers import empty_wgs

GAME = get_game('control-resonant')
ME = 76561198000000001


def rmdb(payload: bytes) -> bytes:
    return b'RMDB' + struct.pack('<II', 2, 2) + struct.pack('<I', zlib.crc32(payload)) + payload


def header(ts: int, area: str = '/zone_mold/areas/x') -> bytes:
    return rmdb(struct.pack('<II', 16, ts) + area.encode())


def save_point(name: str, ts: int) -> dict[str, bytes]:
    return {f'{name}-header': header(ts), f'{name}-player': rmdb(b'p' * 52),
            f'{name}-persi-global': rmdb(name.encode() * 20), f'{name}-bundle-container': rmdb(b'b' * 40)}


def pointer(point: str) -> bytes:
    return rmdb(struct.pack('<III', 3, 0, 1) + b'\x06\x00\x00\x00slot-0'
                + struct.pack('<I', len(point) + 1) + f'{point}-'.encode() + b'\x05\0\0\0\x04\0\0\0\0')


class FormatTest(unittest.TestCase):
    def test_crc_checked_only_for_rmdb(self):
        ok = rmdb(b'hello')
        ctl.check_rmdb(ok)
        bad = ok[:-1] + b'X'
        with self.assertRaises(SaveError):
            ctl.check_rmdb(bad)
        ctl.check_rmdb(b'\x15\x00\x00\x00raw settings')  # preferences data isn't RMDB
        self.assertEqual(ctl.fix_crc(bad)[12:16], struct.pack('<I', zlib.crc32(bad[16:])))

    def test_identify_by_file_name(self):
        s = GAME.identify(rmdb(b'x'), 'dl.zip:remote/slot-0_auto-3-player')
        self.assertEqual((s.key, list(s.parts)), ('slot-0', ['auto-3-player']))
        self.assertEqual(GAME.identify(b'\x15raw', 'remote/preferences_data').key, 'preferences')
        self.assertIsNone(GAME.identify(rmdb(b'x'), 'remote/steam_autocloud.vdf'))
        self.assertIsNone(GAME.identify(b'not rmdb', 'remote/slot-0_auto-3-player'))


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.steam_root = self.local / 'Steam'
        self.remote = (self.steam_root / 'userdata' / str(ME - platforms.STEAM_ID64_BASE)
                       / '3669870' / 'remote')
        self.remote.mkdir(parents=True)
        wgs_parent = (self.local / 'Packages' / 'Remedy.CONTROLResonant_a0f1gph4eb81p'
                      / 'SystemAppData' / 'wgs')
        self.xbox = empty_wgs(wgs_parent)
        store = WgsStore(self.xbox)
        store.write({'achievements': {'data': b'ach'},
                     'preferences': {'data': b'\x15my settings', 'savegame': pointer('auto-1')},
                     'slot-0': save_point('auto-1', 1000)})
        self.pretend_synced()
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(ctl, 'steam_install', lambda: self.steam_root),
                  mock.patch.object(core, 'steam_users', lambda: [SteamAccount(ME, 'me')]),
                  mock.patch.object(core, 'active_steam_user', lambda: None),
                  mock.patch.object(cli, 'active_steam_user', lambda: None),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def pretend_synced(self):
        from savebridge.wgs import BlobRef, Index, build_manifest
        path = self.xbox / 'containers.index'
        idx = Index.parse(path.read_bytes())
        for e in idx.entries:
            e.state, e.etag = 1, f'"0x{e.name}"'
            m = self.xbox / guid_dir(e.folder) / f'container.{e.number}'
            refs = parse_manifest(m.read_bytes())
            m.write_bytes(build_manifest({n: BlobRef(r.disk, r.disk) for n, r in refs.items()}))
        path.write_bytes(idx.build())

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox_blobs(self):
        store = WgsStore(self.xbox)
        return {e.name: (e, store.read_blobs(e)) for e in store.live_entries()}

    def download(self) -> Path:
        files = {**save_point('auto-1', 2000), **save_point('key-42', 1500)}
        z = self.local / 'dl.zip'
        with zipfile.ZipFile(z, 'w') as zf:
            for n, d in files.items():
                zf.writestr(f'remote/slot-0_{n}', d)
            zf.writestr('remote/preferences_data', b'\x15their settings')
            zf.writestr('remote/preferences_savegame', pointer('key-42'))
            zf.writestr('remote/steam_autocloud.vdf', b'"steam_autocloud.vdf"{}')
        return z

    def test_import_download_into_xbox(self):
        self.assertEqual(self.run_cli('import', 'control', str(self.download()), '--to', 'xbox'), 0)
        after = self.xbox_blobs()
        e, slot = after['slot-0']
        self.assertEqual(sorted(slot), sorted({**save_point('auto-1', 0), **save_point('key-42', 0)}))
        self.assertEqual(slot['auto-1-header'], header(2000))
        self.assertEqual((e.state, e.etag), (2, '"0xslot-0"'))
        refs = parse_manifest((self.xbox / guid_dir(e.folder) / f'container.{e.number}').read_bytes())
        self.assertNotEqual(refs['auto-1-header'].cloud, NO_CLOUD_BLOB)  # replaced: keeps cloud id
        self.assertEqual(refs['key-42-header'].cloud, NO_CLOUD_BLOB)     # new: nothing in the cloud
        prefs = after['preferences'][1]
        self.assertEqual(prefs['data'], b'\x15my settings')              # settings kept
        self.assertEqual(prefs['savegame'], pointer('key-42'))          # continue pointer moved
        self.assertEqual(after['achievements'][1], {'data': b'ach'})
        self.assertEqual(after['achievements'][0].state, 1)

    def test_xbox_to_steam_replaces_the_whole_slot(self):
        (self.remote / 'slot-0_auto-9-header').write_bytes(header(5))  # stale save point
        (self.remote / 'steam_autocloud.vdf').write_bytes(b'keep me')
        self.assertEqual(self.run_cli('convert', 'control', 'xbox-to-steam'), 0)
        names = sorted(p.name for p in self.remote.iterdir())
        self.assertEqual(names, sorted(['preferences_data', 'preferences_savegame', 'steam_autocloud.vdf']
                                       + [f'slot-0_{n}' for n in save_point('auto-1', 0)]))
        self.assertEqual((self.remote / 'slot-0_auto-1-header').read_bytes(), header(1000))

    def test_round_trip(self):
        self.run_cli('convert', 'control', 'xbox-to-steam')
        steam = GAME.read_files('steam', self.remote).saves
        xbox = {k: GAME.decode_xbox(k, b) for k, (_, b) in self.xbox_blobs().items() if k != 'achievements'}
        self.assertEqual({k: s.parts for k, s in steam.items()}, {k: s.parts for k, s in xbox.items()})


if __name__ == '__main__':
    unittest.main()
