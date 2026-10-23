import sqlite3
import unittest
from src.exploration import browse

class BrowseTests(unittest.TestCase):
    def test_pagination_and_literal_query(self):
        class Engine:
            def connect(self):
                c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
                c.execute('CREATE TABLE papers(paper_id TEXT,title TEXT,abstract TEXT,doi TEXT,year INTEGER,citation_count INTEGER)')
                c.executemany('INSERT INTO papers VALUES(?,?,?,?,?,?)',[(str(i),'100% graph '+str(i),'abstract','doi',2000+i,i) for i in range(25)])
                return c
        e=Engine();a=browse(e,'%',page=1);b=browse(e,'%',page=2)
        self.assertEqual(a['total'],25);self.assertEqual(len(a['results']),20);self.assertEqual(len(b['results']),5)
        self.assertFalse(set(r['paper_id'] for r in a['results'])&set(r['paper_id'] for r in b['results']))
        self.assertEqual(browse(e,"' OR 1=1 --")['total'],0)
        with self.assertRaises(ValueError):browse(e,field='p.title; DROP TABLE papers')
