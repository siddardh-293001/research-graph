import unittest
import numpy as np
import pandas as pd
from src.audit import audit_frames
from src.corpus import canonical_doi, deduplicate_papers


class IdentityTests(unittest.TestCase):
    def test_doi_normalization(self):
        self.assertEqual(canonical_doi(' HTTPS://DOI.ORG/10.123/ABC '), '10.123/abc')
        self.assertIsNone(canonical_doi(float('nan')))

    def test_transitive_duplicates_keep_first(self):
        papers = [dict(paper_id='A'), dict(paper_id='B', doi='10.1/x'),
                  dict(paper_id='A', doi='https://doi.org/10.1/X')]
        self.assertEqual(deduplicate_papers(papers), papers[:1])

    def test_missing_identifiers_and_shared_titles_do_not_merge(self):
        papers = [dict(title='same'), dict(title='same')]
        self.assertEqual(len(deduplicate_papers(papers)), 2)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.corpus = pd.DataFrame(dict(paper_id=['A', 'B'], title=['a', 'b'],
            abstract=['text', 'text'], year=[2023, 2024], citation_count=[0, 1]))
        self.embeddings = np.eye(2)
        self.ids = np.array(['A', 'B'])

    def audit(self, **changes):
        args = dict(corpus=self.corpus, embeddings=self.embeddings,
                    embedding_ids=self.ids, analysis=self.corpus)
        args.update(changes)
        return audit_frames(**args)

    def test_valid_corpus(self):
        self.assertTrue(self.audit()['passed'])

    def test_shuffled_embeddings_rejected(self):
        self.assertFalse(self.audit(embedding_ids=self.ids[::-1])['passed'])

    def test_analysis_order_rejected(self):
        self.assertFalse(self.audit(analysis=self.corpus.iloc[::-1])['passed'])

    def test_bad_vectors_rejected(self):
        for vectors in (np.zeros((2, 2)), np.array([[np.nan, 0], [0, 1]]), np.eye(3)):
            self.assertFalse(self.audit(embeddings=vectors)['passed'])

    def test_missing_schema_rejected(self):
        self.assertFalse(self.audit(corpus=self.corpus.drop(columns='title'))['passed'])

    def test_invalid_years_and_infinite_citations_rejected(self):
        invalid = self.corpus.copy()
        invalid['year'] = [2020.5, float('nan')]
        self.assertFalse(self.audit(corpus=invalid)['passed'])
        invalid = self.corpus.copy()
        invalid['citation_count'] = [0., float('inf')]
        self.assertFalse(self.audit(corpus=invalid)['passed'])

    def test_short_text_is_reported_without_rewriting_the_corpus(self):
        report = self.audit()
        self.assertTrue(report['passed'])
        self.assertEqual(report['short_abstracts_under_30_words'], 2)


if __name__ == '__main__':
    unittest.main()
