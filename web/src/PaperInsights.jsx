import React from 'react';

export default function PaperInsights({paper,onSelect}) {
  const context=paper.citation_context;
  if (!context) return <p>{paper.abstract}</p>;
  return <div className="paper-insights">
    <p className="paper-authors">{paper.authors?.slice(0,6).join(' · ') || 'Authors unavailable'}{paper.authors?.length>6?` · +${paper.authors.length-6} more`:''}</p>
    <div className="impact-grid" aria-label="Citation context">
      <div><strong>{context.global_count==null?'Unavailable':context.global_count.toLocaleString()}</strong><span>Times cited · {context.source||'OpenAlex'}</span></div>
      <div><strong>{context.within_corpus_citing.toLocaleString()}</strong><span>Citing papers in this atlas</span></div>
      <div><strong>{context.recorded_references.toLocaleString()}</strong><span>Recorded references</span></div>
    </div>
    <p className="evidence-note">Counts at {new Date(context.as_of).toLocaleDateString()}. Citation counts indicate attention, not research quality. Missing references can limit coverage.</p>
    <section><h3>At a glance</h3><p className="evidence-note">Extractive summary · abstract only</p><ul className="summary-points">{paper.summary?.sentences.map((sentence,i)=><li key={i}>{sentence}</li>)}</ul><p className="evidence-note">{paper.summary?.scope}</p></section>
    <section><h3>Research themes</h3><div className="theme-chips">{paper.research_topics?.map(t=><span className="tag" key={t.topic_key}>{t.name}</span>)}</div><p className="evidence-note">OpenAlex topic assignments; a paper can belong to several themes.</p><p>{paper.keywords?.slice(0,8).join(' · ')}</p></section>
    <section className="citation-links"><h3>How this paper connects</h3><p>Follow references backwards to its foundations, or citations forwards to work that cites it. A citation alone does not establish agreement or influence.</p>
      {[['cites','References in this atlas',context.within_corpus_references],['cited_by','Papers citing this work',context.within_corpus_citing]].map(([key,label,count])=><details key={key} open={key==='cites'}><summary>{label} · {count.toLocaleString()}</summary>{paper.connections[key].length?<ol>{paper.connections[key].map(n=><li key={n.paper_id}><button onClick={()=>onSelect(n.paper_id)}>{n.title}</button><small>{n.year} · {n.citation_count.toLocaleString()} citations</small></li>)}</ol>:<p>No matching links are recorded in this snapshot.</p>}{count>12&&<p className="evidence-note">Showing the 12 most cited linked papers.</p>}</details>)}
    </section>
    <details className="full-abstract"><summary>Read the full abstract</summary><p>{paper.abstract}</p></details>
  </div>;
}
