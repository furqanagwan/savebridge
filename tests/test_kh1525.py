import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from savebridge import cli, core, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import kh1525 as k
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('kh1525')
T = k.TITLES['recom']   # the smallest archive


def archive(t: k.Title, names: list[str], stamp: int = 1630000000) -> bytes:
    table, slots = bytearray(t.table), bytearray(t.entries * t.stride)
    for i, name in enumerate(names):
        length = 0x400 if name.endswith('SYS') else t.save_size
        e = name.encode().ljust(0x40, b'\0') + struct.pack('<iiiiii', stamp, 0, stamp, 0, length, 0)
        table[i * k.ENTRY:i * k.ENTRY + len(e)] = e
        slots[i * t.stride:i * t.stride + 8] = bytes([i + 1]) * 8
    return bytes(table + slots) + b'\0' * 16 * 46   # zero tail like the real archives


def png(sq: bytes) -> bytes:
    def chunk(kind, data):
        return struct.pack('>I4s', len(data), kind) + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', b'\0' * 13) + chunk(b'tEXt', b'Author\0test')
            + chunk(b'sqEX', sq) + chunk(b'IDAT', b'img') + chunk(b'IEND', b''))


def steam_file(t: k.Title, a: bytes, key: bytes = bytes(range(16)), hide_entry0: bool = True) -> bytes:
    """The Steam layout, built independently: XORed table head, optionally the hidden entry 0."""
    table = bytearray(a[:t.table])
    if hide_entry0:
        for i in list(range(18)) + list(range(0x40, 0x4C)):
            table[i] ^= k.STEAM_ENTRY0_KEY[i & 15]
        struct.pack_into('<i', table, 0x50, 0)
    table[k.KEY_AT:k.KEY_AT + 16] = bytes(16)
    for i in range(k.OBFUSCATED):
        table[i] ^= key[i & 15]
    return png(k.STEAM_HEADER + bytes(table) + a[t.table:len(a) - 16])


class FormatTest(unittest.TestCase):
    def test_steam_unpack_restores_the_hidden_entry0(self):
        a = archive(T, ['BISLPM-66676COM-01', 'BISLPM-66676COM-SYS', 'BISLPM-66676COM-02'])
        self.assertEqual(k.steam_unpack(T, steam_file(T, a), 'x'), a)
        self.assertEqual(k.steam_unpack(T, steam_file(T, a, hide_entry0=False), 'x'), a)

    def test_xbox_blobs(self):
        a = archive(T, ['BISLPM-66676COM-01'])
        blob = k.xbox_pack(T, a)
        self.assertEqual(blob[:16], hashlib.md5(blob[16:]).digest())
        self.assertEqual(k.xbox_unpack(T, blob, 'x'), a)
        kh1 = k.TITLES['kh1']
        a1 = archive(kh1, ['BISLPS-25198-01', '-01/system.bin'])
        b1 = k.xbox_pack(kh1, a1)
        self.assertEqual(len(b1), k.KH1_BLOB)
        self.assertEqual(k.xbox_unpack(kh1, b1, 'x'), a1)
        with self.assertRaisesRegex(SaveError, 'checksum'):
            k.xbox_unpack(T, blob[:-1] + b'\1', 'x')

    def test_steam_pack_round_trip(self):
        a = archive(T, ['BISLPM-66676COM-01', 'BISLPM-66676COM-02'])
        template = steam_file(T, archive(T, ['BISLPM-66676COM-05']), hide_entry0=False)
        self.assertEqual(k.steam_unpack(T, k.steam_pack(T, a, template), 'x'), a)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.wgs = empty_wgs(self.local / 'Packages' / '39EA002F.KH1.52.5_x' / 'SystemAppData' / 'wgs')
        self.mine = k.xbox_pack(T, archive(T, ['BISLPM-66676COM-01', 'BISLPM-66676COM-SYS'], 1790000000))
        WgsStore(self.wgs).write({T.container: {T.container: self.mine},
                                  'MareSaveData/SAVE0.DAT': {'MareSaveData/SAVE0.DAT': b'launcher'},
                                  'config1525.dat': {'config1525.dat': b'config'}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def test_steam_download_replaces_the_game_archive_only(self):
        d = self.local / 'dl'
        d.mkdir()
        theirs = archive(T, ['BISLPM-66676COM-01', 'BISLPM-66676COM-SYS', 'BISLPM-66676COM-02'])
        (d / 'KHReCoM_WW.png').write_bytes(steam_file(T, theirs))
        (d / 'config1525.dat').write_bytes(b'theirs')
        self.assertEqual(self.run_cli('import', 'kh1525', str(d), '--to', 'xbox'), 0)
        store = WgsStore(self.wgs)
        after = {e.name: store.read_blobs(e) for e in store.live_entries()}
        self.assertEqual(k.xbox_unpack(T, after[T.container][T.container], 'x'), theirs)
        self.assertEqual(after['MareSaveData/SAVE0.DAT'], {'MareSaveData/SAVE0.DAT': b'launcher'})
        self.assertEqual(after['config1525.dat'], {'config1525.dat': b'config'})


if __name__ == '__main__':
    unittest.main()
