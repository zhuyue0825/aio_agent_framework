import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api, type Evidence, type SourceSegment } from "./api";

export default function EvidencePanel({source,conversationId,onClose}:{source:Evidence;conversationId:string;onClose:()=>void}) {
  const [segments,setSegments]=useState<SourceSegment[]>([]);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(true);
  const active=useRef<HTMLDivElement>(null);
  const close=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    close.current?.focus();
    const handle=(event:KeyboardEvent)=>{if(event.key==="Escape")onClose();};
    window.addEventListener("keydown",handle);
    return ()=>window.removeEventListener("keydown",handle);
  },[onClose]);
  useEffect(()=>{
    let cancelled=false;setSegments([]);setError("");setLoading(true);
    const request=source.attachment_id?api.attachment(conversationId,source.attachment_id):source.document_id?api.knowledgeDocument(source.document_id):Promise.resolve({segments:[]});
    request.then(data=>{if(!cancelled)setSegments(data.segments??[]);}).catch(err=>{if(!cancelled)setError(String(err));}).finally(()=>{if(!cancelled)setLoading(false);});
    return ()=>{cancelled=true;};
  },[source,conversationId]);
  useEffect(()=>{active.current?.scrollIntoView({block:"center"});},[segments]);
  return <aside className="evidence-panel" role="dialog" aria-label="来源原文">
    <header><div><strong>{source.name}</strong><small>{source.path || (source.kind==="knowledge"?"知识库原文":"附件快照")} · {source.location}</small></div><button ref={close} aria-label="关闭来源" onClick={onClose}><X size={19}/></button></header>
    <div className="evidence-body">
      {loading && <p>正在加载原文…</p>}
      {error && <p role="alert">{error}</p>}
      {segments.map(segment=><div ref={segment.id===source.chunk_id?active:undefined} key={segment.id} className={`evidence-segment ${segment.id===source.chunk_id?"highlighted":""}`}><small>{segment.location}</small><pre>{segment.text}</pre></div>)}
      {!loading && !segments.length && source.text && <pre>{source.text}</pre>}
    </div>
  </aside>;
}
