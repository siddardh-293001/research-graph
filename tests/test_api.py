"""Public API contract, bounded requests and safe lookup behavior (offline)."""
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from src.api import create_app


class Engine:
    manifest = dict(papers=20000, run_id='fixture', source_finished_at='2026-10-22T00:00:00Z',
                    topics=[], year_min=2020, year_max=2026, limitations=['fixture'])

    def search(self, **kwargs):
        self.last_search = kwargs
        return [], False

    def paper(self, paper_id):
        return {'paper_id': paper_id} if paper_id == 'https://openalex.org/W1' else None

    def neighborhood(self, paper_id, limit):
        return {'nodes': [], 'edges': []} if paper_id == 'https://openalex.org/W1' else None


class PublicAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine()
        self.temp = tempfile.TemporaryDirectory()
        Path(self.temp.name, 'index.html').write_text('<html>ResearchGraph</html>')
        self.client = TestClient(create_app(lambda: self.engine, self.temp.name))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_status_and_static_app_do_not_disclose_paths(self):
        self.assertEqual(self.client.get('/readyz').json()['papers'], 20000)
        self.assertEqual(self.client.get('/healthz').status_code, 200)
        response = self.client.get('/')
        self.assertIn('ResearchGraph', response.text)
        self.assertIn("default-src 'self'", response.headers['content-security-policy'])
        self.assertNotIn('artifacts', self.client.get('/api/status').json())
        self.assertEqual(self.client.get('/.env').status_code, 404)

    def test_search_forwards_filters_and_returns_empty_state(self):
        response = self.client.post('/api/search', json={'query':'medical retrieval', 'mode':'dense',
                   'year_min':2024, 'year_max':2025, 'topic_ids':[2], 'top_k':5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])
        self.assertEqual(self.engine.last_search['topic_ids'], [2])
        self.assertEqual(self.engine.last_search['year_min'], 2024)

    def test_rejects_invalid_and_unbounded_searches(self):
        for body in [{'query':' '}, {'query':'x'*2001}, {'query':'x','mode':'invented'},
                     {'query':'x','top_k':51}, {'query':'x','top_k':True}, {'query':'x','top_k':'10'},
                     {'query':'x','year_min':2025,'year_max':2020}, {'query':'x','topic_ids':[-1]},
                     {'query':'x','extra':'ignored?'}, {'query':'x','topic_ids':list(range(21))}]:
            with self.subTest(body=str(body)[:100]):
                self.assertEqual(self.client.post('/api/search',json=body).status_code,422)
        self.assertEqual(self.client.post('/api/search',content=b'x'*16385).status_code,413)
        self.assertEqual(self.client.post('/api/search',content='invalid JSON',headers={'Content-Type':'application/json'}).status_code,422)

    def test_paper_ids_are_exact_lookups_and_graph_is_bounded(self):
        self.assertEqual(self.client.get('/api/paper',params={'paper_id':'https://openalex.org/W1'}).status_code,200)
        for paper_id in ["' OR 1=1 --",'../../.env','missing']:
            self.assertEqual(self.client.get('/api/paper',params={'paper_id':paper_id}).status_code,404)
        self.assertEqual(self.client.get('/api/graph',params={'paper_id':'https://openalex.org/W1','limit':31}).status_code,422)
        self.assertEqual(self.client.get('/api/graph',params={'paper_id':'missing'}).status_code,404)

    def test_demo_limit_keeps_health_available(self):
        with TestClient(create_app(lambda: Engine(), self.temp.name, requests_per_minute=1)) as client:
            self.assertEqual(client.post('/api/search',json={'query':'one'}).status_code,200)
            response = client.post('/api/search',json={'query':'two'})
            self.assertEqual(response.status_code,429)
            self.assertEqual(response.headers['retry-after'],'60')
            self.assertEqual(client.get('/healthz').status_code,200)

    def test_openapi_documents_search_and_filters(self):
        schema = self.client.get('/api/openapi.json').json()
        self.assertIn('/api/search',schema['paths'])
        self.assertEqual(schema['components']['schemas']['SearchRequest']['properties']['top_k']['maximum'],50)


if __name__ == '__main__':
    unittest.main()
