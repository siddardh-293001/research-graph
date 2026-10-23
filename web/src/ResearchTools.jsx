import ReviewMatrix from './ReviewMatrix.jsx';
import React,{useState} from 'react';
const key='researchgraph-reading-list';
export function readSaved(){try{return JSON.parse(localStorage.getItem(key)||'[]');}catch{return [];}}
export function PaperTools({paper,onSaved}){
 const [message,setMessage]=useState('');
 const citation=`${(paper.authors||[]).join(', ')} (${paper.year}). ${paper.title}. ${paper.doi||paper.paper_id}`;
 const clean=v=>String(v||'').replace(/[{}\\]/g,' ').replace(/[\r\n]/g,' ');
 function save(){const rows=readSaved();if(!rows.some(p=>p.paper_id===paper.paper_id)){rows.push(paper);try{localStorage.setItem(key,JSON.stringify(rows));onSaved();setMessage('Saved on this device.');}catch{setMessage('Device storage is full or unavailable.');}}else setMessage('Already in your reading list.');}
 function bib(){const value=`@article{researchgraph${clean(paper.paper_id).replace(/\W/g,'')},\n title={${clean(paper.title)}},\n author={${(paper.authors||[]).map(clean).join(' and ')}},\n year={${clean(paper.year)}},\n doi={${clean(paper.doi)}}\n}`;const url=URL.createObjectURL(new Blob([value],{type:'text/plain'}));const a=document.createElement('a');a.href=url;a.download='citation.bib';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 return <><div className="tools"><button onClick={save}>Save to reading list</button><button onClick={async()=>{try{await navigator.clipboard.writeText(citation);setMessage('Citation copied.');}catch{setMessage('Clipboard unavailable. Use the BibTeX download.');}}}>Copy citation</button><button onClick={bib}>Export BibTeX</button></div><p role="status">{message}</p></>;
}
export function Library({rows,onChange,onSelect}){
 const [selected,setSelected]=useState([]);
 const papers=rows.filter(p=>selected.includes(p.paper_id));
 const references=p=>new Set((p.connections?.cites||[]).map(r=>r.paper_id));
 const shared=papers.length===2?(papers[0].connections?.cites||[]).filter(r=>references(papers[1]).has(r.paper_id)):[];
 return <section className="library" aria-label="Reading list"><h2>Reading list</h2><p>Saved on this browser. Select two papers to compare.</p>{!rows.length&&<p>Open a paper and save it to start a collection.</p>}{rows.map(p=><div className="tools" key={p.paper_id}><label><input type="checkbox" checked={selected.includes(p.paper_id)} disabled={selected.length===2&&!selected.includes(p.paper_id)} onChange={e=>setSelected(e.target.checked?[...selected,p.paper_id]:selected.filter(id=>id!==p.paper_id))}/> Compare</label><button onClick={()=>onSelect(p.paper_id)}>{p.title}</button><button onClick={()=>{try{localStorage.setItem(key,JSON.stringify(rows.filter(r=>r.paper_id!==p.paper_id)));setSelected(selected.filter(id=>id!==p.paper_id));onChange();}catch{}}}>Remove</button></div>)}{papers.length===2&&<><h3>Paper comparison</h3><ReviewMatrix papers={papers}/><div className="compare-grid">{papers.map(p=><div key={p.paper_id}><h3>{p.title}</h3><p>{p.year} · {p.citation_context?.global_count??'Unknown'} times cited</p><p>{p.summary?.sentences?.join(' ')||p.abstract}</p><p>{p.research_topics?.map(t=>t.name).join(' · ')}</p></div>)}</div><h3>Shared references in the displayed metadata</h3>{shared.length?shared.map(r=><p key={r.paper_id}><button onClick={()=>onSelect(r.paper_id)}>{r.title}</button></p>):<p>No shared references in the available linked-paper sample. This does not establish that the full bibliographies have no overlap.</p>}</>}</section>;
}
