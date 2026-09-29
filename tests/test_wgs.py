import tempfile
import unittest
from pathlib import Path

from savebridge.wgs import (FLAG_FULLY_UPLOADED, STATE_CREATED, STATE_MODIFIED, Index,
                            WgsStore)
from tests.helpers import empty_wgs


class WgsStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = empty_wgs(Path(self.tmp.name))
        self.store = WgsStore(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_round_trips_byte_for_byte(self):
        raw = (self.root / 'containers.index').read_bytes()
        self.assertEqual(Index.parse(raw).build(), raw)

    def test_new_container_is_created_without_etag(self):
        self.store.write({'Slot': {'Data': b'hello'}}, {'Slot': 1})
        idx = self.store.index()
        (e,) = idx.entries
        self.assertEqual((e.name, e.state, e.etag, e.size, e.reserved),
                         ('Slot', STATE_CREATED, '', 5, 1))
        self.assertFalse(idx.flags & FLAG_FULLY_UPLOADED)
        self.assertEqual(self.store.read_blobs(e), {'Data': b'hello'})

    def test_replacing_synced_container_keeps_etag_and_prunes_old_files(self):
        self.store.write({'Slot': {'Data': b'one'}})
        idx = self.store.index()
        idx.entries[0].etag = '"0x8D00000000000A1"'  # pretend the cloud has it
        idx.entries[0].state = 1
        (self.root / 'containers.index').write_bytes(idx.build())
        before = self.store.index().mtime

        self.store.write({'Slot': {'Data': b'two!'}})
        idx = self.store.index()
        (e,) = idx.entries
        self.assertEqual((e.state, e.etag, e.size), (STATE_MODIFIED, '"0x8D00000000000A1"', 4))
        self.assertGreater(idx.mtime, before)
        self.assertEqual(self.store.read_blobs(e), {'Data': b'two!'})
        folder = self.root / e.folder.hex.upper()
        self.assertEqual(len(list(folder.iterdir())), 2)  # one manifest, one blob

    def test_multi_blob_container(self):
        self.store.write({'World': {'Level': b'a' * 10, 'Players': b'b' * 3}})
        (e,) = self.store.index().entries
        self.assertEqual(self.store.read_blobs(e), {'Level': b'a' * 10, 'Players': b'b' * 3})
        self.assertEqual(e.size, 13)


if __name__ == '__main__':
    unittest.main()
