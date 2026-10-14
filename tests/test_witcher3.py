import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from savebridge import cli, core, lz4, platforms
from savebridge.games import SaveError, get_game
from savebridge.games import witcher3 as w3
from savebridge.wgs import WgsStore
from tests.helpers import empty_wgs

GAME = get_game('witcher3')
MINE = 'ManualSave_53db9_7ea48c00_3cca28d'
THEIRS = 'ManualSave_11c607_7ea47400_3375e79'
META = (b'{\n    "saveMetadata": {\n        "initial buildID": "5.0 test ",\n        "current buildID": "5.0 test ",\n'
        b'        "gameVersion": 29,\n        "saveVersion": 66,\n        "buildPatch": 0,\n'
        b'        "platform": "PC"\n    }\n}\0')


def literal_block(data: bytes) -> bytes:
    """An LZ4 block holding ``data`` as literals only."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    rest, ext = n - 15, bytearray()
    while rest >= 255:
        ext.append(255)
        rest -= 255
    return bytes([0xF0]) + bytes(ext) + bytes([rest]) + data


def raw_save(flags: list[int], save_version: int = 66, game_version: int = 30) -> bytes:
    """A SAV3 body with ContentTaintedFlags content0.. set from ``flags``, plus filler."""
    names = ['Entity', 'nP', 'Uint32', 'isAvailable', 'Bool', 'ContentTaintedFlags'] + \
            [f'content{i}' for i in range(len(flags))]
    rec = b'VL' + struct.pack('<HHI', 6, 3, 12)
    for i, f in enumerate(flags):
        rec += b'VL' + struct.pack('<HH', 7 + i, 5) + bytes([f])
    table = b'MANU' + struct.pack('<II', len(names), 0) + b''.join(bytes([len(n)]) + n.encode() for n in names)
    return b'SAV3' + struct.pack('<III', save_version, game_version, 164) + b'x' * 300 + rec + b'BS' + table + b'SE'


def sav_file(raw: bytes, chunk: int = 256, xbox: bool = False) -> bytes:
    pieces = [raw[i:i + chunk] for i in range(0, len(raw), chunk)]
    blocks = [literal_block(p) for p in pieces]
    head = 0xC0C
    table, pos = bytearray(), head
    for p, b in zip(pieces, blocks):
        last = p is pieces[-1]
        table += struct.pack('<III', len(b), len(p), 0 if xbox and last else pos + len(b))
        pos += len(b)
    header = w3.MAGIC + struct.pack('<II', len(pieces), head) + table
    return header.ljust(head, b'\0') + b''.join(blocks)


PNG = b'\x89PNG\r\n\x1a\nscreenshot'


class FormatTest(unittest.TestCase):
    def test_lz4_overlapping_match(self):
        block = bytes([0x15]) + b'a' + struct.pack('<H', 1)  # 'a' then copy 9 bytes from 1 back
        self.assertEqual(lz4.decompress_block(block, 10), b'a' * 10)

    def test_layouts_and_content(self):
        raw = raw_save([1, 1, 0, 1])
        steam = sav_file(raw)
        xbox = w3.relayout(steam, xbox=True)
        self.assertEqual(w3.relayout(xbox, xbox=False), steam)
        ends = [struct.unpack_from('<I', xbox, 24 + 12 * i)[0] for i in range(struct.unpack_from('<I', xbox, 8)[0])]
        self.assertEqual(ends[-1], 0)
        self.assertTrue(all(ends[:-1]))  # the game finds each chunk from the previous one's end
        self.assertEqual(w3.body(xbox), raw)
        self.assertEqual(w3.required_content(raw), ['content0', 'content1', 'content3'])
        self.assertEqual(w3.con_blob(['content0', 'content1']), b'content0\0content1\0')
        meta = w3.make_meta(META, raw)
        self.assertIn(b'"gameVersion": 30,', meta)
        self.assertTrue(meta.endswith(b'}\0'))

    def test_damaged_save_is_refused(self):
        with self.assertRaises(SaveError):
            w3.chunks(sav_file(raw_save([1]))[:-5])


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = Path(self.tmp.name)
        self.docs = self.local / 'Documents'
        self.wgs = empty_wgs(self.local / 'Packages' / 'CDPROJEKTSA.Witcher3GOTY_x' / 'SystemAppData' / 'wgs')
        self.mine = {'con': b'content0\0', 'meta': META, 'sav': sav_file(raw_save([1]), xbox=True),
                     'scr': PNG}
        WgsStore(self.wgs).write({MINE: self.mine, 'settings': {'str': b'[Rendering]'}})
        for p in (mock.patch.object(platforms, 'LOCALAPPDATA', self.local),
                  mock.patch.object(platforms, 'BACKUP_ROOT', self.local / 'backups'),
                  mock.patch.object(w3, 'documents_dir', lambda: self.docs),
                  mock.patch.object(core, 'running_processes', lambda: set())):
            p.start()
            self.addCleanup(p.stop)

    def run_cli(self, *argv):
        with mock.patch('sys.stdout'), mock.patch('sys.stderr'):
            return cli.main(list(argv))

    def xbox(self) -> dict[str, dict[str, bytes]]:
        store = WgsStore(self.wgs)
        return {e.name: store.read_blobs(e) for e in store.live_entries()}

    def test_steam_download_becomes_a_new_xbox_save(self):
        d = self.local / 'dl'
        d.mkdir()
        raw = raw_save([1] * 13 + [0] * 4)
        (d / f'{THEIRS}.sav').write_bytes(sav_file(raw))
        (d / f'{THEIRS}.png').write_bytes(PNG + b'2')
        self.assertEqual(self.run_cli('import', 'witcher3', str(d), '--to', 'xbox'), 0)
        after = self.xbox()
        self.assertEqual(after[MINE], self.mine)
        self.assertEqual(after['settings'], {'str': b'[Rendering]'})
        new = after[THEIRS]
        self.assertEqual(new['sav'], sav_file(raw, xbox=True))
        self.assertEqual(new['scr'], PNG + b'2')
        self.assertEqual(new['con'], b''.join(f'content{i}\0'.encode() for i in range(13)))
        self.assertIn(b'"gameVersion": 30,', new['meta'])
        self.assertIn(b'5.0 test', new['meta'])

    def test_xbox_to_steam(self):
        self.assertEqual(self.run_cli('convert', 'witcher3', 'xbox-to-steam'), 0)
        folder = self.docs / 'The Witcher 3' / 'gamesaves'
        self.assertEqual((folder / f'{MINE}.sav').read_bytes(), sav_file(raw_save([1])))
        self.assertEqual((folder / f'{MINE}.png').read_bytes(), PNG)

    def test_needs_an_own_xbox_save_for_the_build(self):
        with mock.patch.object(WgsStore, 'live_entries', lambda self: []):
            with self.assertRaisesRegex(SaveError, 'save once'):
                GAME.rebind(GAME.collect([GAME.identify(sav_file(raw_save([1])), f'dl/{THEIRS}.sav')])
                            .saves[THEIRS], core.resolve_xbox(GAME, None))


if __name__ == '__main__':
    unittest.main()
