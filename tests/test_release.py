"""Checksummed publication parts: round-trip, tampering and path safety."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from scripts.pack_release import pack
from scripts.restore_release import restore,digest


class ReleasePackagingTests(unittest.TestCase):
    def source(self,root):
        source=root/'source';source.mkdir();(source/'metadata.txt').write_text('public research metadata')
        (source/'release.json').write_text(json.dumps({'artifacts':{'metadata.txt':digest(source/'metadata.txt'),'model.onnx':'not-shipped'}}))
        return source

    def test_parts_round_trip_and_repeatable_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=self.source(root)
            first=pack(source,root/'a',part_bytes=100);second=pack(source,root/'b',part_bytes=100)
            self.assertEqual(first,second)
            self.assertGreater(len(first['parts']),1)
            restore(root/'a',root/'restored')
            self.assertEqual((root/'restored/metadata.txt').read_bytes(),(source/'metadata.txt').read_bytes())
            self.assertFalse((root/'restored/model.onnx').exists())

    def test_changed_part_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);manifest=pack(self.source(root),root/'parts')
            (root/'parts'/manifest['parts'][0]['file']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):restore(root/'parts',root/'output')

    def test_archive_traversal_is_rejected_even_with_matching_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);parts=root/'parts';parts.mkdir();path=parts/'release-000.part'
            with tarfile.open(path,'w:gz') as archive:
                entry=tarfile.TarInfo('../outside');entry.size=1;archive.addfile(entry,io.BytesIO(b'x'))
            (parts/'manifest.json').write_text(json.dumps({'archive_sha256':digest(path),'release_sha256':'unused',
                  'parts':[{'file':path.name,'bytes':path.stat().st_size,'sha256':digest(path)}]}))
            with self.assertRaisesRegex(ValueError,'Unsafe archive'):restore(parts,root/'output')
            self.assertFalse((root/'outside').exists())


if __name__=='__main__':unittest.main()
