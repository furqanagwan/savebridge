"""Xbox PC (Game Pass / Microsoft Store) save storage, a.k.a. "wgs".

Layout of %LOCALAPPDATA%/Packages/<package>/SystemAppData/wgs/<XUID>_<SCID>/:

    containers.index          list of containers (one per game save "slot")
    <FOLDER GUID>/container.N manifest naming the blobs in that container
    <FOLDER GUID>/<BLOB GUID> blob contents (the game's own bytes)

Write rules follow what the Xbox app expects so a local change is uploaded
instead of overwritten by the cloud copy: never mint an ETag, mark containers
the cloud already knows as Modified (and new ones as Created), advance the
index FILETIME, and clear the FullyUploaded flag. In each manifest, a new blob
keeps the cloud blob id of the version the cloud holds (all zeros if it holds
none); pointing it at the new local blob makes sync believe it's already
uploaded and it never finishes.
"""

from __future__ import annotations

import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


class WgsError(Exception):
    pass


STATE_SYNCED, STATE_MODIFIED, STATE_DELETED, STATE_CREATED = 1, 2, 3, 5
FLAG_FULLY_UPLOADED = 1
BLOB_ENTRY = 160  # 128-byte UTF-16 name + cloud blob GUID + local blob GUID


def _rstr(b: bytes, o: int) -> tuple[str, int]:
    n = struct.unpack_from('<I', b, o)[0]
    o += 4
    return b[o:o + n * 2].decode('utf-16le'), o + n * 2


def _wstr(s: str) -> bytes:
    return struct.pack('<I', len(s)) + s.encode('utf-16le')


def filetime_now() -> int:
    ms = int(time.time() * 1000)  # entries are millisecond granular
    return (ms + 11644473600000) * 10000


def guid_dir(g: uuid.UUID) -> str:
    return g.hex.upper()


@dataclass
class Entry:
    name: str
    name2: str
    etag: str
    number: int
    state: int
    folder: uuid.UUID
    mtime: int
    reserved: int
    size: int


@dataclass
class Index:
    version: int
    reserved: int
    package: str
    mtime: int
    flags: int
    root_id: str
    tail: bytes
    entries: list[Entry] = field(default_factory=list)

    @classmethod
    def parse(cls, b: bytes) -> 'Index':
        try:
            return cls._parse(b)
        except (struct.error, UnicodeDecodeError, ValueError):
            raise WgsError('invalid or truncated containers.index') from None

    @classmethod
    def _parse(cls, b: bytes) -> 'Index':
        version, count, reserved = struct.unpack_from('<III', b, 0)
        if version != 14:
            raise WgsError(f'unsupported containers.index version {version}')
        o = 12
        package, o = _rstr(b, o)
        mtime, flags = struct.unpack_from('<QI', b, o)
        o += 12
        root_id, o = _rstr(b, o)
        tail = b[o:o + 8]
        o += 8
        idx = cls(version, reserved, package, mtime, flags, root_id, tail)
        for _ in range(count):
            name, o = _rstr(b, o)
            name2, o = _rstr(b, o)
            etag, o = _rstr(b, o)
            number, state = struct.unpack_from('<BI', b, o)
            o += 5
            folder = uuid.UUID(bytes_le=b[o:o + 16])
            o += 16
            emtime, ereserved, size = struct.unpack_from('<QQQ', b, o)
            o += 24
            idx.entries.append(Entry(name, name2, etag, number, state, folder,
                                     emtime, ereserved, size))
        return idx

    def build(self) -> bytes:
        out = [struct.pack('<III', self.version, len(self.entries), self.reserved),
               _wstr(self.package), struct.pack('<QI', self.mtime, self.flags),
               _wstr(self.root_id), self.tail]
        for e in self.entries:
            out += [_wstr(e.name), _wstr(e.name2), _wstr(e.etag),
                    struct.pack('<BI', e.number, e.state), e.folder.bytes_le,
                    struct.pack('<QQQ', e.mtime, e.reserved, e.size)]
        return b''.join(out)


NO_CLOUD_BLOB = uuid.UUID(int=0)


@dataclass(frozen=True)
class BlobRef:
    """A blob as listed in a container.N manifest.

    ``cloud`` names the version the cloud holds (all zeros if none) and ``disk``
    names the local file. They are equal only once the blob has been uploaded;
    the sync service uploads a blob when they differ. Claiming a cloud version
    that was never uploaded leaves sync stuck.
    """
    cloud: uuid.UUID
    disk: uuid.UUID


def parse_manifest(b: bytes) -> dict[str, BlobRef]:
    _, count = struct.unpack_from('<II', b, 0)
    blobs = {}
    for i in range(count):
        o = 8 + i * BLOB_ENTRY
        name = b[o:o + 128].decode('utf-16le').rstrip('\0')
        blobs[name] = BlobRef(uuid.UUID(bytes_le=b[o + 128:o + 144]),
                              uuid.UUID(bytes_le=b[o + 144:o + 160]))
    return blobs


def build_manifest(blobs: dict[str, BlobRef]) -> bytes:
    out = [struct.pack('<II', 4, len(blobs))]
    for name, ref in blobs.items():
        if len(name) > 63:
            raise WgsError(f'blob name too long: {name}')
        out.append(name.encode('utf-16le').ljust(128, b'\0')
                   + ref.cloud.bytes_le + ref.disk.bytes_le)
    return b''.join(out)


class WgsStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / 'containers.index'
        if not self.index_path.is_file():
            raise WgsError(f'no containers.index in {self.root}')

    def index(self) -> Index:
        return Index.parse(self.index_path.read_bytes())

    def live_entries(self) -> list[Entry]:
        return [e for e in self.index().entries if e.state != STATE_DELETED]

    def _manifest_path(self, e: Entry) -> Path:
        return self.root / guid_dir(e.folder) / f'container.{e.number}'

    def read_blobs(self, e: Entry) -> dict[str, bytes]:
        folder = self.root / guid_dir(e.folder)
        blobs = parse_manifest(self._manifest_path(e).read_bytes())
        return {name: (folder / guid_dir(ref.disk)).read_bytes() for name, ref in blobs.items()}

    def write(self, changes: dict[str, dict[str, bytes]],
              reserved: dict[str, int] | None = None) -> None:
        """Create or replace containers.

        ``changes`` maps container name -> {blob name: bytes}. ``reserved`` gives
        the index entry's reserved field for containers that don't exist yet.
        """
        idx = self.index()
        live = {e.name: e for e in idx.entries if e.state != STATE_DELETED}
        superseded: list[Path] = []
        for name, blobs in changes.items():
            e = live.get(name)
            previous: dict[str, BlobRef] = {}
            if e is None:
                e = Entry(name, name, '', 0, STATE_CREATED, uuid.uuid4(), 0,
                          (reserved or {}).get(name, 0), 0)
                idx.entries.append(e)
                live[name] = e
                (self.root / guid_dir(e.folder)).mkdir()
            else:
                old = self._manifest_path(e)
                if old.is_file():
                    previous = parse_manifest(old.read_bytes())
                    superseded.append(old)
                    superseded += [old.parent / guid_dir(ref.disk) for ref in previous.values()]
            folder = self.root / guid_dir(e.folder)
            refs = {}
            for blob_name, data in blobs.items():
                disk = uuid.uuid4()
                (folder / guid_dir(disk)).write_bytes(data)
                # Keep pointing at the version the cloud really has (as the game
                # does); a container the cloud has never seen has no cloud blob.
                cloud = previous[blob_name].cloud if e.etag and blob_name in previous \
                    else NO_CLOUD_BLOB
                refs[blob_name] = BlobRef(cloud, disk)
            e.number = e.number % 255 + 1
            (folder / f'container.{e.number}').write_bytes(build_manifest(refs))
            e.size = sum(len(d) for d in blobs.values())
            e.mtime = filetime_now()
            e.state = STATE_MODIFIED if e.etag else STATE_CREATED
        idx.mtime = max(filetime_now(), idx.mtime + 1)
        idx.flags &= ~FLAG_FULLY_UPLOADED
        tmp = self.index_path.with_name('containers.index.tmp')
        tmp.write_bytes(idx.build())
        os.replace(tmp, self.index_path)
        for p in superseded:
            if p.exists():
                p.unlink()
