export function mergeBackup(value, papers, notes) {
  if (!value || value.version !== 1 || !Array.isArray(value.papers) || value.papers.length > 1000 || !value.notes || typeof value.notes !== 'object' || Array.isArray(value.notes)) throw Error('Unsupported backup format.');
  const imported = value.papers.map(p => {
    if (!p || typeof p.paper_id !== 'string' || p.paper_id.length > 200 || typeof p.title !== 'string' || p.title.length > 5000) throw Error('Invalid paper in backup.');
    // Restore identities only; refresh scholarly metadata through the API when opened.
    return {paper_id:p.paper_id,title:p.title,year:Number.isInteger(p.year)?p.year:null};
  });
  const mergedNotes={...notes};
  for(const p of imported){
    const n=value.notes[p.paper_id];if(!n)continue;
    if(typeof n!=='object'||Array.isArray(n))throw Error('Invalid notes.');
    const safe={};for(const k of ['collection','tags','text','status'])if(n[k]!==undefined){if(typeof n[k]!=='string'||n[k].length>10000)throw Error('Invalid note field.');safe[k]=n[k];}
    if(!Object.hasOwn(mergedNotes,p.paper_id))Object.defineProperty(mergedNotes,p.paper_id,{value:safe,enumerable:true,writable:true,configurable:true});
  }
  return {papers:[...new Map([...imported,...papers].map(p=>[p.paper_id,p])).values()],notes:mergedNotes};
}
