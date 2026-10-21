import importlib
import unittest
from unittest.mock import patch
from src.ingestion.openalex import normalize_paper, reconstruct_abstract, search_openalex


class IngestionTests(unittest.TestCase):
    def test_abstract_positions_and_missing_abstract(self):
        self.assertEqual(reconstruct_abstract({'world': [1], 'hello': [0]}), 'hello world')
        self.assertIsNone(reconstruct_abstract(None))

    def test_normalization_keeps_reference_ids(self):
        record = normalize_paper({'id': 'W1', 'title': 'Test', 'referenced_works': ['W2'],
                                   'open_access': None})
        self.assertEqual(record['paper_id'], 'W1')
        self.assertEqual(record['referenced_works'], ['W2'])
        self.assertIsNone(record['abstract'])

    def test_collection_uses_timeout_and_propagates_http_errors(self):
        with patch('src.ingestion.openalex.requests.get') as get:
            get.return_value.raise_for_status.side_effect = RuntimeError('HTTP failure')
            with self.assertRaisesRegex(RuntimeError, 'HTTP failure'):
                search_openalex('test')
            self.assertEqual(get.call_args.kwargs['timeout'], 30)

    def test_manual_probe_has_no_import_side_effects(self):
        with patch('requests.get') as get:
            importlib.reload(importlib.import_module('src.ingestion.test_openalex'))
            get.assert_not_called()
