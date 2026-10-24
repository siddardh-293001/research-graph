export function findPassages(text,query){
 const terms=[...new Set(query.toLowerCase().match(/[a-z]{3,}/g)||[])].filter(w=>!['the','what','how','does','this','and','are','was','were','for'].includes(w));
 return text.split(/\r?\n\s*\r?\n/).map((text,i)=>({text,index:i+1,score:terms.filter(t=>text.toLowerCase().includes(t)).length})).filter(p=>p.score).sort((a,b)=>b.score-a.score||a.index-b.index).slice(0,5);
}
