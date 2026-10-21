"""Shared identity handling for batch and future incremental ingestion."""

def canonical_doi(value):
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/', 'doi:'):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    return value or None


def deduplicate_papers(records):
    """Group by paper ID or DOI, including transitive matches; keep first input.

    Missing identifiers never match each other. Titles alone do not establish
    identity. Metadata merging and arXiv version matching are later work.
    """
    records = list(records)
    parents = list(range(len(records)))
    seen = {}

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    for i, paper in enumerate(records):
        paper_id = paper.get('paper_id')
        keys = [('doi', canonical_doi(paper.get('doi')))]
        keys.append(('paper_id', paper_id.strip() if isinstance(paper_id, str) else None))
        for kind, value in keys:
            if not value:
                continue
            key = (kind, value)
            if key in seen:
                a, b = root(i), root(seen[key])
                parents[max(a, b)] = min(a, b)
            seen[key] = i
    return [paper for i, paper in enumerate(records) if root(i) == i]


def canonical_arxiv(value):
    """Canonical arXiv identifier, stripping a version only on recognized IDs."""
    import re
    from urllib.parse import unquote
    if not isinstance(value,str):return None
    value=unquote(value.strip()).lower()
    value=re.sub(r'^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/','',value)
    value=re.sub(r'^(?:arxiv:|https?://doi\.org/10\.48550/arxiv\.|10\.48550/arxiv\.)','',value)
    value=value.split('?',1)[0].split('#',1)[0].removesuffix('.pdf')
    match=re.fullmatch(r'(\d{4}\.\d{4,5}|[a-z][a-z.-]*(?:\.[a-z]{2})?/\d{7})(?:v\d+)?',value)
    return match.group(1) if match else None


def arxiv_from_work(work):
    candidates=[work.get('arxiv_id'),work.get('doi'),work.get('pdf_url')]
    ids=work.get('ids') or {}
    candidates.append(ids.get('arxiv'))
    locations=list(work.get('locations') or [])+[work.get('primary_location') or {},work.get('best_oa_location') or {}]
    for location in locations:
        candidates.extend([location.get('landing_page_url'),location.get('pdf_url')])
    return next((value for item in candidates if (value:=canonical_arxiv(item))),None)


def coalesce_metadata(records, preferred_ids=()):
    """Transitive DOI/arXiv/ID identity with stable seed IDs and citation aliases.

    Latest metadata wins, while the longest nonempty abstract is retained.
    Title similarity is not identity. Reference lists are unioned and remapped.
    """
    records=[dict(r) for r in records]
    parent=list(range(len(records)))
    seen={}
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,row in enumerate(records):
        for kind,value in [('id',row.get('paper_id')),('doi',canonical_doi(row.get('doi'))),
                           ('arxiv',canonical_arxiv(row.get('arxiv_id')) or canonical_arxiv(row.get('doi')) or canonical_arxiv(row.get('pdf_url')))]:
            if not isinstance(value,str) or not value.strip():continue
            key=(kind,value.strip())
            if key in seen:
                a,b=root(i),root(seen[key]);parent[max(a,b)]=min(a,b)
            seen[key]=i
    groups={}
    for i,row in enumerate(records):groups.setdefault(root(i),[]).append(row)
    preferred={paper:i for i,paper in enumerate(preferred_ids)}
    merged=[];aliases={}
    for group in groups.values():
        identifiers=sorted({r['paper_id'] for r in group if isinstance(r.get('paper_id'),str) and r['paper_id'].strip()})
        if not identifiers:continue
        canonical=min(identifiers,key=lambda p:(preferred.get(p,len(preferred)),p))
        latest=sorted(group,key=lambda r:(str(r.get('updated_date') or ''),len(str(r.get('abstract') or '')),
                                           int(r.get('citation_count') or 0),str(r.get('paper_id'))),reverse=True)
        row=dict(latest[0]);row['paper_id']=canonical
        abstracts=[r['abstract'] for r in latest if isinstance(r.get('abstract'),str) and r['abstract'].strip()]
        row['abstract']=max(abstracts,key=len) if abstracts else None
        for field in ['authors','institutions','topics','keywords','title','doi','arxiv_id','publication_date','year']:
            if row.get(field) is None or (isinstance(row.get(field),(str,list)) and len(row[field])==0):
                row[field]=next((r[field] for r in latest if r.get(field) is not None and not (isinstance(r[field],(str,list)) and len(r[field])==0)),None)
        row['referenced_works']=sorted({p for r in group for p in (r.get('referenced_works') or [])})
        row['identity_aliases']=identifiers
        row['merged_record_count']=len(group)
        merged.append(row)
        aliases.update({p:canonical for p in identifiers})
    for row in merged:
        row['referenced_works']=sorted({aliases.get(p,p) for p in row['referenced_works'] if aliases.get(p,p)!=row['paper_id']})
    merged.sort(key=lambda r:(preferred.get(r['paper_id'],len(preferred)),r['paper_id']))
    return merged,aliases
