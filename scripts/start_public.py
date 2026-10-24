"""Supervise one search process and adopt verified atlas releases with rollback."""
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.remote_release import fetch,REPOSITORY,latest_release
from scripts.restore_release import digest


def ready(process,expected,timeout=90):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if process.poll() is not None:return False
        try:
            with urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/readyz',timeout=2) as response:
                if json.load(response).get('release_sha256')==expected:return True
        except (OSError,ValueError):pass
        time.sleep(.25)
    return False


def main():
    bundled=Path(os.environ.get('RESEARCHGRAPH_RELEASE','/app/release')).resolve();active=bundled;child=None;stopping=False
    enabled=os.environ.get('RESEARCHGRAPH_REMOTE_RELEASE','1')=='1'
    def launch(directory):
        env=dict(os.environ,RESEARCHGRAPH_RELEASE=str(directory))
        return subprocess.Popen([sys.executable,'-m','uvicorn','src.api:app','--host','0.0.0.0','--port',os.environ.get('PORT','8000'),'--workers','1','--no-access-log'],cwd=ROOT,env=env)
    def stop(process):
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    def shutdown(*args):
        nonlocal stopping
        stopping=True;stop(child)
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    def download():
        temp=Path(tempfile.mkdtemp(prefix='researchgraph-release-'))
        try:
            info=fetch(temp/'parts',temp/'release',bundled/'model.onnx')
            if info:
                shutil.rmtree(temp/'parts');return temp/'release'
            shutil.rmtree(temp);return None
        except Exception as exc:
            print('Atlas refresh unavailable:',type(exc).__name__,getattr(exc,'code',''),flush=True);shutil.rmtree(temp,ignore_errors=True);return None
    if enabled:
        candidate=download()
        if candidate:active=candidate
    if stopping:return
    child=launch(active)
    if not ready(child,digest(active/'release.json')):
        stop(child)
        if stopping:return
        active=bundled;child=launch(active)
        if not ready(child,digest(active/'release.json')):stop(child);sys.exit('Bundled atlas failed readiness')
    print('Serving atlas:',digest(active/'release.json'),flush=True)
    next_check=time.monotonic()+300
    while not stopping:
        if child.poll() is not None:
            print('Search process exited; restoring bundled atlas',flush=True)
            active=bundled;child=launch(active)
            if not ready(child,digest(active/'release.json')):stop(child);sys.exit('Search process could not recover')
        if enabled and time.monotonic()>=next_check:
            next_check=time.monotonic()+300
            try:
                latest=latest_release()
                current='atlas-'+digest(active/'release.json')[:16]
                if latest and latest.get('tag_name')!=current:
                    candidate=download()
                    if candidate and digest(candidate/'release.json')!=digest(active/'release.json'):
                        old=active;stop(child)
                        if stopping:break
                        child=launch(candidate)
                        if ready(child,digest(candidate/'release.json')):
                            active=candidate;print('Adopted verified atlas:',digest(active/'release.json'),flush=True)
                            if old!=bundled:shutil.rmtree(old.parent,ignore_errors=True)
                        else:
                            stop(child)
                            if stopping:break
                            child=launch(old);active=old
                            if not ready(child,digest(old/'release.json')):stop(child);sys.exit('Rollback failed')
                            shutil.rmtree(candidate.parent,ignore_errors=True)
                            print('Candidate startup failed; restored previous atlas',flush=True)
            except (OSError,ValueError) as exc:print('Atlas poll unavailable:',type(exc).__name__,getattr(exc,'code',''),flush=True)
        time.sleep(1)
    stop(child)

if __name__=='__main__':main()
