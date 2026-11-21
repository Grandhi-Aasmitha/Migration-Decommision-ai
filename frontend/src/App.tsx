import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Activity, BookOpen, Check, ChevronDown, Database, FileText, GitBranch, Layers3, LoaderCircle, MessageSquare, Play, Plus, Search, Send, ShieldCheck, UploadCloud } from 'lucide-react';
import { API, json, request, type Answer, type Assessment, type Citation, type Doc, type DocType } from './api';
import GraphPanel from './GraphPanel';

const labels: Record<DocType,string> = {source_app:'Source application',target:'Target system',policy:'Policy',nfr:'Non-functional requirements'};
const questionExamples = ['What systems does this application depend on?', 'What evidence is required before decommissioning?', 'What are the recovery requirements?'];

function Citations({items}:{items:Citation[]}) {
  if (!items.length) return null;
  return <div className="citations"><div className="eyebrow">Supporting documents · {items.length}</div>{items.map(c => <details key={c.chunk_id} className="citation"><summary><FileText size={15}/><span>{c.filename} <small>v{c.version} · {c.page ? `Page ${c.page}` : c.section}</small></span><ChevronDown size={14}/></summary><p>{c.text}</p><a href={`${API}${c.url}`} target="_blank" rel="noreferrer">Open original document</a></details>)}</div>;
}

export default function App() {
  const [docs,setDocs] = useState<Doc[]>([]);
  const [health,setHealth] = useState<{demo:boolean;graph:string;graph_backend:string;model_provider:string}|null>(null);
  const [source,setSource] = useState('');
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [uploading,setUploading] = useState(false);
  const [docType,setDocType] = useState<DocType>('source_app');
  const [appId,setAppId] = useState('');
  const [version,setVersion] = useState('1.0');
  const [files,setFiles] = useState<File[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);
  const [jobs,setJobs] = useState<Record<string,{step:string;error?:string}>>({});
  const [question,setQuestion] = useState('');
  const [asking,setAsking] = useState(false);
  const [messages,setMessages] = useState<{question:string;answer:Answer}[]>([]);
  const [run,setRun] = useState<Assessment|null>(null);
  const [history,setHistory] = useState<Assessment[]>([]);
  const [targetSelection,setTargetSelection] = useState<string[]>([]);
  const [starting,setStarting] = useState(false);
  const [priority,setPriority] = useState('balanced');
  const [filter,setFilter] = useState('');

  async function refresh() {
    const [d,h,a] = await Promise.all([request<{documents:Doc[]}>('/documents'),request<NonNullable<typeof health>>('/health'),request<{assessments:Assessment[]}>('/assessments')]);
    setDocs(d.documents); setHealth(h); setHistory(a.assessments);
    const sources=[...new Set(d.documents.filter(doc=>doc.status==='ready' && doc.document_type==='source_app').map(doc=>doc.application_id))];
    setSource(current=>sources.includes(current) ? current : sources[0] || '');
    const updates = await Promise.all(d.documents.filter(doc => doc.status !== 'ready').map(async doc => [doc.job_id,await request<{step:string;error?:string}>(`/ingestion-jobs/${doc.job_id}`)] as const));
    setJobs(Object.fromEntries(updates));
  }
  useEffect(() => {
    let active = true;
    const load = () => { if(active) void refresh().catch(e => { if(active) setError(`Cannot reach the API: ${e.message}`); }); };
    load(); const timer = setInterval(load,2500);
    return () => {active=false;clearInterval(timer);};
  },[]);
  useEffect(()=>{if(source)setAppId(current=>current || source);},[source]);
  useEffect(() => {
    if(!run || !['running','paused'].includes(run.status)) return;
    let active=true;
    const timer=setInterval(() => {void request<Assessment>(`/assessments/${run.id}`).then(r => {if(active) setRun(r);}).catch(e => {if(active) setError(e.message);});},1500);
    return () => {active=false;clearInterval(timer);};
  },[run?.id,run?.status]);
  const ready=docs.filter(d => d.status==='ready');
  const sourceIds=[...new Set(ready.filter(d => d.document_type==='source_app').map(d => d.application_id))];
  const targets=[...new Set(ready.filter(d => d.document_type==='target' && d.application_id!==source).map(d => d.application_id))];
  const hasSource=sourceIds.includes(source);
  const shown=docs.filter(d => `${d.filename} ${d.application_id} ${d.document_type}`.toLowerCase().includes(filter.toLowerCase()));

  async function upload(event:FormEvent) {
    event.preventDefault();setError('');setNotice('');setUploading(true);
    try {
      let duplicates=0;
      for(const file of files) {
        const body=new FormData();body.append('file',file);body.append('document_type',docType);body.append('application_id',appId);body.append('version',version);
        const result=await request<{duplicate:boolean}>('/documents',{method:'POST',body});
        if(result.duplicate) duplicates++;
      }
      setNotice(`${files.length} document(s) submitted${duplicates ? `; ${duplicates} already uploaded` : ''}.`);
      setFiles([]);if(fileInput.current) fileInput.current.value='';await refresh();
    } catch(e) {setError((e as Error).message);} finally {setUploading(false);}
  }
  async function ask(event:FormEvent) {
    event.preventDefault(); if(!question.trim()) return;
    const submitted=question;setAsking(true);setError('');
    try {const answer=await request<Answer>('/chat/messages',json({question:submitted,application_id:source}));setMessages(m => [...m,{question:submitted,answer}]);setQuestion('');}
    catch(e) {setError((e as Error).message);} finally {setAsking(false);}
  }
  async function start() {
    setStarting(true);setError('');
    try {setRun(await request<Assessment>('/assessments',json({application_id:source,target_ids:targetSelection.filter(t => targets.includes(t))})));}
    catch(e) {setError((e as Error).message);} finally {setStarting(false);}
  }
  async function resume(event:FormEvent) {
    event.preventDefault();setStarting(true);setError('');
    try {setRun(await request<Assessment>(`/assessments/${run!.id}/answers`,json({objective:priority})));}
    catch(e) {setError((e as Error).message);} finally {setStarting(false);}
  }

  return <div className="shell">
    <aside className="sidebar"><a className="brand" href="#workspace"><span className="brand-icon"><GitBranch size={23}/></span><span>Migration<span className="brand-ai">AI</span><small>APPLICATION INTELLIGENCE</small></span></a>
      <div className="sidebar-caption">YOUR WORKSPACE</div><a href="#workspace" className="nav-item active"><Layers3 size={19}/> Assessment workspace</a><a href="#documents" className="nav-item"><Database size={19}/> Knowledge base <span>{docs.length}</span></a><a href="#knowledge-graph" className="nav-item"><GitBranch size={19}/> Explore graph</a><a href="#chat" className="nav-item"><MessageSquare size={19}/> Ask documents</a><a href="#assessment" className="nav-item"><GitBranch size={19}/> Assessment runs <span>{history.length}</span></a>
      <div className="sidebar-note"><ShieldCheck size={23}/><strong>Evidence comes first.</strong><p>Every recommendation starts with your documents. Review the sources and resolve gaps before deciding.</p></div>
      <div className="sidebar-bottom"><span className="avatar">MA</span><div>Migration workspace<small>Local prototype · v0.1</small></div></div>
    </aside>
    <main id="workspace"><header className="topbar"><span>Workspace <span className="slash">/</span> <strong>Application assessment</strong></span><span className={`connection ${health?.graph==='ready' ? 'connected' : ''}`}><Activity size={15}/>{health ? health.graph==='ready' ? 'Graph connected' : 'Graph unavailable' : 'Connecting to API'}</span></header>
      <div className="content"><section className="intro"><div><div className="eyebrow teal">MIGRATION & DECOMMISSION</div><h1>A clearer path to your next platform.</h1><p>Connect application evidence, ask better questions, and compare your options.</p></div><span className="prototype"><Layers3 size={15}/> Prototype workspace</span></section>
        {health?.demo && <div className="banner"><BookOpen size={19}/><span><strong>Demo mode is active.</strong> Uploaded files build a document graph. {health.model_provider==='demo' ? 'Extracting systems and capabilities from ordinary prose requires the configured model service.' : ''}</span></div>}
        {error && <div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={() => setError('')}>×</button></div>}
        {notice && <div className="notice" role="status"><Check size={17}/>{notice}</div>}
        <div className="stats"><div><span className="stat-icon blue"><FileText/></span><span><strong>{ready.length}<small> / {docs.length}</small></strong><p>Documents ready</p></span></div><div><span className="stat-icon teal-bg"><Layers3/></span><span><strong>{sourceIds.length}</strong><p>Source applications</p></span></div><div><span className="stat-icon violet"><GitBranch/></span><span><strong>{targets.length}</strong><p>Target systems</p></span></div><div><span className="stat-icon amber"><ShieldCheck/></span><span><strong>{ready.filter(d => ['policy','nfr'].includes(d.document_type)).length}</strong><p>Policy & NFR documents</p></span></div></div>
        <div className="context-bar"><div><span className="eyebrow">CURRENT APPLICATION</span><label className="sr-only" htmlFor="source-select">Source application for questions and assessments</label><select id="source-select" value={source} onChange={e => {setSource(e.target.value);setMessages([]);setTargetSelection([]);}}>{!sourceIds.includes(source) && <option value={source}>Upload source documents to begin</option>}{sourceIds.map(s => <option key={s}>{s}</option>)}</select></div><p><span className="dot"/> {hasSource ? 'Ready to explore source evidence' : 'Add source documents to get started'}</p></div>
        <div className="workspace-grid"><section id="documents" className="panel documents"><div className="panel-title"><span className="section-icon"><Database size={20}/></span><div><h2>Build your knowledge base</h2><p>The foundation for every answer.</p></div></div>
          <form onSubmit={upload}><label className="dropzone"><UploadCloud size={30}/><strong>{files.length ? `${files.length} file(s) selected` : 'Choose documents to upload'}</strong><span>Text-based PDF, DOCX or TXT · up to 15 MB each</span><input ref={fileInput} type="file" accept=".pdf,.docx,.txt" multiple required onChange={e => setFiles(Array.from(e.target.files || []))}/></label>
            <div className="form-row"><label>Document type<select value={docType} onChange={e => {const type=e.target.value as DocType;setDocType(type);if(['policy','nfr'].includes(type))setAppId('_shared');else if(appId==='_shared')setAppId(source);}}>{Object.entries(labels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select></label><label>Version<input value={version} onChange={e => setVersion(e.target.value)} required maxLength={100}/></label></div>
            <label>Application ID<input value={appId} onChange={e => setAppId(e.target.value)} required maxLength={100} placeholder="e.g. my-application"/><small>Use _shared for policies that apply across applications.</small></label>
            <button className="primary full" disabled={uploading || !files.length}>{uploading ? <LoaderCircle className="spin" size={17}/> : <Plus size={17}/>} {uploading ? 'Submitting documents…' : 'Add to knowledge base'}</button>
          </form><div className="library-heading"><h3>Document library <span>{docs.length}</span></h3></div><label className="search"><Search size={16}/><input aria-label="Filter documents" placeholder="Find a document…" value={filter} onChange={e => setFilter(e.target.value)}/></label>
          <div className="document-list">{!shown.length && <div className="empty"><FileText size={27}/><strong>{docs.length ? 'No matching documents' : 'Your evidence starts here'}</strong><p>{docs.length ? 'Try a different search.' : 'Upload your own source, target, policy, or NFR documents to begin.'}</p></div>}{shown.map(doc => <article className="document" key={doc.id}><FileText size={20}/><div><a href={`${API}/documents/${doc.id}/content`} target="_blank" rel="noreferrer">{doc.filename}</a><small>{doc.application_id} · {labels[doc.document_type]} · v{doc.version}</small><span className={`status ${doc.status}`}>{doc.status==='processing' && <LoaderCircle size={11} className="spin"/>}{doc.status==='ready' ? `${doc.chunk_count} chunks · Ready` : jobs[doc.job_id]?.step || doc.status}</span>{jobs[doc.job_id]?.error && <p className="job-error">{jobs[doc.job_id].error} Re-upload this file to retry.</p>}</div></article>)}</div>
        </section><div className="right-stack"><GraphPanel documents={docs}/><section id="chat" className="panel chat"><div className="panel-title"><span className="section-icon"><MessageSquare size={20}/></span><div><h2>Ask your documents</h2><p>Answers grounded in connected evidence.</p></div><span className="tag">DOCUMENT Q&A</span></div>
          <div className="chat-history" aria-live="polite">{!messages.length ? <div className="chat-welcome"><span className="welcome-icon"><BookOpen size={26}/></span><h3>What would you like to understand?</h3><p>Explore capabilities, dependencies, and requirements.<br/>Every answer links back to its source.</p><div className="suggestions">{questionExamples.map(q => <button key={q} onClick={() => setQuestion(q)}>{q}<Plus size={14}/></button>)}</div></div> : messages.map((m,i) => <article className="exchange" key={i}><div className="user-question">{m.question}</div><div className="answer"><div className="answer-label"><BookOpen size={15}/> Evidence answer{m.answer.mode==='demo' && <span className="tag">EXTRACTIVE DEMO</span>}</div><p>{m.answer.answer}</p><Citations items={m.answer.citations}/></div></article>)}{asking && <div className="thinking"><LoaderCircle size={17} className="spin"/> Retrieving document and graph evidence…</div>}</div>
          <form className="composer" onSubmit={ask}><label className="sr-only" htmlFor="question">Question about documents</label><input id="question" value={question} onChange={e => setQuestion(e.target.value)} placeholder={hasSource ? `Ask about ${source}…` : 'Upload source documents to start…'} minLength={3} maxLength={2000} disabled={!hasSource}/><button className="primary" aria-label="Send question" disabled={asking || !hasSource || question.trim().length<3}><Send size={18}/></button></form><p className="chat-caption">Questions explore documents. Start a comparison with Run assessment below.</p>
        </section><section id="assessment" className="panel assessment"><div className="panel-title"><span className="section-icon"><GitBranch size={20}/></span><div><h2>Compare migration options</h2><p>A structured assessment, guided by your priorities.</p></div><span className="tag">HUMAN IN THE LOOP</span></div>
          <div className="assessment-body"><div className="assessment-intro"><div><h3>Turn evidence into a draft recommendation.</h3><p>Compare documented coverage, surface gaps, and keep the decision in your hands.</p></div><button className="primary" onClick={() => void start()} disabled={!hasSource || starting || run?.status==='running'}>{starting ? <LoaderCircle size={16} className="spin"/> : <Play size={16}/>}Run assessment</button></div>
            <div className="target-options"><span className="eyebrow">TARGETS · ALL READY TARGETS BY DEFAULT</span>{targets.length ? <div>{targets.map(target => <label key={target}><input type="checkbox" checked={targetSelection.includes(target)} onChange={e => setTargetSelection(old => e.target.checked ? [...old,target] : old.filter(t => t!==target))}/>{target}</label>)}</div> : <p>Add a target document to enable comparison. A source-only run will report the missing evidence.</p>}</div>
            <div className="workflow"><span><Search size={15}/> Gather evidence</span><i/><span><MessageSquare size={15}/> Clarify priority</span><i/><span><ShieldCheck size={15}/> Draft recommendation</span></div>
            {history.length>0 && <label className="history-select">Assessment history<select value={run?.id || ''} onChange={e => {const chosen=history.find(r => r.id===e.target.value);if(chosen)setRun(chosen);}}><option value="">Select a previous run</option>{history.map(r => <option key={r.id} value={r.id}>{r.request.application_id} · {r.status} · {r.id.slice(0,8)}</option>)}</select></label>}
            {run && <div className="run-result" aria-live="polite"><div className="run-status"><span className={`status ${run.status}`}>{run.status==='running' && <LoaderCircle size={13} className="spin"/>}{run.status}</span><strong>{run.step}</strong><small>Run {run.id.slice(0,8)}</small></div>{run.error && <div role="alert" className="error">{run.error}</div>}
              {run.status==='paused' && run.question && <form className="clarification" onSubmit={resume}><h3>{run.question.question}</h3>{run.question.choices.map(c => <label key={c.value}><input type="radio" name="priority" value={c.value} checked={priority===c.value} onChange={e => setPriority(e.target.value)}/>{c.label}</label>)}<button className="primary" disabled={starting}>Continue assessment</button></form>}
              {run.result && <div className="recommendation"><div className="eyebrow teal">DRAFT · REVIEW REQUIRED</div><h3>{run.result.summary}</h3>{run.result.candidates.map(c => <article className="candidate" key={c.application_id}><div><strong>{c.application_id}</strong><span>{c.coverage_score===null ? 'Insufficient source facts' : `${c.coverage_score}% documented coverage`}</span></div>{c.coverage_score!==null && <div className="score-track"><span style={{width:`${c.coverage_score}%`}}/></div>}<dl><dt>Capabilities found</dt><dd>{c.matches.HAS_CAPABILITY.join(', ') || 'None documented'}</dd><dt>Integrations found</dt><dd>{c.matches.DEPENDS_ON.join(', ') || 'None documented'}</dd></dl>{c.gaps.length>0 && <ul>{c.gaps.map(g => <li key={g}>{g}</li>)}</ul>}</article>)}{run.result.rubric && <p className="rubric">Rubric: {Math.round(run.result.rubric.capability_weight*100)}% capability coverage, {Math.round(run.result.rubric.integration_weight*100)}% integration coverage. {run.result.rubric.meaning}</p>}<div className="gaps"><h4>Open checks before a decision</h4><ul>{run.result.gaps.map(g => <li key={g}>{g}</li>)}</ul></div><Citations items={run.result.citations}/></div>}
            </div>}
          </div></section></div></div><footer>Migration AI <span>Built around evidence. Designed for human review.</span></footer>
      </div></main>
  </div>;
}
