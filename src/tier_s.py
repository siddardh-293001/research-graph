"""Build the bounded Tier S corpus from a checksummed source snapshot."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
from pathlib import Path
import uuid
import numpy as np
import pandas as pd
import yaml
from src.pipeline import ROOT, sha256
from src.ingestion.snapshot import iter_snapshot, atomic_json
from src.ingestion.openalex import normalize_paper
from src.corpus import coalesce_metadata
from src.preprocessing import classify_paper, clean_nlp_text
from src.search import load_encoder
from src.ann import CosineHNSW, recall_checks, ann_graph_edges, normalized_vectors
from src.artifacts import resolve_run
from src.baseline_methods import fit_topics, integrate_analysis
from src.research_graph import graph_from_edges, leiden_partition, graph_metrics, citation_edges
from src.audit import audit_frames


def curate(raw_records, seed_frame, config):
    seeds=json.loads(seed_frame.to_json(orient='records'))
    for row in seeds:
        for field in ['arxiv_id','updated_date','is_retracted','doi']:row.setdefault(field,None)
    preferred=[r['paper_id'] for r in seeds if isinstance(r.get('abstract'),str) and r['abstract'].strip()]
    rejected=Counter(); valid=[]
    for raw in raw_records:
        row=normalize_paper(raw)
        reason=None
        if not row.get('paper_id') or not row.get('title'):reason='missing_identity_or_title'
        elif row['is_retracted']:reason='retracted'
        elif not isinstance(row['year'],int) or not 2020<=row['year']<=2026:reason='year'
        elif not isinstance(row['citation_count'],(int,float)) or not np.isfinite(row['citation_count']) or row['citation_count']<0:reason='citations'
        elif len((row.get('abstract') or '').split())<config['source']['min_abstract_words']:reason='short_or_missing_abstract'
        if reason:rejected[reason]+=1
        else:valid.append(row)
    merged,aliases=coalesce_metadata(seeds+valid,preferred)
    usable=[r for r in merged if isinstance(r.get('abstract'),str) and r['abstract'].strip() and r.get('title')]
    seed_ids={aliases.get(p,p) for p in preferred}
    usable.sort(key=lambda r:(r['paper_id'] not in seed_ids,-int(r.get('citation_count') or 0),r['paper_id']))
    selected=usable[:config['target_papers']]
    if len(seed_ids)>config['target_papers']:raise ValueError('Target cannot retain the benchmark seed corpus')
    frame=pd.DataFrame(selected).sort_values('paper_id').reset_index(drop=True)
    frame['text_for_embedding']=frame.title+'. '+frame.abstract
    frame['paper_category']=frame.title.map(classify_paper)
    frame['abstract_length']=frame.abstract.str.split().str.len()
    frame['year']=frame.year.astype(int);frame['citation_count']=frame.citation_count.astype(int)
    coverage={'seed_records':len(seeds),'raw_records':len(valid)+sum(rejected.values()),'accepted_raw_records':len(valid),
        'rejected_raw_records':dict(rejected),'identity_groups':len(merged),'usable_groups':len(usable),
        'selected_papers':len(frame),'target_papers':config['target_papers'],'seed_identities_retained':len(set(frame.paper_id)&seed_ids),
        'seed_usable_identities':len(seed_ids),'year_counts':{str(k):int(v) for k,v in frame.year.value_counts().sort_index().items()},
        'fresh_source_metadata_fraction':float(frame.updated_date.notna().mean()),
        'retraction_status_unknown':int(frame.is_retracted.isna().sum()),
        'doi_fraction':float(frame.doi.notna().mean()),'arxiv_fraction':float(frame.arxiv_id.notna().mean()),
        'abstract_fraction':float(frame.abstract.str.strip().ne('').mean()),
        'reference_fraction':float(frame.referenced_works.map(len).gt(0).mean()),
        'selection':'All usable baseline identities, then citation-descending matching source records; not a random sample.'}
    return frame,aliases,coverage


def cached_embeddings(papers, config, seed, encoder=None):
    cache=ROOT/config['cache'];cache.mkdir(parents=True,exist_ok=True)
    prefix=json.dumps({k:config[k] for k in ['model','revision','normalize']},sort_keys=True)
    keys=[hashlib.sha256((prefix+'\n'+t).encode()).hexdigest() for t in papers.text_for_embedding]
    vectors={};missing=[]
    for i,key in enumerate(keys):
        path=cache/(key+'.npy')
        if path.exists():
            value=np.load(path,allow_pickle=False)
            if value.shape!=(384,) or not np.isfinite(value).all() or not np.isclose(np.linalg.norm(value),1,atol=1e-4):
                raise ValueError('Invalid cached embedding')
            vectors[i]=value
        else:missing.append(i)
    # Seed the content-addressed cache only when both the model and text match.
    try:
        directory,manifest=resolve_run()
        if all(manifest['config']['embedding'].get(k)==config[k] for k in ['model','revision','normalize']):
            old=pd.read_parquet(directory/'embedded_papers.parquet');old_x=np.load(directory/'paper_embeddings.npy',allow_pickle=False)
            known={t:x for t,x in zip(old.text_for_embedding,old_x)}
            for i in list(missing):
                if papers.text_for_embedding.iloc[i] in known:
                    value=known[papers.text_for_embedding.iloc[i]]
                    vectors[i]=value;np.save(cache/(keys[i]+'.npy'),value,allow_pickle=False)
            missing=[i for i in missing if i not in vectors]
    except (FileNotFoundError,ValueError):pass
    print(f'Embedding cache: {len(vectors)} hits; {len(missing)} papers to encode',flush=True)
    encoder=encoder or load_encoder(config,seed)
    for start in range(0,len(missing),config['batch_size']):
        indices=missing[start:start+config['batch_size']]
        values=encoder.encode(papers.text_for_embedding.iloc[indices].tolist(),normalize_embeddings=True,convert_to_numpy=True)
        values=normalized_vectors(values)
        for i,value in zip(indices,values):
            path=cache/(keys[i]+'.npy');temporary=cache/(keys[i]+'.tmp.npy')
            np.save(temporary,value,allow_pickle=False);temporary.replace(path);vectors[i]=value
        if start%512==0:print(f'Encoded {min(start+len(indices),len(missing))}/{len(missing)} new papers',flush=True)
    return np.stack([vectors[i] for i in range(len(papers))]),keys,encoder


def effective_benchmark(aliases,known):
    benchmark=json.loads((ROOT/'data/benchmark/queries.json').read_text())
    mapped=0
    for query in benchmark['queries']:
        grades={}
        for judgment in query['judgments']:
            paper=aliases.get(judgment['paper_id'],judgment['paper_id'])
            if paper not in known:raise ValueError('Benchmark identity lost during curation')
            mapped+=paper!=judgment['paper_id'];grades[paper]=max(grades.get(paper,0),judgment['grade'])
        query['judgments']=[{'paper_id':p,'grade':g} for p,g in grades.items()]
    benchmark['identity_mapping']={'mapped_judgments':mapped,'original_sha256':sha256(ROOT/'data/benchmark/queries.json')}
    return benchmark


def run(snapshot, config_path=None, output_root=None):
    config_path=Path(config_path or ROOT/'config/tier_s.yaml')
    config=yaml.safe_load(config_path.read_text());snapshot=Path(snapshot).resolve()
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output=Path(output_root or ROOT/config['output_root'])/run_id;output.mkdir(parents=True)
    manifest={'run_id':run_id,'kind':'tier_s','status':'running','config':config,'started_at':datetime.now(timezone.utc).isoformat(),
        'source_snapshot':str(snapshot),'source_manifest_sha256':sha256(snapshot/'manifest.json'),
        'seed_metadata_sha256':sha256(ROOT/config['seed_metadata']),
        'code_sha256':{str(p.relative_to(ROOT)):sha256(p) for p in sorted((ROOT/'src').rglob('*.py'))},
        'packages':{p:version(p) for p in ['faiss-cpu','numpy','pandas','sentence-transformers','torch','scikit-learn','igraph','leidenalg']}}
    atomic_json(output/'manifest.json',manifest)
    try:
        papers,aliases,coverage=curate(iter_snapshot(snapshot),pd.read_parquet(ROOT/config['seed_metadata']),config)
        if len(papers)<config['target_papers'] or len(papers)>config['max_papers']:raise ValueError(f'Corpus size gate failed: {len(papers)}')
        print(f'Curated {len(papers)} papers; encoding',flush=True)
        papers.to_parquet(output/'embedded_papers.parquet',index=False)
        atomic_json(output/'coverage.json',coverage)
        pd.DataFrame(sorted(aliases.items()),columns=['source_id','canonical_id']).to_parquet(output/'identity_aliases.parquet',index=False)
        embeddings,keys,encoder=cached_embeddings(papers,config['embedding'],config['seed'])
        np.save(output/'paper_embeddings.npy',embeddings,allow_pickle=False)
        np.save(output/'embedded_paper_ids_safe.npy',papers.paper_id.to_numpy(dtype=str),allow_pickle=False)
        atomic_json(output/'embedding_keys.json',keys)
        benchmark=effective_benchmark(aliases,set(papers.paper_id));atomic_json(output/'benchmark_effective.json',benchmark)
        print('Building HNSW and checking against exact cosine retrieval',flush=True)
        ann_config=config['ann'];index=CosineHNSW(embeddings,**{k:ann_config[k] for k in ['m','ef_construction','ef_search']},seed=config['seed'])
        index.save(output/'search_hnsw.faiss')
        probes=np.sort(np.random.default_rng(config['seed']).choice(len(papers),min(len(papers),ann_config['evaluation_queries']),replace=False))
        queries=encoder.encode([q['query'] for q in benchmark['queries']],normalize_embeddings=True,convert_to_numpy=True)
        np.save(output/'benchmark_query_vectors.npy',queries,allow_pickle=False)
        checks={'document_probes':recall_checks(index,embeddings,embeddings[probes],excluded_ids=probes,ef_values=ann_config['evaluation_ef_values']),
            'benchmark_queries':recall_checks(index,embeddings,queries,ef_values=ann_config['evaluation_ef_values']),
            'probe_rows':probes.tolist(),'build_seconds':index.build_seconds,'index_bytes':(output/'search_hnsw.faiss').stat().st_size,
            'latency_scope':'Single-thread index search only; excludes encoder, BM25, result formatting and HTTP.'}
        atomic_json(output/'ann_checks.json',checks)
        accuracy=all(next(r for r in checks[key] if r['ef_search']==ann_config['ef_search'])['recall_at_10']>=ann_config['recall_target'] for key in ['document_probes','benchmark_queries'])
        if not accuracy:raise ValueError('ANN recall gate failed')
        print('Fitting sampled NMF topics and sparse ANN graph',flush=True)
        # Year-stratified deterministic sample; only the fitted vocabulary/model are reused for transform.
        sample=(papers.groupby('year',group_keys=False).sample(frac=min(1,config['topics']['fit_sample']/len(papers)),random_state=config['seed']).sort_index())
        topic_config={**config['topics'],'labels':{}}
        _,vectorizer,model,terms=fit_topics(sample,topic_config,config['seed'])
        weights=model.transform(vectorizer.transform(papers.text_for_embedding.map(clean_nlp_text)))
        topics=papers[['paper_id','title','year','citation_count']].copy()
        topics['topic_id']=np.where(weights.sum(axis=1)>0,weights.argmax(axis=1)+1,0)
        names={t['topic_id']:', '.join(t['top_terms'][:3]) for t in terms};names[0]='Unassigned'
        topics['topic_name']=topics.topic_id.map(names)
        atomic_json(output/'topic_terms.json',terms)
        atomic_json(output/'topic_fit_ids.json',sample.paper_id.tolist())
        np.savez_compressed(output/'topic_model.npz',components=model.components_,idf=vectorizer.idf_)
        atomic_json(output/'topic_vocabulary.json',{k:int(v) for k,v in vectorizer.vocabulary_.items()})
        edges,near=ann_graph_edges(index,embeddings,ann_config['graph_k'])
        graph=graph_from_edges(len(papers),edges)
        labels=leiden_partition(graph,seed=config['seed'],**config['leiden'])
        metrics,method=graph_metrics(graph,seed=config['seed'],sample_size=64)
        nodes=papers[['paper_id','title','year','citation_count']].copy();nodes.insert(0,'node',range(len(papers)))
        nodes['community']=labels
        for key,values in metrics.items():nodes[key]=[values[i] for i in range(len(papers))]
        edge_frame=pd.DataFrame([(papers.paper_id.iloc[i],papers.paper_id.iloc[j],w) for i,j,w in edges],columns=['source','target','weight'])
        analysis=integrate_analysis(papers,topics,nodes)
        audit=audit_frames(papers,embeddings,papers.paper_id.to_numpy(dtype=str),analysis)
        if not audit['passed']:raise ValueError(audit['errors'])
        for name,table in [('graph_nodes',nodes),('graph_edges',edge_frame),('nlp_topic_assignments',topics),('research_analysis_dataset',analysis)]:table.to_parquet(output/(name+'.parquet'),index=False)
        pd.DataFrame([(papers.paper_id.iloc[i],papers.paper_id.iloc[j],w) for i,j,w in near],columns=['source','target','cosine']).to_parquet(output/'near_duplicate_candidates.parquet',index=False)
        citation,reference_coverage=citation_edges(papers)
        pd.DataFrame([(papers.paper_id.iloc[i],papers.paper_id.iloc[j]) for i,j in citation],columns=['source','target']).to_parquet(output/'citation_edges.parquet',index=False)
        atomic_json(output/'audit.json',audit)
        atomic_json(output/'graph_method.json',{**method,'graph':'positive cosine ANN union kNN','k':ann_config['graph_k'],'leiden':config['leiden'],'seed':config['seed'],'reference_coverage':reference_coverage,
            'near_duplicate_policy':'Cosine >=0.99 candidates in graph neighbors; retained, not identity evidence or exhaustive duplicate search.',
            'citation_display':'Relative citations use the legacy citation_count/(year median +1); descriptive, not field-normalized impact.'})
        manifest.update(status='complete',finished_at=datetime.now(timezone.utc).isoformat(),counts={'papers':len(papers),'edges':len(edges),'communities':int(nodes.community.nunique()),'nmf_components':config['topics']['count'],
                'topic_fit_papers':len(sample),'occupied_topic_labels':int(topics.topic_id.nunique()),
                'near_duplicate_candidate_pairs':len(near),'internal_citation_edges':len(citation)},
            gates={'target_size':True,'ann_recall':accuracy,'aligned_artifacts':True},artifacts={p.name:sha256(p) for p in sorted(output.iterdir()) if p.name!='manifest.json'})
    except Exception as exc:
        manifest.update(status='failed',error=f'{type(exc).__name__}: {exc}');raise
    finally:atomic_json(output/'manifest.json',manifest)
    print(f'Completed Tier S: {output}',flush=True)
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot',type=Path,default=ROOT/'data/raw/tier_s_openalex');parser.add_argument('--config',type=Path);parser.add_argument('--output-root',type=Path)
    args=parser.parse_args();run(args.snapshot,args.config,args.output_root)
