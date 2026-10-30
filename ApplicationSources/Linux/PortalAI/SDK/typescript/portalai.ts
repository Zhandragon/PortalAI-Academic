/** PortalAI application API v1. Requires fetch; no dependencies or mutation retries. */
export type Job = {id:string; state:'queued'|'running'|'complete'|'failed'|'cancelled'|'needs_review'; result?:unknown; error?:string};
export type Submitted = {job_id:string; state:'queued'; status_path:string};
export class APIError extends Error {
  constructor(public status:number, public code:string, message:string) {super(message);}
}
export class Client {
  private base:string;
  constructor(baseURL:string, private token:string) {
    const url=new URL(baseURL);
    if(url.protocol!=='http:' || url.hostname!=='127.0.0.1' || url.pathname.replace(/\/$/,'')!=='/v1' || url.search || url.hash || url.username) throw new Error('Copy the loopback /v1 URL from Workspace > API');
    this.base=baseURL.replace(/\/$/,'');
  }
  static newKey():string {return crypto.randomUUID();}
  async request<T=unknown>(method:'GET'|'POST',path:string,body?:unknown,options:{key?:string;query?:Record<string,string|number>;signal?:AbortSignal}={}):Promise<T> {
    if(!path.startsWith('/') || path.includes('..') || /[?#]/.test(path)) throw new Error('Use a v1-relative resource path');
    if(method==='POST' && !options.key) throw new Error('POST requires a stable idempotency key; retain it until the outcome is known');
    const query=new URLSearchParams();for(const [key,value] of Object.entries(options.query||{}))query.set(key,String(value));
    const response=await fetch(this.base+path+(query.size?'?'+query:''),{method,headers:{Authorization:'Bearer '+this.token,'Content-Type':'application/json',...(options.key?{'Idempotency-Key':options.key}:{})},body:method==='POST'?JSON.stringify(body??{}):undefined,signal:options.signal??AbortSignal.timeout(15000),redirect:'error'});
    const raw=await response.text();if(raw.length>2*1024*1024)throw new Error('API result limit exceeded');
    const value=JSON.parse(raw);
    if(!response.ok)throw new APIError(response.status,value.error?.code,value.error?.message||'API request failed');
    if(value.api_version!=='1.0')throw new Error('Unexpected API version');
    return value.data as T;
  }
  status(){return this.request('GET','/status');}
  createChat(title:string,key:string){return this.request<{id:string}>('POST','/chats',{title},{key});}
  message(chat:string,message:string,key:string,max_tokens=1024){return this.request<Submitted>('POST',`/chats/${chat}/messages`,{message,max_tokens},{key});}
  structured(question:string,schema:object,context:unknown,key:string,max_tokens=1024){return this.request<Submitted>('POST','/structured',{question,schema,context,max_tokens},{key});}
  job(id:string){return this.request<Job>('GET',`/jobs/${id}`);}
  cancel(id:string,key:string){return this.request('POST',`/jobs/${id}/cancel`,{},{key});}
  async wait(id:string,timeout=600000):Promise<Job>{
    const deadline=Date.now()+timeout;
    while(true){const row=await this.job(id);if(!['queued','running'].includes(row.state))return row;
      if(Date.now()>=deadline)throw new Error('Polling deadline reached; cancel explicitly if needed');
      await new Promise(resolve=>setTimeout(resolve,250));}
  }
}
