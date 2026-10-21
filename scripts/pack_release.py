"""Create bounded, checksummed public release parts for GitHub publication."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def pack(source, output, part_bytes=20*1024*1024):
    source,output=Path(source),Path(output)
    if output.exists():raise ValueError('Use a fresh parts directory')
    output.mkdir(parents=True)
    release=json.loads((source/'release.json').read_text())
    temporary=output/'release.tar.gz'
    with temporary.open('wb') as raw, gzip.GzipFile(fileobj=raw,mode='wb',mtime=0,filename='') as compressed, tarfile.open(fileobj=compressed,mode='w') as archive:
        for name in sorted([*release['artifacts'],'release.json']):
            if Path(name).name!=name:raise ValueError('Unsafe release file name')
            if name=='model.onnx':continue
            if name!='release.json' and digest(source/name)!=release['artifacts'][name]:raise ValueError('Release artifact changed')
            data=(source/name).read_bytes()
            info=tarfile.TarInfo(name);info.size=len(data);info.mtime=0;info.mode=0o644
            archive.addfile(info,io.BytesIO(data))
    manifest={'schema_version':1,'release_sha256':digest(source/'release.json'),
              'archive_sha256':digest(temporary),'parts':[]}
    with temporary.open('rb') as archive:
        while chunk:=archive.read(part_bytes):
            path=output/f'release-{len(manifest["parts"]):03d}.part';path.write_bytes(chunk)
            manifest['parts'].append({'file':path.name,'bytes':len(chunk),'sha256':digest(path)})
    temporary.unlink()
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=Path('build/release'))
    parser.add_argument('--output',type=Path,default=Path('deploy/release-parts'))
    args=parser.parse_args();manifest=pack(args.source,args.output)
    print(json.dumps({'parts':len(manifest['parts']),'bytes':sum(p['bytes'] for p in manifest['parts']),'output':str(args.output)},indent=2))
