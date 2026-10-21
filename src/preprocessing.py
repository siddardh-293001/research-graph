"""Deterministic extraction of the legacy notebook's cleaning rules."""
import re
import pandas as pd


def classify_paper(title):
    title = str(title).lower()
    if ('graph rag' in title or 'graph retrieval-augmented' in title
            or ('knowledge graph' in title and 'rag' in title)):
        return 'GRAPH_RAG'
    if ('multimodal rag' in title or 'multimodal retrieval-augmented' in title
            or ('retrieval-augmented' in title and 'image' in title)):
        return 'MULTIMODAL'
    if any(t in title for t in ['agentic rag', 'agent rag', 'adaptive-rag',
        'adaptive rag', 'corrective retrieval augmented', 'self-rag', 'active retrieval augmented']):
        return 'AGENTIC'
    if ('ragas' in title or (('rag' in title or 'retrieval-augmented' in title)
            and any(t in title for t in ['evaluation', 'evaluating', 'benchmark']))):
        return 'EVALUATION'
    if (any(t in title for t in ['retrieval-augmented generation', 'retrieval augmented generation',
        'retrieval-augmented language model', 'retrieval augmented language model']) or ' rag ' in f' {title} '):
        return 'CORE_RAG'
    if any(t in title for t in ['dense retrieval', 'information retrieval', 'passage retrieval',
        'document retrieval', 'neural retrieval', 'retrieval model', 'retrieval system', 'retriever']):
        return 'RETRIEVAL'
    if any(t in title for t in ['large language model', 'llm', 'language model']):
        return 'LLM'
    return 'BACKGROUND'


def clean_metadata(frame):
    required = {'paper_id', 'title', 'abstract', 'year', 'citation_count'}
    if missing := required - set(frame):
        raise ValueError(f'Missing metadata columns: {sorted(missing)}')
    frame = frame.copy()
    if frame.paper_id.isna().any() or frame.paper_id.duplicated().any():
        raise ValueError('Input paper IDs must be present and unique')
    frame = frame[frame.title.fillna('').str.strip().ne('')].copy()
    frame['paper_category'] = frame.title.map(classify_paper)
    frame['abstract_length'] = frame.abstract.fillna('').str.split().str.len()
    frame['title_normalized'] = frame.title.str.lower().str.replace(r'[^a-z0-9]+', ' ', regex=True).str.strip()
    # Baseline compatibility only: v3 identity dedup is separate from this legacy rule.
    return (frame.sort_values(['title_normalized', 'citation_count', 'year', 'paper_id'],
                             ascending=[True, False, False, True], kind='stable')
            .drop_duplicates('title_normalized').reset_index(drop=True))


def prepare_embedding_corpus(clean):
    result = clean[clean.abstract.fillna('').str.strip().ne('')].copy().reset_index(drop=True)
    if result.empty:
        raise ValueError('No papers with abstracts remain')
    result['text_for_embedding'] = result.title.fillna('') + '. ' + result.abstract.fillna('')
    return result


def clean_nlp_text(text):
    return re.sub(r'\s+', ' ', re.sub(r'\b(19|20)\d{2}\b', ' ', text)).strip()
