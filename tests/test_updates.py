"""Real release lifecycle regressions, plus bounded source parsing and rollback preflight."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.collect_sources import arxiv_records,crossref_records
from scripts.promote_release import promote
from scripts.remote_release import fetch
from scripts.update_release import update


class UpdateContractTests(unittest.TestCase):
    def test_arxiv_preserves_version_and_does_not_invent_citation_counts(self):
        xml='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2601.12345v2</id><title>Graph learning</title><summary>A genuine abstract.</summary><published>2026-01-02T00:00:00Z</published><updated>2026-01-03T00:00:00Z</updated></entry></feed>'''
        row=arxiv_records(xml)[0]
        self.assertFalse(row['citation_count_available']);self.assertTrue(row['paper_id'].endswith('v2'))
        self.assertEqual(row['year'],2026)

    def test_crossref_does_not_treat_missing_abstract_as_full_text(self):
        rows=crossref_records({'message':{'items':[{'DOI':'10.1234/example','title':['Software engineering'],'published':{'date-parts':[[2026]]}}]}})
        self.assertEqual(rows[0]['abstract'],'');self.assertEqual(rows[0]['source'],'crossref')

    def test_oversized_update_rejected_before_model_load(self):
        with self.assertRaises(ValueError):update('/does/not/exist',[{}]*501,'/does/not/exist/output')

    def test_promotion_rejects_missing_candidate_before_network(self):
        with patch.dict('os.environ',{'GH_TOKEN':'fixture'},clear=True),patch('urllib.request.urlopen') as request:
            with self.assertRaises(FileNotFoundError):promote('unused','unused')
            request.assert_not_called()

    def test_remote_release_rejects_unrelated_tag_before_downloading(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return b'{"tag_name":"unrelated","assets":[]}'
        with tempfile.TemporaryDirectory() as temp,patch('urllib.request.urlopen',return_value=Response()):
            with self.assertRaises(ValueError):fetch(Path(temp)/'parts',Path(temp)/'release','unused')

    def test_supervisor_rolls_back_failed_candidate_startup(self):
        from scripts.start_public import main
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bundled=root/'bundled';bundled.mkdir();(bundled/'release.json').write_text('{}')
            work=root/'work';work.mkdir();handlers={};children=[]
            def fake_fetch(parts,output,model):
                parts.mkdir();output.mkdir();(output/'release.json').write_text('{"candidate":true}');return {'tag':'fixture'}
            class Child:
                def __init__(self,*args,**kwargs):self.code=None;self.env=kwargs['env'];children.append(self)
                def poll(self):return self.code
                def terminate(self):self.code=0
                def wait(self,timeout=None):return self.code
            def register(sig,callback):handlers[sig]=callback
            def tick(seconds):
                import signal
                handlers[signal.SIGTERM]()
            with patch.dict('os.environ',{'RESEARCHGRAPH_RELEASE':str(bundled),'RESEARCHGRAPH_REMOTE_RELEASE':'1'}),patch('scripts.start_public.fetch',side_effect=fake_fetch),patch('scripts.start_public.tempfile.mkdtemp',return_value=str(work)),patch('scripts.start_public.subprocess.Popen',side_effect=Child),patch('scripts.start_public.ready',side_effect=[False,True]),patch('scripts.start_public.signal.signal',side_effect=register),patch('scripts.start_public.time.sleep',side_effect=tick):
                main()
            self.assertEqual(len(children),2)
            self.assertEqual(children[1].env['RESEARCHGRAPH_RELEASE'],str(bundled.resolve()))
            self.assertTrue(all(c.code==0 for c in children))
