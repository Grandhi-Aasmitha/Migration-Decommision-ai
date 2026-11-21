import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { ExternalLink, GitBranch, LoaderCircle, Maximize2, Minus, Plus, RefreshCw, Search } from 'lucide-react';
import { API, request, type Doc, type GraphData, type GraphEdge, type GraphKind, type GraphNode } from './api';
import './graph.css';

const colors: Record<GraphKind,string> = {Document:'#447bc0',Chunk:'#7b8fa6',Application:'#087e83',System:'#9771ca',Capability:'#3b9671',Policy:'#bd8c31'};
const empty:GraphData={nodes:[],edges:[],truncated:false,document_count:0,available_document_count:0};
const column=(kind:GraphKind) => kind==='Document' ? 0 : kind==='Chunk' ? 1 : kind==='Application' ? 2 : 3;

export default function GraphPanel({documents}:{documents:Doc[]}) {
  const [data,setData]=useState<GraphData>(empty);
  const [documentId,setDocumentId]=useState('');
  const [application,setApplication]=useState('');
  const [search,setSearch]=useState('');
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const [selected,setSelected]=useState<string|null>(null);
  const [selectedEdge,setSelectedEdge]=useState<string|null>(null);
  const [refresh,setRefresh]=useState(0);
  const [zoom,setZoom]=useState(1);
  const [pan,setPan]=useState({x:0,y:0});
  const drag=useRef<{x:number;y:number;px:number;py:number}|null>(null);
  const marker=useId().replace(/:/g,'');
  const ready=documents.filter(d=>d.status==='ready');
  const readyKey=ready.map(d=>d.id).sort().join('|');
  const applications=[...new Set(ready.map(d=>d.application_id))];
  useEffect(()=>{
    if(documentId && !ready.some(d=>d.id===documentId)) setDocumentId('');
    if(application && !applications.includes(application)) setApplication('');
  },[readyKey,documentId,application]);
  useEffect(()=>{
    let active=true;
    setLoading(true);setError('');setSelected(null);setSelectedEdge(null);
    const params=new URLSearchParams();
    if(documentId)params.set('document_id',documentId);
    if(application)params.set('application_id',application);
    request<GraphData>(`/graph?${params}`).then(result=>{if(active){setData(result);setZoom(1);setPan({x:0,y:0});}})
      .catch(e=>{if(active){setError(e.message);setData(empty);}})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[readyKey,documentId,application,refresh]);

  const layout=useMemo(()=>{
    const grouped=[0,1,2,3].map(i=>data.nodes.filter(n=>column(n.kind)===i));
    const height=Math.max(440,...grouped.map(g=>g.length*88+65));
    const nodes=grouped.flatMap((group,col)=>group.map((n,i)=>({...n,x:105+col*255,y:72+i*88})));
    return {nodes,height,byId:new Map(nodes.map(n=>[n.id,n]))};
  },[data]);
  const selectedNode=data.nodes.find(n=>n.id===selected);
  const edge=data.edges.find(e=>e.id===selectedEdge);
  const related=data.edges.filter(e=>e.source===selected || e.target===selected);
  const evidence=[...new Map((edge ? [edge] : related).map(e=>[`${e.evidence.chunk_id}:${e.evidence.quote || ''}`,e.evidence])).values()];
  const connectedIds=new Set(selected ? [selected,...related.flatMap(e=>[e.source,e.target])] : []);
  const matchedIds=new Set(data.nodes.filter(n=>`${n.label} ${n.kind} ${n.text || ''}`.toLowerCase().includes(search.toLowerCase())).map(n=>n.id));
  const dim=(node:GraphNode)=>search ? !matchedIds.has(node.id) : selected ? !connectedIds.has(node.id) : false;
  const choose=(node:GraphNode)=>{setSelected(old=>old===node.id ? null : node.id);setSelectedEdge(null);};
  const describe=(edge:GraphEdge)=>`${layout.byId.get(edge.source)?.label} ${edge.relation} ${layout.byId.get(edge.target)?.label}`;
  const reset=()=>{setZoom(1);setPan({x:0,y:0});};
  const viewWidth=1050/zoom,viewHeight=layout.height/zoom;

  return <section id="knowledge-graph" className="panel graph-panel"><div className="panel-title"><span className="section-icon"><GitBranch size={20}/></span><div><h2>Explore your knowledge graph</h2><p>See how your uploaded evidence connects.</p></div><button className="graph-refresh" onClick={()=>setRefresh(n=>n+1)} aria-label="Refresh graph"><RefreshCw size={16}/></button></div>
    <div className="graph-body"><div className="graph-filters"><label>Application<select aria-label="Graph application filter" value={application} onChange={e=>{setApplication(e.target.value);setDocumentId('');}}><option value="">All uploaded applications</option>{applications.map(id=><option key={id}>{id}</option>)}</select></label><label>Document<select aria-label="Graph document filter" value={documentId} onChange={e=>setDocumentId(e.target.value)}><option value="">All processed documents</option>{ready.filter(d=>!application || d.application_id===application || d.application_id==='_shared').map(d=><option value={d.id} key={d.id}>{d.filename} · v{d.version}</option>)}</select></label></div>
      {loading && <div className="graph-message" role="status"><LoaderCircle size={19} className="spin"/>Loading uploaded evidence…</div>}
      {error && <div className="error" role="alert">{error}</div>}
      {!loading && !error && !data.nodes.length && <div className="graph-empty"><GitBranch size={36}/><h3>Your graph starts with an upload</h3><p>Upload a PDF, DOCX, or TXT document. Once processing finishes, its document, passage, and application connections appear here automatically.</p><a href="#documents">Upload your first document</a></div>}
      {!loading && data.nodes.length>0 && <><div className="graph-toolbar"><label className="graph-search"><Search size={15}/><input aria-label="Find a graph node" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find a node or passage…"/></label><div><button aria-label="Zoom out" disabled={zoom<=.5} onClick={()=>setZoom(z=>Math.max(.5,z/1.3))}><Minus size={16}/></button><button onClick={reset} aria-label="Fit graph"><Maximize2 size={16}/></button><button aria-label="Zoom in" disabled={zoom>=5} onClick={()=>setZoom(z=>Math.min(5,z*1.3))}><Plus size={16}/></button></div></div>
        <div className="graph-stage"><svg role="group" aria-label="Knowledge graph from uploaded documents" style={{height:Math.max(430,layout.height*.86)}} viewBox={`${pan.x} ${pan.y} ${viewWidth} ${viewHeight}`}
          onPointerDown={e=>{if(e.target!==e.currentTarget)return;drag.current={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y};e.currentTarget.setPointerCapture(e.pointerId);}}
          onPointerMove={e=>{if(!drag.current)return;const rect=e.currentTarget.getBoundingClientRect();setPan({x:drag.current.px-(e.clientX-drag.current.x)*viewWidth/rect.width,y:drag.current.py-(e.clientY-drag.current.y)*viewHeight/rect.height});}}
          onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
          <defs><marker id={marker} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#a8bac8"/></marker></defs>
          {['Documents','Passages','Applications','Connected entities'].map((title,i)=><text key={title} x={105+i*255} y="22" textAnchor="middle" className="graph-column-label">{title}</text>)}
          {data.edges.map(link=>{const start=layout.byId.get(link.source),end=layout.byId.get(link.target);if(!start || !end)return null;const active=selectedEdge===link.id || !!selected && (link.source===selected || link.target===selected);return <g className={`graph-edge ${active ? 'highlight' : ''}`} key={link.id} opacity={search && !matchedIds.has(link.source) && !matchedIds.has(link.target) ? .12 : 1}>
            <path d={`M ${start.x+18} ${start.y} C ${start.x+115} ${start.y}, ${end.x-115} ${end.y}, ${end.x-21} ${end.y}`} markerEnd={`url(#${marker})`} onClick={()=>{setSelectedEdge(link.id);setSelected(null);}}/>
            <title>{describe(link)}</title></g>;})}
          {layout.nodes.map(node=><g key={node.id} className={`graph-node ${selected===node.id ? 'selected' : ''}`} role="button" tabIndex={0} aria-label={`${node.kind}: ${node.label}`} aria-pressed={selected===node.id} transform={`translate(${node.x},${node.y})`} opacity={dim(node) ? .18 : 1} onClick={()=>choose(node)} onKeyDown={e=>{if(e.key==='Enter' || e.key===' '){e.preventDefault();choose(node);}}}>
            <circle r="21" fill={colors[node.kind]} stroke={selected===node.id ? '#142b40' : 'white'} strokeWidth="4"/><text y="5" textAnchor="middle" className="graph-node-letter">{node.kind[0]}</text><text y="41" textAnchor="middle" className="graph-node-label">{node.label.length>26 ? node.label.slice(0,24)+'…' : node.label}</text><title>{node.kind}: {node.label}</title></g>)}
        </svg></div><div className="graph-legend">{Object.entries(colors).map(([kind,color])=><span key={kind}><i style={{background:color}}/>{kind}</span>)}</div>
        <p className="graph-caption">{data.nodes.length} nodes · {data.edges.length} connections · {data.document_count} document(s). Select a node to inspect its relationships and source evidence. Drag blank space to pan.</p>
        {data.truncated && <div className="banner">Showing a bounded graph. Select a document or application to inspect the remaining evidence.</div>}
        {(selectedNode || edge) && <div className="graph-inspector"><div className="graph-inspector-title"><div><span className="eyebrow">{selectedNode?.kind || 'RELATIONSHIP'}</span><h3>{selectedNode?.label || (edge && describe(edge))}</h3></div><button onClick={()=>{setSelected(null);setSelectedEdge(null);}} aria-label="Close graph details">×</button></div>
          {selectedNode?.text && <p>{selectedNode.text}</p>}{selectedNode?.url && <a href={`${API}${selectedNode.url}`} target="_blank" rel="noreferrer">Open original document <ExternalLink size={13}/></a>}
          {!!related.length && <ul className="graph-relations">{related.map(link=><li key={link.id}><button onClick={()=>{setSelectedEdge(link.id);setSelected(null);}}>{describe(link)}</button></li>)}</ul>}
          {evidence.map((source,i)=><details className="citation" key={`${source.chunk_id}:${i}`} open={!!edge}><summary>{source.filename} · {source.page ? `Page ${source.page}` : source.section}</summary><p>{source.quote || source.text}</p><a href={`${API}${source.url}`} target="_blank" rel="noreferrer">Open supporting document</a></details>)}
        </div>}
        {!data.nodes.some(n=>['System','Capability','Policy'].includes(n.kind)) && <p className="graph-caption">Document structure is available. No explicit domain facts were extracted from these uploads. The local demo recognizes lines such as DEPENDS_ON: System name; use the configured model service for extraction from ordinary prose.</p>}
      </>}
    </div>
  </section>;
}
