"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Fact = {id:string;person_id:string;predicate:string;value:string;valid_from:string|null;valid_until:string|null;status:string;confidence:string;source_note:string;source_quote:string|null};
type Conflict = {a:Fact;b:Fact;a_version:string;b_version:string;uncertain_period:boolean};
type Decision = {id:string;person_id:string;action:string;note:string;before:{a:Fact;b:Fact};after:{a:Fact;b:Fact};created_at:string};
type Person = {id:string;first_name:string;last_name:string};
const actions:Record<string,string> = {changed:"Situation hat sich verändert",both:"Beide Angaben sind korrekt",reject_a:"Angabe A ist falsch",reject_b:"Angabe B ist falsch",defer:"Noch unklar – offen lassen"};
const states:Record<string,string> = {proposed:"Unbestätigt",confirmed:"Bestätigt",rejected:"Verworfen"};
const confidence:Record<string,string> = {low:"Niedrig",medium:"Mittel",high:"Hoch"};
const range = (fact:Fact)=> (fact.valid_from??"Beginn unbekannt")+" – "+(fact.valid_until?fact.valid_until+" (exklusiv)":"Ende offen/unbekannt");
function FactCard({label,fact}:{label:string;fact:Fact}){
  return <div className="fact-conflict-side"><strong>{label}: {fact.value}</strong><p>{range(fact)}</p><p className="muted">{states[fact.status]} · Vertrauen: {confidence[fact.confidence]}</p>{fact.source_note&&<p>Quelle: {fact.source_note}</p>}{fact.source_quote&&<blockquote>{fact.source_quote}</blockquote>}</div>;
}
function ReviewForm({conflict,busy,onResolve}:{conflict:Conflict;busy:boolean;onResolve:(action:string,previous:string|null,note:string)=>Promise<void>}){
  const [action,setAction]=useState("");
  const [previous,setPrevious]=useState("");
  const [note,setNote]=useState("");
  function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(!action||(action==="changed"&&!previous))return;
    if(!window.confirm("Diese Entscheidung speichern? "+actions[action]))return;
    void onResolve(action,action==="changed"?previous:null,note);
  }
  const candidates=[conflict.a,conflict.b].filter((fact,i)=>{
    const next=i===0?conflict.b:conflict.a;
    return !fact.valid_until&&!!next.valid_from&&(!fact.valid_from||fact.valid_from<next.valid_from);
  });
  return <form className="person-form" onSubmit={submit}>
    <label>Entscheidung<select value={action} onChange={e=>{setAction(e.target.value);setPrevious("");}} required><option value="">Auswählen</option>{Object.entries(actions).map(([v,label])=><option value={v} key={v} disabled={v==="changed"&&!candidates.length}>{label}</option>)}</select></label>
    {action==="changed"&&<label>Welcher Fakt galt zuerst?<select required value={previous} onChange={e=>setPrevious(e.target.value)}><option value="">Auswählen</option>{candidates.map(f=><option key={f.id} value={f.id}>{f.id===conflict.a.id?"A":"B"}: {f.value}</option>)}</select><small>Der frühere Fakt endet am Beginndatum des nachfolgenden. Beide werden bestätigt.</small></label>}
    {action==="both"&&<p>Beide Fakten werden bestätigt; dieser Konflikt wird für die aktuellen Versionen ausgeblendet.</p>}
    {(action==="reject_a"||action==="reject_b")&&<p>Eine Aussage wird verworfen, die andere bestätigt. Beide bleiben in der Faktenhistorie.</p>}
    {action==="defer"&&<p>Der Konflikt bleibt offen. Keine Aussage wird verändert.</p>}
    <label>Begründung (optional)<textarea value={note} onChange={e=>setNote(e.target.value)} maxLength={5000}/></label>
    <button disabled={busy||!action||(action==="changed"&&!previous)}>Entscheidung speichern</button>
  </form>;
}
export function FactConflictsPanel({request,people,personId,revision,onResolved}:{request:Request;people:Person[];personId?:string;revision:number;onResolved:()=>Promise<void>}){
  const [rows,setRows]=useState<Conflict[]>([]);
  const [history,setHistory]=useState<Decision[]>([]);
  const [showHistory,setShowHistory]=useState(false);
  const [offset,setOffset]=useState(0);
  const [historyOffset,setHistoryOffset]=useState(0);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const params=useCallback((page:number)=>{const q=new URLSearchParams({limit:"20",offset:String(page)});if(personId)q.set("person_id",personId);return q.toString();},[personId]);
  useEffect(()=>{
    let active=true;setLoading(true);setError("");
    Promise.all([request<Conflict[]>("/api/facts/conflicts?"+params(offset)),showHistory?request<Decision[]>("/api/facts/conflicts/history?"+params(historyOffset)):Promise.resolve([])]).then(([a,b])=>{if(active){setRows(a);setHistory(b);}}).catch(e=>{if(active)setError(String(e));}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[request,params,revision,offset,historyOffset,showHistory]);
  async function resolve(conflict:Conflict,action:string,previous:string|null,note:string){
    setBusy(true);setError("");
    try{
      await request("/api/facts/conflicts/resolve",{method:"POST",body:JSON.stringify({fact_a_id:conflict.a.id,fact_b_id:conflict.b.id,a_version:conflict.a_version,b_version:conflict.b_version,action,previous_fact_id:previous,note})});
      setOffset(0);setHistoryOffset(0);await onResolved();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const personName=(id:string)=>{const p=people.find(row=>row.id===id);return p?p.first_name+" "+p.last_name:"Person";};
  return <section className="fact-conflicts">
    <div className="panel-head"><div><h3>Mögliche Faktenwidersprüche</h3><p className="muted">Unterschiedliche Werte mit möglicherweise überlappender Gültigkeit, beispielsweise Wohnort oder Arbeitgeber. Mehrere Werte können gleichzeitig richtig sein.</p></div></div>
    {error&&<p className="error" role="alert">{error}</p>}
    {loading?<p className="muted">Widersprüche werden geprüft …</p>:rows.length===0?<p className="muted">Keine offenen Hinweise in dieser Auswahl.</p>:rows.map(c=><article key={c.a.id+c.b.id+c.a_version+c.b_version} className="inbox-item">
      <h4>{personName(c.a.person_id)} · {c.a.predicate}</h4>{c.uncertain_period&&<p className="muted">Mindestens eine Datumsgrenze fehlt. Der Zeitraum könnte sich überschneiden.</p>}
      <div className="fact-conflict-comparison"><FactCard label="A" fact={c.a}/><FactCard label="B" fact={c.b}/></div>
      <ReviewForm conflict={c} busy={busy} onResolve={(action,previous,note)=>resolve(c,action,previous,note)}/>
    </article>)}
    <div className="commitment-actions"><button type="button" className="quiet" disabled={loading||busy||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-20))}>Zurück</button><button type="button" className="quiet" disabled={loading||busy||rows.length<20} onClick={()=>setOffset(v=>v+20)}>Weiter</button><button type="button" className="quiet" disabled={busy} onClick={()=>setShowHistory(v=>!v)}>{showHistory?"Entscheidungsverlauf schließen":"Entscheidungsverlauf anzeigen"}</button></div>
    {showHistory&&<div><h4>Entscheidungsverlauf</h4>{history.length===0?<p className="muted">Keine Entscheidungen gespeichert.</p>:history.map(d=><article className="inbox-item" key={d.id}><strong>{actions[d.action]} · {personName(d.person_id)}</strong><p>{d.before.a.value} / {d.before.b.value}</p><p>A: {states[d.before.a.status]} → {states[d.after.a.status]}, {range(d.after.a)}</p><p>B: {states[d.before.b.status]} → {states[d.after.b.status]}, {range(d.after.b)}</p>{d.note&&<p>{d.note}</p>}<small>{new Date(d.created_at).toLocaleString("de-DE")}</small></article>)}<div className="commitment-actions"><button type="button" disabled={loading||historyOffset===0} onClick={()=>setHistoryOffset(v=>Math.max(0,v-20))}>Zurück</button><button type="button" disabled={loading||history.length<20} onClick={()=>setHistoryOffset(v=>v+20)}>Weiter</button></div></div>}
  </section>;
}
