import tempfile
import unittest
from pathlib import Path

from savebridge.wgs import (FLAG_FULLY_UPLOADED, NO_CLOUD_BLOB, STATE_CREATED,
                            STATE_MODIFIED, BlobRef, Index, WgsStore, build_manifest,
                            guid_dir, parse_manifest)
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

    def manifest(self, e):
        return parse_manifest((self.root / guid_dir(e.folder) / f'container.{e.number}').read_bytes())

    def test_new_container_claims_no_cloud_blob(self):
        self.store.write({'Slot': {'Data': b'hello'}})
        (e,) = self.store.index().entries
        ref = self.manifest(e)['Data']
        self.assertEqual(ref.cloud, NO_CLOUD_BLOB)
        self.assertNotEqual(ref.disk, NO_CLOUD_BLOB)

    def pretend_uploaded(self):
        """Make the store look like the Xbox app just synced it."""
        idx = self.store.index()
        e = idx.entries[0]
        e.etag, e.state = '"0x8D00000000000A1"', 1
        mpath = self.root / guid_dir(e.folder) / f'container.{e.number}'
        refs = parse_manifest(mpath.read_bytes())
        mpath.write_bytes(build_manifest({n: BlobRef(r.disk, r.disk) for n, r in refs.items()}))
        (self.root / 'containers.index').write_bytes(idx.build())
        return refs['Data'].disk

    def test_replacing_synced_container_keeps_etag_and_cloud_blob(self):
        self.store.write({'Slot': {'Data': b'one'}})
        uploaded = self.pretend_uploaded()
        before = self.store.index().mtime

        self.store.write({'Slot': {'Data': b'two!'}})
        idx = self.store.index()
        (e,) = idx.entries
        self.assertEqual((e.state, e.etag, e.size), (STATE_MODIFIED, '"0x8D00000000000A1"', 4))
        self.assertGreater(idx.mtime, before)
        self.assertEqual(self.store.read_blobs(e), {'Data': b'two!'})
        ref = self.manifest(e)['Data']
        self.assertEqual(ref.cloud, uploaded)      # still the version the cloud has
        self.assertNotEqual(ref.disk, uploaded)    # new local data, so it gets uploaded
        folder = self.root / e.folder.hex.upper()
        self.assertEqual(len(list(folder.iterdir())), 2)  # one manifest, one blob

    def test_multi_blob_container(self):
        self.store.write({'World': {'Level': b'a' * 10, 'Players': b'b' * 3}})
        (e,) = self.store.index().entries
        self.assertEqual(self.store.read_blobs(e), {'Level': b'a' * 10, 'Players': b'b' * 3})
        self.assertEqual(e.size, 13)


if __name__ == '__main__':
    unittest.main()
