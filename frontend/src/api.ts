export const API = import.meta.env.VITE_API_BASE || '/api';
export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { const body = await response.json(); message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail); } catch { /* preserve HTTP status */ }
    throw new Error(message);
  }
  return response.json();
}
export const json = (body: unknown): RequestInit => ({method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
export type DocType = 'source_app' | 'target' | 'policy' | 'nfr';
export type Doc = {id:string;filename:string;application_id:string;document_type:DocType;version:string;status:string;job_id:string;chunk_count?:number};
export type Citation = {chunk_id:string;document_id:string;filename:string;version:string;page:number|null;section:string;url:string;text:string};
export type Fact = {application_id:string;relation:string;name:string;quote:string;chunk_id:string};
export type Answer = {answer:string;citations:Citation[];facts:Fact[];mode:string};
export type Candidate = {application_id:string;coverage_score:number|null;gaps:string[];matches:Record<string,string[]>;facts:Fact[]};
export type Result = {summary:string;recommendation:string|null;objective:string;draft:boolean;gaps:string[];candidates:Candidate[];citations:Citation[];rubric?:{capability_weight:number;integration_weight:number;meaning:string}};
export type Assessment = {id:string;status:string;step:string;request:{application_id:string;target_ids:string[]};error?:string;question?:{question:string;choices:{label:string;value:string}[]};result?:Result};
export type GraphKind = 'Document' | 'Chunk' | 'Application' | 'System' | 'Capability' | 'Policy';
export type GraphNode = {id:string;kind:GraphKind;label:string;document_id?:string;text?:string;page?:number|null;section?:string;url?:string;version?:string};
export type GraphEdge = {id:string;source:string;target:string;relation:string;evidence:Citation & {quote?:string}};
export type GraphData = {nodes:GraphNode[];edges:GraphEdge[];truncated:boolean;document_count:number;available_document_count:number};
