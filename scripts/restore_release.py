"""Restore only checksummed regular files from the published frozen release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile


def digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def restore(parts,output):
    parts,output=Path(parts),Path(output)
    manifest=json.loads((parts/'manifest.json').read_text())
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryFile() as joined:
        for part in manifest['parts']:
            if Path(part['file']).name!=part['file']:raise ValueError('Unsafe part name')
            path=parts/part['file']
            if path.stat().st_size!=part['bytes'] or digest(path)!=part['sha256']:raise ValueError('Release part checksum mismatch')
            with path.open('rb') as source:shutil.copyfileobj(source,joined)
        joined.seek(0)
        if hashlib.file_digest(joined,'sha256').hexdigest()!=manifest['archive_sha256']:raise ValueError('Archive checksum mismatch')
        joined.seek(0)
        with tarfile.open(fileobj=joined,mode='r:gz') as archive:
            members=archive.getmembers()
            if len(members)>30 or sum(m.size for m in members)>256*1024*1024:raise ValueError('Archive exceeds the bounded release size')
            names=set()
            for member in members:
                if not member.isfile() or member.name!=Path(member.name).name or member.name in names or member.size>128*1024*1024:
                    raise ValueError('Unsafe archive member')
                names.add(member.name)
                with archive.extractfile(member) as source, (output/member.name).open('wb') as target:shutil.copyfileobj(source,target)
    if digest(output/'release.json')!=manifest['release_sha256']:raise ValueError('Restored release manifest mismatch')
    release=json.loads((output/'release.json').read_text())
    for name,expected in release['artifacts'].items():
        if name=='model.onnx':continue # fetched from the pinned public revision during image build
        if Path(name).name!=name or digest(output/name)!=expected:raise ValueError('Restored artifact checksum mismatch')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parts',type=Path,default=Path('deploy/release-parts'))
    parser.add_argument('--output',type=Path,default=Path(os.environ.get('RESEARCHGRAPH_RELEASE','build/release')))
    args=parser.parse_args();print('Restored release:',restore(args.parts,args.output))
