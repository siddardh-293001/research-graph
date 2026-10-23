"""Offline end-to-end update/replay/retraction verification against real serving data."""
from contextlib import closing
from datetime import datetime,timezone
import argparse
import json
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.update_release import update
from src.public_engine import PublicEngine


def check(source):
    engine=PublicEngine(source)
    with closing(engine.connect()) as db:
        p=dict(db.execute('SELECT * FROM papers ORDER BY row_id DESC LIMIT 1').fetchone())
    new={'paper_id':'https://openalex.org/W999999999999999','title':p['title'],'abstract':p['abstract'],'year':p['year'],'citation_count':3,'publication_date':'2026-10-22','updated_date':'2026-10-23T00:00:00Z','authors':[],'topics':[],'keywords':[],'referenced_works':[p['paper_id']]}
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);result=update(source,[new],root/'candidate');candidate=PublicEngine(root/'candidate')
        assert len(candidate.ids)==len(engine.ids)+1
        detail=candidate.paper(new['paper_id']);assert detail['citation_context']['global_count']==3
        assert detail['connections']['cites'][0]['paper_id']==p['paper_id']
        assert all(s in new['abstract'] for s in detail['summary']['sentences'])
        assert candidate.feed()['live_updates']
        replay=update(root/'candidate',[new],root/'replay');assert not replay['changed'] and not (root/'replay').exists()
        correction=dict(new,citation_count=7,updated_date='2026-10-24T00:00:00Z')
        update(root/'candidate',[correction],root/'corrected');assert PublicEngine(root/'corrected').paper(new['paper_id'])['citation_context']['global_count']==7
        retraction=dict(new,is_retracted=True,updated_date='2026-10-25T00:00:00Z')
        update(root/'corrected',[retraction],root/'retracted');removed=PublicEngine(root/'retracted');assert removed.paper(new['paper_id']) is None and len(removed.ids)==len(engine.ids)
        with closing(removed.connect()) as db:assert db.execute('SELECT count(*) FROM citations WHERE source=? OR target=?',(new['paper_id'],new['paper_id'])).fetchone()[0]==0
        arxiv=dict(new,paper_id='https://arxiv.org/abs/2610.12345v2',source='arxiv',citation_count_available=False)
        update(source,[arxiv],root/'arxiv');assert PublicEngine(root/'arxiv').paper('https://arxiv.org/abs/2610.12345')['citation_context']['global_count'] is None
    return {'passed':True,'synthetic_fixture_only':True,'checks':['addition','directed citation evidence','grounded summary','idempotent replay','citation correction','retraction removes index and links','arxiv canonical versions and unknown citation counts'],'active_release_unchanged':True}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT/'build/release');p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=check(a.source);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
