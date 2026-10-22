"""Grounded, deterministic paper insights from abstract and frozen metadata."""
import re
from collections import Counter


def summarize(title, abstract):
    """Extract original sentences, never invent results or imply full-text access."""
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', abstract or '') if s.strip()]
    if not sentences:
        return {'method': 'extractive_abstract', 'sentences': [], 'scope': 'No abstract available.'}
    terms = set(re.findall(r'\b[a-z]{4,}\b', (title or '').lower()))
    cues = re.compile(r'\b(propos\w*|introduc\w*|present\w*|evaluat\w*|result\w*|demonstrat\w*|achiev\w*|findings|conclud\w*)\b', re.I)
    ranked = sorted(range(len(sentences)), key=lambda i: (-(len(terms & set(re.findall(r'\b[a-z]{4,}\b', sentences[i].lower()))) + 2*bool(cues.search(sentences[i]))), i))
    selected = sorted(set([0] + ranked[:2]))[:3]
    return {'method': 'extractive_abstract', 'sentences': [sentences[i] for i in selected],
            'scope': 'Selected sentences from the abstract. Full text has not been reviewed; findings are the authors’ claims.'}


def overlap_terms(left, right, stopwords=()):
    def terms(text):
        return Counter(t for t in re.findall(r'\b[a-z][a-z-]{3,}\b', text.lower()) if t not in stopwords)
    a, b = terms(left), terms(right)
    return sorted(a.keys() & b.keys(), key=lambda t: (-(a[t]+b[t]), t))[:6]
