import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const EXAMPLES = ['Graph retrieval for multi-hop reasoning', 'Clinical question answering with language models', 'Evaluating hallucinations in retrieval augmented generation'];
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    if (response.status === 429) throw new Error('The demo is receiving many searches. Please try again in a minute.');
    if (response.status === 503) throw new Error('Search is starting or busy. Please try again shortly.');
    throw new Error(response.status === 404 ? 'This paper could not be found.' : 'The request could not be completed. Please try again.');
  }
  return response.json();
}
function safeDoi(value) {
  if (typeof value !== 'string') return null;
  const doi = value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '');
  return /^10\.\d{4,9}\//.test(doi) ? 'https://doi.org/' + encodeURI(doi) : null;
}
function Neighbors({ paper, onSelect }) {
  const [data, setData] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setData(null); setError('');
    api('/api/graph?paper_id='+encodeURIComponent(paper.paper_id)+'&limit=12', {signal: controller.signal})
      .then(setData).catch(e => {if (e.name !== 'AbortError') setError(e.message);});
    return () => controller.abort();
  }, [paper.paper_id]);
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <p role="status">Loading semantic neighbors…</p>;
  const count = data.nodes.length-1;
  const point = i => ({x: 210+Math.cos(i/Math.max(count,1)*Math.PI*2)*145, y: 180+Math.sin(i/Math.max(count,1)*Math.PI*2)*130});
  return <section className="neighbors"><h3>Nearby research</h3><p>Connections reflect abstract similarity.</p>
    <svg viewBox="0 0 420 360" role="img" aria-label="Semantic neighborhood of selected paper">
      {data.edges.map((edge,i) => <line key={edge.target} x1="210" y1="180" x2={point(i).x} y2={point(i).y}/>)}
      <circle cx="210" cy="180" r="13" className="center"/><text x="210" y="208" textAnchor="middle">Selected paper</text>
      {data.nodes.slice(1).map((n,i) => <g key={n.paper_id}><circle cx={point(i).x} cy={point(i).y} r="8"><title>{n.title}</title></circle><text x={point(i).x} y={point(i).y-15} textAnchor="middle">{i+1}</text></g>)}
    </svg>
    <ol>{data.nodes.slice(1).map(n => <li key={n.paper_id}><button onClick={() => onSelect(n.paper_id)}>{n.title}</button></li>)}</ol>
    {!count && <p>No semantic neighbors are available.</p>}
  </section>;
}
function App() {
  const [status, setStatus] = useState(null), [query, setQuery] = useState(''), [mode, setMode] = useState('hybrid');
  const [yearMin, setYearMin] = useState(''), [yearMax, setYearMax] = useState(''), [topic, setTopic] = useState('');
  const [result, setResult] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [paper, setPaper] = useState(null), [detailError, setDetailError] = useState('');
  const searchController = useRef(null), detailController = useRef(null), detailRef = useRef(null);
  useEffect(() => {api('/api/status').then(setStatus).catch(e => setError(e.message)); return () => {searchController.current?.abort(); detailController.current?.abort();};}, []);
  async function search(text = query) {
    if (!text.trim()) return;
    if (yearMin && yearMax && Number(yearMin)>Number(yearMax)) {setError('Choose an earliest year no later than the latest year.');return;}
    searchController.current?.abort(); const controller = new AbortController(); searchController.current = controller;
    detailController.current?.abort(); setDetailError('');
    setQuery(text); setBusy(true); setError(''); setResult(null); setPaper(null);
    try {
      const data = await api('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({query:text, mode, top_k:20, year_min:yearMin?Number(yearMin):null, year_max:yearMax?Number(yearMax):null, topic_ids:topic?[Number(topic)]:null})});
      setResult(data);
    } catch(e) {if (e.name!=='AbortError') setError(e.message);} finally {if (!controller.signal.aborted) setBusy(false);}
  }
  async function select(id) {
    detailController.current?.abort(); const controller = new AbortController(); detailController.current=controller; setDetailError('');
    try {const data=await api('/api/paper?paper_id='+encodeURIComponent(id), {signal:controller.signal}); if (controller.signal.aborted) return; setPaper(data); requestAnimationFrame(() => detailRef.current?.focus());}
    catch(e) {if(e.name!=='AbortError') setDetailError(e.message);}
  }
  function clear() {searchController.current?.abort(); detailController.current?.abort(); setBusy(false);setQuery('');setResult(null);setPaper(null);setError('');setDetailError('');setYearMin('');setYearMax('');setTopic('');}
  return <><header><a href="/" className="brand"><span className="brand-mark">◈</span> ResearchGraph</a><nav><a href="#about">About the corpus</a><a href="/api/docs">API</a></nav></header>
    <main><section className="intro"><p className="eyebrow">A CONNECTED VIEW OF AI RESEARCH</p><h1>Follow an idea.<br/><span>Find its connections.</span></h1><p className="lead">Explore papers through language, research topics, and the work around them.</p>
    <div className="corpus-line"><span className="dot"/>{status?`${status.papers.toLocaleString()} papers · frozen OpenAlex snapshot`:'Connecting to the research atlas…'}</div></section>
    <section className="search-panel" aria-label="Search papers"><form onSubmit={e => {e.preventDefault();search();}}>
      <label htmlFor="query">What are you researching?</label><div className="query-row"><input id="query" value={query} onChange={e => setQuery(e.target.value)} maxLength={2000} required placeholder="e.g. Graph retrieval for multi-hop reasoning"/><button className="primary" type="submit" disabled={busy||!query.trim()}>{busy?'Searching…':'Find papers ↗'}</button></div>
      <div className="filters"><label>Ranking<select value={mode} onChange={e => setMode(e.target.value)}><option value="hybrid">Hybrid</option><option value="bm25">Keyword · BM25</option><option value="dense">Semantic · dense</option></select></label>
        <label>Earliest year<input type="number" min="1900" max="2100" placeholder="Any" value={yearMin} onChange={e => setYearMin(e.target.value)}/></label>
        <label>Latest year<input type="number" min="1900" max="2100" placeholder="Any" value={yearMax} onChange={e => setYearMax(e.target.value)}/></label>
        <label className="topic-filter">Research topic<select value={topic} onChange={e => setTopic(e.target.value)}><option value="">All topics</option>{status?.topics.map(t=><option key={t.topic_id} value={t.topic_id}>{t.name}</option>)}</select></label><button type="button" className="clear" onClick={clear}>Clear</button></div>
    </form><div className="examples"><span>Try an idea</span>{EXAMPLES.map(q=><button key={q} disabled={busy} onClick={()=>search(q)}>{q} ↗</button>)}</div></section>
    {error&&<p role="alert" className="error">{error}</p>}{detailError&&<p role="alert" className="error">{detailError}</p>}
    {busy&&<p role="status" className="search-state">Searching the atlas…</p>}
    {result&&<section className="results" aria-label="Search results"><div className="results-heading"><h2>{result.count?'Papers to explore':'No papers found'}</h2><span>{result.count} results · {result.mode}</span></div>
      {!result.count&&<p>Try a broader query or clear the year and topic filters.</p>}
      <div className="results-layout"><div>{result.results.map((r,i)=><article className="paper-card" key={r.paper_id}><div className="paper-meta"><span>{String(i+1).padStart(2,'0')}</span><span>{r.year}</span><span>{r.citation_count.toLocaleString()} citations</span></div>
        <h3><button onClick={()=>select(r.paper_id)}>{r.title}</button></h3><p>{r.matching_sentence||r.abstract.slice(0,300)}</p><div className="paper-footer"><span className="tag">{r.topic_name}</span><button onClick={()=>select(r.paper_id)}>Paper & connections ↗</button></div>
      </article>)}</div>{paper&&<aside className="detail" ref={detailRef} tabIndex="-1" aria-label="Paper details"><button className="close" aria-label="Close paper details" onClick={()=>{detailController.current?.abort();setPaper(null);}}>×</button><p className="eyebrow">PAPER & CONNECTIONS</p><h2>{paper.title}</h2><p>{paper.year} · {paper.citation_count.toLocaleString()} citations</p><p>{paper.abstract}</p>{safeDoi(paper.doi)&&<a href={safeDoi(paper.doi)} target="_blank" rel="noopener noreferrer">Read at DOI ↗</a>}<Neighbors paper={paper} onSelect={select}/></aside>}</div>
    </section>}
    <section id="about" className="about"><div><p className="eyebrow">ABOUT THIS ATLAS</p><h2>Explore connections.<br/>Keep the context.</h2></div><div><p>This is a selective snapshot of literature on language models, retrieval, and related research, published between 2020 and 2026. The graph connects papers by title and abstract similarity; it does not represent a causal relationship.</p><p>Topic names are generated from leading words. Citation counts reflect this snapshot. Search evaluation uses provisional, incomplete relevance judgments awaiting independent review.</p>{status&&<p className="snapshot">Corpus built {new Date(status.source_finished_at).toLocaleDateString()} · Snapshot {status.run_id}</p>}</div></section>
    </main><footer><span>ResearchGraph · A research project</span><a href="/api/status">Corpus status ↗</a></footer></>;
}
createRoot(document.getElementById('root')).render(<App/>);
