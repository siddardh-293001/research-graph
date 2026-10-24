import {useEffect,useState} from 'react';
export function readNotes(){try{const value=JSON.parse(localStorage.getItem('rg-notes')||'{}');return value&&typeof value==='object'&&!Array.isArray(value)?value:{};}catch{return {};}}
export function notifyNotes(){window.dispatchEvent(new Event('researchgraph-notes'));}
export function updateNote(id,field,value){const current=readNotes();localStorage.setItem('rg-notes',JSON.stringify({...current,[id]:{...current[id],[field]:value}}));notifyNotes();}
export function useReviewNotes(){const [notes,setNotes]=useState(readNotes);useEffect(()=>{const refresh=()=>setNotes(readNotes());window.addEventListener('researchgraph-notes',refresh);window.addEventListener('storage',refresh);return()=>{window.removeEventListener('researchgraph-notes',refresh);window.removeEventListener('storage',refresh);};},[]);return notes;}
