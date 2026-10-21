import json
from pathlib import Path
import tempfile
import unittest
from src.artifacts import resolve_run


class ArtifactTests(unittest.TestCase):
    def test_unfinished_and_tampered_runs_are_not_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            manifest = directory/'manifest.json'
            manifest.write_text(json.dumps({'status':'failed'}))
            with self.assertRaisesRegex(ValueError, 'completed'):
                resolve_run(directory)
            (directory/'embedded_papers.parquet').write_bytes(b'tampered')
            manifest.write_text(json.dumps({'status':'complete', 'artifacts':{
                'embedded_papers.parquet':'invalidhash'}}))
            with self.assertRaisesRegex(ValueError, 'integrity'):
                resolve_run(directory)
