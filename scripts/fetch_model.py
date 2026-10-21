"""Fetch only the pinned public ONNX file at image build; verify its release hash."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request


def fetch(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'release.json').read_text())
    path = directory/'model.onnx'
    expected = manifest['artifacts']['model.onnx']
    if path.exists():
        with path.open('rb') as source:
            if hashlib.file_digest(source,'sha256').hexdigest()==expected:
                return
        raise ValueError('Existing model checksum mismatch')
    model = manifest['embedding']
    if model['model'] != 'sentence-transformers/all-MiniLM-L6-v2' or len(model['revision']) != 40:
        raise ValueError('Unexpected release model')
    url = f'https://huggingface.co/{model["model"]}/resolve/{model["revision"]}/onnx/model.onnx'
    temporary = path.with_suffix('.tmp')
    with urllib.request.urlopen(url,timeout=120) as source, temporary.open('wb') as output:
        while chunk := source.read(1024*1024):
            output.write(chunk)
    with temporary.open('rb') as source:
        if hashlib.file_digest(source,'sha256').hexdigest()!=expected:
            temporary.unlink()
            raise ValueError('Downloaded ONNX model checksum mismatch')
    temporary.replace(path)


if __name__=='__main__':
    fetch(os.environ.get('RESEARCHGRAPH_RELEASE','build/release'))
