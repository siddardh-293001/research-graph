"""Verify exploration against the frozen release without external requests."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.public_engine import PublicEngine
from src.exploration import browse,evidence,trends,author_profile
engine=PublicEngine(Path(__file__).resolve().parents[1]/'build/release')
a=browse(engine);b=browse(engine,page=2)
assert a['release_sha256']==engine.release_sha256
assert len(a['matching_ids'])==a['total']
assert not {r['paper_id'] for r in a['results']}&{r['paper_id'] for r in b['results']}
p=a['results'][0];e=evidence(engine,p['paper_id'],'model methods results')
assert all(r['text'] in p['abstract'] for r in e['passages'])
assert all(r['text'] in p['abstract'] for rows in e['matrix'].values() for r in rows)
assert trends(engine)['years']
print('PASS: release-bound matches, pagination, grounded excerpts, chronology and trends')

name=engine.paper(p["paper_id"])["authors"][0]
profile=author_profile(engine,name)
assert profile["total"]>=1 and any(r["paper_id"]==p["paper_id"] for r in profile["results"])
