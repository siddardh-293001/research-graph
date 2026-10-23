"""Load a verified remote atlas before serving; fall back to the bundled release."""
import os
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.remote_release import fetch


def main():
    bundled=Path(os.environ.get('RESEARCHGRAPH_RELEASE','/app/release'))
    if os.environ.get('RESEARCHGRAPH_REMOTE_RELEASE','1')=='1':
        try:
            temp=Path(tempfile.mkdtemp(prefix='researchgraph-release-'))
            result=fetch(temp/'parts',temp/'release',bundled/'model.onnx')
            if result:
                os.environ['RESEARCHGRAPH_RELEASE']=str(temp/'release')
                print('Loaded verified atlas release:',result,flush=True)
        except Exception as exc:
            print('Remote atlas unavailable; serving bundled release:',type(exc).__name__,flush=True)
    os.execv(sys.executable,[sys.executable,'-m','uvicorn','src.api:app','--host','0.0.0.0','--port',os.environ.get('PORT','8000'),'--workers','1','--no-access-log'])

if __name__=='__main__':main()
