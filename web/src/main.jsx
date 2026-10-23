import React, { useState, useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import {PaperTools,Library,readSaved} from './ResearchTools.jsx';
import PaperInsights from './PaperInsights.jsx';

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
  return <section className="neighbors"><h3>Nearby research</h3><p>Related by title and abstract similarity. Shared terms explain overlap; similarity is not evidence of a citation.</p>
    <svg viewBox="0 0 420 360" role="img" aria-label="Semantic neighborhood of selected paper">
      {data.edges.map((edge,i) => <line key={edge.target} x1="210" y1="180" x2={point(i).x} y2={point(i).y}/>)}
      <circle cx="210" cy="180" r="13" className="center"/><text x="210" y="208" textAnchor="middle">Selected paper</text>
      {data.nodes.slice(1).map((n,i) => <g key={n.paper_id}><circle cx={point(i).x} cy={point(i).y} r="8"><title>{n.title}</title></circle><text x={point(i).x} y={point(i).y-15} textAnchor="middle">{i+1}</text></g>)}
    </svg>
    <ol>{data.nodes.slice(1).map(n => <li key={n.paper_id}><button onClick={() => onSelect(n.paper_id)}>{n.title}</button><small>{Math.round((data.edges.find(e=>e.target===n.paper_id)?.weight||0)*100)}% cosine similarity · {n.citation_count_available===0?'Citation count unavailable':n.citation_count?.toLocaleString()+' citations'}</small><p className="connection-reason">Shared terms: {n.shared_terms?.join(', ')||'No distinctive lexical overlap'}. {n.same_community?'Same semantic community.':'Connects different semantic communities.'} {n.citation_direction==='cites'?'This paper references it.':n.citation_direction==='cited_by'?'It cites this paper.':n.citation_direction==='both'?'Mutual citation links.':''}</p></li>)}</ol>
    {!count && <p>No semantic neighbors are available.</p>}
  </section>;
}
function App() {
  const [saved,setSaved]=useState(readSaved),[showLibrary,setShowLibrary]=useState(false);
  const [theme,setTheme]=useState(()=>{try{return localStorage.getItem('rg-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');}catch{return 'light';}});
  useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('rg-theme',theme);}catch{}},[theme]);

  const [route,setRoute]=useState(location.hash);
  useEffect(()=>{const change=()=>{setRoute(location.hash);window.scrollTo(0,0);};window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
  const paperRoute=route.startsWith('#paper=');
  const home=!paperRoute && route!=='#search';
  useEffect(()=>{if(paperRoute) loadPaper(decodeURIComponent(route.slice(7)));else {detailController.current?.abort();setPaper(null);}},[route]);
  const [status, setStatus] = useState(null), [query, setQuery] = useState(''), [mode, setMode] = useState('hybrid');
  const [yearMin, setYearMin] = useState(''), [yearMax, setYearMax] = useState(''), [topic, setTopic] = useState('');
  const [researchTopic,setResearchTopic]=useState(''), [topicSearch,setTopicSearch]=useState(''), [feed,setFeed]=useState(null);
  useEffect(()=>{const c=new AbortController();api('/api/feed?limit=6',{signal:c.signal}).then(setFeed).catch(()=>{});return ()=>c.abort();},[]);
  const [result, setResult] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState(''), [paper, setPaper] = useState(null), [detailError, setDetailError] = useState('');
  const searchController = useRef(null), detailController = useRef(null), detailRef = useRef(null);
  useEffect(() => {api('/api/status').then(setStatus).catch(e => setError(e.message)); return () => {searchController.current?.abort(); detailController.current?.abort();};}, []);
  async function search(text = query, theme = researchTopic) {
    if (!text.trim()) return;
    if (yearMin && yearMax && Number(yearMin)>Number(yearMax)) {setError('Choose an earliest year no later than the latest year.');return;}
    searchController.current?.abort(); const controller = new AbortController(); searchController.current = controller;
    detailController.current?.abort(); setDetailError('');
    location.hash='search'; setQuery(text); setBusy(true); setError(''); setResult(null); setPaper(null);
    try {
      const data = await api('/api/search', {method:'POST', headers:{'Content-Type':'application/json'}, signal:controller.signal,
        body:JSON.stringify({query:text, mode, top_k:20, year_min:yearMin?Number(yearMin):null, year_max:yearMax?Number(yearMax):null, topic_ids:topic?[Number(topic)]:null,research_topic:theme||null})});
      setResult(data);
    } catch(e) {if (e.name!=='AbortError') setError(e.message);} finally {if (!controller.signal.aborted) setBusy(false);}
  }
  function select(id) {location.hash='paper='+encodeURIComponent(id);}
  async function loadPaper(id) {
    detailController.current?.abort(); const controller = new AbortController(); detailController.current=controller; setDetailError('');setPaper(null);
    try {const data=await api('/api/paper?paper_id='+encodeURIComponent(id), {signal:controller.signal}); if (controller.signal.aborted) return; setPaper(data); requestAnimationFrame(() => detailRef.current?.focus());}
    catch(e) {if(e.name!=='AbortError') setDetailError(e.message);}
  }
  function clear() {location.hash='';searchController.current?.abort(); detailController.current?.abort(); setBusy(false);setQuery('');setResult(null);setPaper(null);setError('');setDetailError('');setYearMin('');setYearMax('');setTopic('');setResearchTopic('');setTopicSearch('');}
  return <><header><a href="/" className="brand"><span className="brand-mark">◈</span> ResearchGraph</a><nav><button onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?'Light theme':'Dark theme'}</button><button onClick={()=>setShowLibrary(!showLibrary)}>Reading list ({saved.length})</button><a href="/">Home</a><a href="/api/docs">API</a></nav></header>
    <main className={paperRoute?'paper-view':home?'home-view':'search-view'}>{showLibrary&&<Library rows={saved} onChange={()=>setSaved(readSaved())} onSelect={select}/>} {home&&<section className="intro"><p className="eyebrow">A CONNECTED VIEW OF AI RESEARCH</p><h1>Follow an idea.<br/><span>Find its connections.</span></h1><p className="lead">Explore papers through language, research topics, and the work around them.</p>
    <div className="corpus-line"><span className="dot"/>{status?`${status.papers.toLocaleString()} papers · ${status.feed?.live_updates?'scheduled research atlas':'frozen OpenAlex snapshot'}`:'Connecting to the research atlas…'}</div></section>}
    <section className="search-panel" aria-label="Search papers"><form onSubmit={e => {e.preventDefault();search();}}>
      <label htmlFor="query">What are you researching?</label><div className="query-row"><input id="query" value={query} onChange={e => setQuery(e.target.value)} maxLength={2000} required placeholder="e.g. Graph retrieval for multi-hop reasoning"/><button className="primary" type="submit" disabled={busy||!query.trim()}>{busy?'Searching…':'Find papers ↗'}</button></div>
      <div className="tools" aria-label="Active filters">{[[yearMin,'From '+yearMin,setYearMin],[yearMax,'Until '+yearMax,setYearMax],[topic,'Topic filter',setTopic],[researchTopic,'Research theme',setResearchTopic]].filter(([value])=>value).map(([value,label,setter])=><button type="button" key={label} onClick={()=>setter('')}>Remove {label} ×</button>)}</div><div className="filters"><label>Ranking<select value={mode} onChange={e => setMode(e.target.value)}><option value="hybrid">Hybrid</option><option value="bm25">Keyword · BM25</option><option value="dense">Semantic · dense</option></select></label>
        <label>Earliest year<input type="number" min="1900" max="2100" placeholder="Any" value={yearMin} onChange={e => setYearMin(e.target.value)}/></label>
        <label>Latest year<input type="number" min="1900" max="2100" placeholder="Any" value={yearMax} onChange={e => setYearMax(e.target.value)}/></label>
        <label className="topic-filter">Research topic<select value={topic} onChange={e => setTopic(e.target.value)}><option value="">All topics</option>{status?.topics.map(t=><option key={t.topic_id} value={t.topic_id}>{t.name}</option>)}</select></label><button type="button" className="clear" onClick={clear}>Clear</button></div>
    <div className="expanded-topics"><label>Find a research theme<input value={topicSearch} onChange={e=>setTopicSearch(e.target.value)} placeholder="Try computer vision, robotics, software…"/></label><label>Explore research themes<select aria-label="Explore research themes" value={researchTopic} onChange={e=>setResearchTopic(e.target.value)}><option value="">All research themes</option>{status?.research_topics?.filter(t=>!topicSearch||t.name.toLowerCase().includes(topicSearch.toLowerCase())||t.topic_key===researchTopic).map(t=><option key={t.topic_key} value={t.topic_key}>{t.name} ({t.papers.toLocaleString()})</option>)}</select></label></div><p className="evidence-note">{status?.research_topics?.length||0} source research themes, alongside 10 learned clusters. Filters combine; clear them to broaden your search.</p></form><div className="examples"><span>Try an idea</span>{EXAMPLES.map(q=><button key={q} disabled={busy} onClick={()=>search(q)}>{q} ↗</button>)}</div></section>
    {error&&<p role="alert" className="error">{error}</p>}{detailError&&<p role="alert" className="error">{detailError}</p>}
    {busy&&<p role="status" className="search-state">Searching the atlas…</p>}
    {!paperRoute&&result&&<section className="results" aria-label="Search results"><div className="results-heading"><h2>{result.count?'Papers to explore':'No papers found'}</h2><span>{result.count} results · {result.mode}</span></div>
      {!result.count&&<p>Try a broader query or clear the year and topic filters.</p>}
      <div className="results-layout"><div>{result.results.map((r,i)=><article className="paper-card" key={r.paper_id}><div className="paper-meta"><span>{String(i+1).padStart(2,'0')}</span><span>{r.year}</span><span>{r.citation_count_available===0?'Citation count unavailable':r.citation_count.toLocaleString()+' citations'}</span></div>
        <h3><button onClick={()=>select(r.paper_id)}>{r.title}</button></h3><p>{r.matching_sentence||r.abstract.slice(0,300)}</p><p className="match-reason">Why this matches: ranked by {result.mode==='hybrid'?'combined keyword and semantic relevance':result.mode==='dense'?'title and abstract similarity':'keyword relevance'}. Topic: {r.topic_name}.</p><div className="paper-footer"><span className="tag">{r.topic_name}</span><button onClick={()=>select(r.paper_id)}>Paper & connections ↗</button></div>
      </article>)}</div></div>
    </section>}
    {paperRoute&&<section aria-label="Paper page">{!paper&&!detailError&&<p role="status">Loading paper details…</p>}{paper&&<aside className="detail paper-page" ref={detailRef} tabIndex="-1" aria-label="Paper details"><button className="close" aria-label="Close paper details" onClick={()=>{location.hash=result?'search':'';}} >← Back</button><p className="eyebrow">PAPER & CONNECTIONS</p><h2>{paper.title}</h2><p>{paper.year} · {paper.citation_context?.global_count==null?'Citation count unavailable':paper.citation_context.global_count.toLocaleString()+' times cited'}</p><PaperTools paper={paper} onSaved={()=>setSaved(readSaved())}/><PaperInsights paper={paper} onSelect={select}/>{safeDoi(paper.doi)&&<a href={safeDoi(paper.doi)} target="_blank" rel="noopener noreferrer">Read at DOI ↗</a>}<Neighbors paper={paper} onSelect={select}/></aside>}</section>}
    {home&&status?.research_topics&&<section className="topic-explorer" aria-label="Explore AI and computer science"><div className="results-heading"><h2>Explore AI & computer science</h2><span>Connected research themes</span></div><div className="feed-grid">{[['T11714','Multimodal learning'],['T10260','Software engineering'],['T10286','Information retrieval'],['T11689','Adversarial robustness'],['T10653','Robot learning'],['T11273','Graph neural networks'],['T12026','Explainable AI'],['T10734','Cybersecurity'],['T10101','Cloud computing']].map(([key,label])=>{const t=status.research_topics.find(t=>t.topic_key===key);return t?<button key={key} onClick={()=>{setTopic('');setYearMin('');setYearMax('');setResearchTopic(key);setQuery(label);setResult(null);setPaper(null);document.getElementById('query')?.focus();}}><small>{t.papers.toLocaleString()} papers in this snapshot</small><span>{label}</span></button>:null;})}</div><p className="evidence-note">Choose a theme, then Find papers. Source topics are multi-label; counts can overlap. Broader AI/CS collection is the next Section 7 milestone.</p></section>}
    {home&&feed&&<section className="recent-feed" aria-label="Latest publications"><div className="results-heading"><h2>Latest in this atlas</h2><span>{feed.live_updates?'Scheduled updates':'Snapshot feed'}</span></div><p className="evidence-note">{feed.live_updates?'Recently published papers from verified scheduled updates; last successful update':'Recently published papers in the current release. Live ingestion is not enabled; snapshot date'} {new Date(feed.as_of).toLocaleDateString()}. Source indexing and release verification can delay new arrivals.</p><div className="feed-grid">{feed.papers.map(p=><button key={p.paper_id} onClick={()=>select(p.paper_id)}><small>{p.publication_date} · {p.citation_count.toLocaleString()} citations</small><span>{p.title}</span></button>)}</div></section>}
    {home&&<section id="about" className="about"><div><p className="eyebrow">ABOUT THIS ATLAS</p><h2>Explore connections.<br/>Keep the context.</h2></div><div><p>This is a selective snapshot of literature on language models, retrieval, and related research, published between 2020 and 2026. The graph connects papers by title and abstract similarity; it does not represent a causal relationship.</p><p>Topic names are generated from leading words. Citation counts reflect this snapshot. Search evaluation uses provisional, incomplete relevance judgments awaiting independent review.</p>{status&&<p className="snapshot">Corpus built {new Date(status.source_finished_at).toLocaleDateString()} · Snapshot {status.run_id}</p>}</div></section>}
    </main><footer><span>ResearchGraph · A research project</span><a href="/api/status">Corpus status ↗</a></footer></>;
}
createRoot(document.getElementById('root')).render(<App/>);
