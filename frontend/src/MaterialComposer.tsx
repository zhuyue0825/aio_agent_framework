import { useEffect, useRef, useState } from "react";
import { Plus, BookOpen, FileText, X, Upload, FolderOpen, RotateCw } from "lucide-react";
import { api, type Attachment, type KnowledgeBase, type MaterialSelection, type Workspace, type WorkspaceNode } from "./api";

type Pending = {localId: string; name: string; state: "processing" | "ready" | "failed"; item?: Attachment; file?: File; path?: string; error?: string};
export default function MaterialComposer({conversationId, projectId, workspace, busy, reset, onChange}: {
  conversationId: string; projectId?: string; workspace: Workspace | null; busy: boolean; reset: number;
  onChange: (selection: MaterialSelection, blocked: boolean) => void;
}) {
  const [pending,setPending] = useState<Pending[]>([]);
  const [selected,setSelected] = useState<string[]>([]);
  const [catalog,setCatalog] = useState<KnowledgeBase[]>([]);
  const [menu,setMenu] = useState<"add"|"knowledge"|"workspace"|null>(null);
  const [filter,setFilter] = useState("");
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const live = useRef(true);
  useEffect(() => {live.current=true; return () => {live.current=false;};},[]);
  useEffect(() => {
    let ignore=false;
    if(!conversationId) {setLoading(false);return;}
    Promise.all([api.knowledgeBases(),api.selectedKnowledge(conversationId)]).then(([bases,selection]) => {
      if(!ignore) {setCatalog(bases.knowledge_bases);setSelected(selection.knowledge_ids);}
    }).catch(err=>{if(!ignore)setError(String(err));}).finally(()=>{if(!ignore)setLoading(false);});
    return ()=>{ignore=true;};
  },[conversationId]);
  useEffect(()=>{setPending([]);},[reset]);
  useEffect(()=>{onChange({attachment_ids:pending.filter(p=>p.state==="ready" && p.item).map(p=>p.item!.id),knowledge_ids:selected},loading || pending.some(p=>p.state!=="ready"));},[pending,selected,loading,onChange]);

  async function process(entry: Pending) {
    setPending(all=>all.map(p=>p.localId===entry.localId?{...p,state:"processing",error:undefined}:p));
    try {
      const item=entry.item ? await api.retryAttachment(conversationId,entry.item.id) : entry.file ? await api.uploadAttachment(conversationId,entry.file) : await api.referenceAttachment(conversationId,projectId!,entry.path!);
      if(live.current) setPending(all=>all.map(p=>p.localId===entry.localId?{...p,item,state:item.status==="READY"?"ready":"failed",error:item.error_message}:p));
    } catch(err) {if(live.current)setPending(all=>all.map(p=>p.localId===entry.localId?{...p,state:"failed",error:err instanceof Error?err.message:String(err)}:p));}
  }
  function addFiles(files: File[]) {
    if(busy || !conversationId)return;
    if(files.length+pending.length>5){setError("每条消息最多添加 5 个附件");return;}
    const entries=files.map(file=>({localId:crypto.randomUUID(),name:file.name,state:"processing" as const,file}));
    setPending(all=>[...all,...entries]);setMenu(null);setError("");
    entries.forEach(entry=>{
      if(entry.file.size>5*1024*1024) setPending(all=>all.map(p=>p.localId===entry.localId?{...p,state:"failed",error:"文件超过 5 MB，请移除后选择较小文件"}:p));
      else void process(entry);
    });
  }
  function reference(path: string) {
    if(pending.length>=5){setError("每条消息最多添加 5 个附件");return;}
    const entry:Pending={localId:crypto.randomUUID(),name:path.split("/").pop()!,path,state:"processing"};
    setPending(all=>[...all,entry]);setMenu(null);void process(entry);
  }
  async function choose(enabled: boolean) {
    setLoading(true);setError("");
    const next=enabled?["duretrieval"]:[];
    try {await api.selectKnowledge(conversationId,next);if(live.current)setSelected(next);}
    catch(err){if(live.current)setError(String(err));}
    finally{if(live.current)setLoading(false);}
  }
  const flatten=(nodes:WorkspaceNode[]):string[]=>nodes.flatMap(n=>n.type==="file"?[n.path]:flatten(n.children??[]));
  return <div className="material-composer" onDragOver={e=>{e.preventDefault();}} onDrop={e=>{e.preventDefault();addFiles(Array.from(e.dataTransfer.files));}}>
    {pending.length>0 && <div className="attachment-chips">{pending.map(p=><div className={`attachment-chip ${p.state}`} key={p.localId}>
      <FileText size={15}/><span title={p.name}>{p.name}<small>{p.state==="processing"?"上传并解析中…":p.state==="ready"?"已就绪":p.error}</small></span>
      {p.state==="failed" && <button aria-label={`重试 ${p.name}`} disabled={busy} onClick={()=>void process(p)}><RotateCw size={14}/></button>}
      <button aria-label={`移除 ${p.name}`} disabled={busy} onClick={()=>setPending(all=>all.filter(x=>x.localId!==p.localId))}><X size={14}/></button>
    </div>)}</div>}
    <div className="material-actions">
      <input ref={input} type="file" multiple hidden accept=".pdf,.txt,.md,.markdown,.py,.java,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.xml,.html,.css,.sql,.sh,.c,.cpp,.h,.go,.rs,.properties,.csv,.log" onChange={e=>{addFiles(Array.from(e.target.files??[]));e.target.value="";}}/>
      <button type="button" className="material-button" aria-label="添加文件" aria-expanded={menu==="add"} disabled={busy||!conversationId} onClick={()=>setMenu(menu==="add"?null:"add")}><Plus size={18}/></button>
      <button type="button" className={`material-button ${selected.length?"selected":""}`} aria-expanded={menu==="knowledge"} disabled={busy||loading||!conversationId} onClick={()=>setMenu(menu==="knowledge"?null:"knowledge")}><BookOpen size={15}/>{selected.length?"知识库：中文通用演示库":"知识库：未选择"}</button>
      <span className="material-caption">支持拖入文件 · 单个文件 ≤ 5 MB</span>
    </div>
    {menu && <div className="material-popover">
      <button className="material-close" aria-label="关闭附件菜单" onClick={()=>setMenu(null)}><X size={14}/></button>
      {menu==="add" && <><button onClick={()=>input.current?.click()}><Upload size={16}/>上传本地文件</button><button disabled={!projectId||!workspace} onClick={()=>setMenu("workspace")}><FolderOpen size={16}/>引用工作区文件</button><small>附件仅用于当前对话，不会自动加入知识库。</small></>}
      {menu==="knowledge" && <><strong>选择知识库</strong>{catalog.map(k=><label key={k.id}><input type="checkbox" checked={selected.includes(k.id)} disabled={loading || (!k.available && !selected.includes(k.id))} onChange={e=>void choose(e.target.checked)}/><span>{k.name}<small>{k.available?k.description:"服务暂不可用；已选时可取消选择"}</small></span></label>)}<small>选择后按需检索；要求依据知识库回答时会先查资料。</small></>}
      {menu==="workspace" && <><strong>引用工作区文件</strong><input aria-label="筛选工作区文件" placeholder="输入文件名筛选" value={filter} onChange={e=>setFilter(e.target.value)}/><div className="workspace-material-list">{flatten(workspace?.tree??[]).filter(p=>p.toLowerCase().includes(filter.toLowerCase())).slice(0,100).map(p=><button key={p} onClick={()=>reference(p)}><FileText size={14}/>{p}</button>)}</div><small>保存当前文件快照，引用时标明原路径与行号。</small></>}
    </div>}
    {error && <div className="material-error" role="alert">{error}<button onClick={()=>setError("")}>关闭</button></div>}
  </div>;
}
