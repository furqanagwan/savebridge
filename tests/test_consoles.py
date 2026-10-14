import struct
import tempfile
import unittest
from pathlib import Path

from savebridge import consoles
from savebridge.core import scan
from savebridge.games import SaveError, get_game


def sfo(entries: dict[str, object]) -> bytes:
    """A PARAM.SFO with the given entries (str = utf-8, int = int32, bytes = raw)."""
    keys, values, index = b'', b'', b''
    for k, v in entries.items():
        if isinstance(v, int):
            fmt, raw = 0x0404, struct.pack('<I', v)
        elif isinstance(v, str):
            fmt, raw = 0x0204, v.encode() + b'\0'
        else:
            fmt, raw = 0x0004, v
        index += struct.pack('<HHIII', len(keys), fmt, len(raw), len(raw), len(values))
        keys += k.encode() + b'\0'
        values += raw
    keys_at = 20 + len(index)
    data_at = keys_at + len(keys)
    return b'\x00PSF' + struct.pack('<IIII', 0x101, keys_at, data_at, len(entries)) + index + keys + values


class SfoTest(unittest.TestCase):
    def test_parse(self):
        info = consoles.parse_sfo(sfo({'TITLE_ID': 'CUSA12345', 'TITLE': 'Cuphead', 'SAVEDATA_BLOCKS': 96,
                                       'ACCOUNT_ID': b'\x01' * 8}))
        self.assertEqual((info['TITLE_ID'], info['TITLE'], info['SAVEDATA_BLOCKS']), ('CUSA12345', 'Cuphead', 96))
        self.assertEqual(info['ACCOUNT_ID'], b'\x01' * 8)  # kept raw, never shown
        with self.assertRaises(consoles.SfoError):
            consoles.parse_sfo(b'not an sfo file at all')


class FindTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def ps4_save(self) -> Path:
        d = self.root / 'apollo' / 'CUSA12345_00-SAVEDATA00'
        (d / 'sce_sys').mkdir(parents=True)
        (d / 'sce_sys' / 'param.sfo').write_bytes(sfo({'TITLE_ID': 'CUSA12345', 'TITLE': 'Cuphead',
                                                         'SUB_TITLE': 'Slot 1', 'ACCOUNT_ID': b'\x07' * 8}))
        (d / 'sce_sys' / 'icon0.png').write_bytes(b'png')
        (d / 'cuphead_player_data_v1_slot_0.sav').write_bytes(b'{}')
        return d

    def test_ps4_folder(self):
        self.ps4_save()
        [found] = consoles.find([self.root])
        self.assertEqual((found.platform, found.title_id, found.title), ('ps4', 'CUSA12345', 'Cuphead'))
        self.assertEqual(list(found.files), ['cuphead_player_data_v1_slot_0.sav'])  # no sce_sys
        self.assertIn('PlayStation 4 save of Cuphead (Slot 1), CUSA12345', found.label())

    def test_ps3_folder(self):
        d = self.root / 'BLES01234-SAVE'
        d.mkdir()
        (d / 'PARAM.SFO').write_bytes(sfo({'TITLE_ID': 'BLES01234', 'TITLE': 'Some Game', 'PARAMS': b'\0' * 32}))
        (d / 'PARAM.PFD').write_bytes(b'\0' * 64)
        (d / 'DATA.BIN').write_bytes(b'save')
        [found] = consoles.find([self.root])
        self.assertEqual((found.platform, list(found.files)), ('ps3', ['DATA.BIN']))

    def test_unsupported_console_import_is_explained(self):
        self.ps4_save()
        with self.assertRaisesRegex(SaveError, 'PlayStation 4 save of Cuphead.*does not convert Cuphead saves'):
            scan(get_game('cuphead'), [self.root])


if __name__ == '__main__':
    unittest.main()
