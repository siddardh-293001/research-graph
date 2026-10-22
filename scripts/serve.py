"""Build and serve the local app; no cloud resources or API credits are used."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    release = Path(os.environ.get('RESEARCHGRAPH_RELEASE', ROOT / 'build/release'))
    if not (release / 'release.json').is_file() or not (release / 'model.onnx').is_file():
        sys.exit('Serving data is missing. Run scripts/restore_release.py and scripts/fetch_model.py first.')
    if not shutil.which('npm'):
        sys.exit('Node.js and npm are required to build the interface. Install Node.js, then run this launcher again.')
    if not (ROOT / 'web/node_modules').is_dir():
        subprocess.run(['npm', 'ci'], cwd=ROOT / 'web', check=True)
    subprocess.run(['npm', 'run', 'build'], cwd=ROOT / 'web', check=True)
    print('\nOpen http://127.0.0.1:8000 after the server reports startup complete.\nKeep this terminal open; press Ctrl+C to stop.\n', flush=True)
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'src.api:app',
                            '--host', '127.0.0.1', '--port', '8000', '--no-access-log'])


if __name__ == '__main__':
    main()
