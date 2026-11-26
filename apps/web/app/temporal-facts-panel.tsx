"use client";
import {useCallback,useEffect,useRef,useState,type FormEvent} from "react";

import { FactConflictsPanel } from "./fact-conflicts-panel";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Person = {id:string;first_name:string;last_name:string};
type Status = "proposed"|"confirmed"|"rejected";
type Fact = {id:string;person_id:string;predicate:string;value:string;valid_from:string|null;valid_until:string|null;confidence:"low"|"medium"|"high";status:Status;source_note:string;source_capture_id:string|null;source_quote:string|null};
const statusLabel = {proposed:"Unbestätigt",confirmed:"Bestätigt",rejected:"Verworfen"};
const confidenceLabel = {low:"Niedrig",medium:"Mittel",high:"Hoch"};
export function TemporalFactsPanel({request,people,personId}:{request:Request;people:Person[];personId?:string}) {
  const [revision,setRevision]=useState(0);
  const [subject,setSubject]=useState(personId??"");
  const [status,setStatus]=useState("");
  const [asOf,setAsOf]=useState("");
  const [predicate,setPredicate]=useState("");
  const [offset,setOffset]=useState(0);
  const [rows,setRows]=useState<Fact[]>([]);
  const [creating,setCreating]=useState(false);
  const [ending,setEnding]=useState("");
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const generation=useRef(0);
  const load=useCallback(async()=>{
    const version=++generation.current;
    const query=new URLSearchParams({limit:"50",offset:String(offset)});
    if(subject)query.set("person_id",subject);
    if(status)query.set("status",status);
    if(asOf)query.set("as_of",asOf);
    if(predicate.trim())query.set("predicate",predicate.trim());
    const list=await request<Fact[]>("/api/facts?"+query);
    if(version===generation.current)setRows(list);
  },[request,subject,status,asOf,predicate,offset]);
  useEffect(()=>{let live=true;setLoading(true);setError("");load().catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;generation.current++;};},[load]);
  async function run(action:()=>Promise<unknown>,after?:()=>void){
    setBusy(true);setError("");
    try{await action();after?.();setRevision(v=>v+1);await load();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  function create(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;const fields=new FormData(form);
    const body={person_id:fields.get("person_id"),predicate:fields.get("predicate"),value:fields.get("value"),valid_from:fields.get("valid_from")||null,valid_until:fields.get("valid_until")||null,confidence:fields.get("confidence"),source_note:fields.get("source_note")||"",source_capture_id:fields.get("source_capture_id")||null,source_quote:fields.get("source_quote")||null};
    void run(()=>request("/api/facts",{method:"POST",body:JSON.stringify(body)}),()=>{form.reset();setCreating(false);setOffset(0);setStatus("");setAsOf("");setPredicate("");if(!personId)setSubject(String(body.person_id));});
  }
  function review(fact:Fact,next:Status){
    if(!window.confirm("Fakt als "+statusLabel[next]+" markieren?"))return;
    void run(()=>request("/api/facts/"+fact.id+"/status",{method:"PATCH",body:JSON.stringify({status:next})}));
  }
  return <section className="card panel temporal-facts-panel">
    <div className="panel-head"><div><span className="eyebrow">GEDÄCHTNIS MIT ZEITBEZUG</span><h2>Zeitliche Fakten</h2></div><button type="button" className="quiet" onClick={()=>setCreating(v=>!v)}>{creating?"Schließen":"Fakt hinzufügen"}</button></div>
    <p className="muted">Fakten beginnen als unbestätigte Vorschläge. Unbekannte Datumsgrenzen sind keine Belege für Gültigkeit. Das Enddatum ist exklusiv (ab diesem Tag gilt der Fakt nicht mehr). Bestehende Profilfelder werden nicht automatisch verändert.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <FactConflictsPanel key={subject||"all"} request={request} people={people} personId={subject||undefined} revision={revision} onResolved={async()=>{setRevision(v=>v+1);await load();}}/>
    {creating&&<form className="person-form" onSubmit={create}>
      <label>Person<select name="person_id" required defaultValue={subject}><option value="">Auswählen</option>{people.filter(p=>!personId||p.id===personId).map(p=><option value={p.id} key={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>
      <label>Eigenschaft<input name="predicate" required maxLength={120} placeholder="z. B. Wohnort, Arbeitgeber, Hobby"/></label>
      <label>Wert<textarea name="value" required maxLength={5000}/></label>
      <label>Gültig ab (optional)<input name="valid_from" type="date"/></label>
      <label>Gültig bis, exklusiv (optional)<input name="valid_until" type="date"/></label>
      <label>Vertrauen<select name="confidence" defaultValue="medium"><option value="low">Niedrig</option><option value="medium">Mittel</option><option value="high">Hoch</option></select></label>
      <label>Quellenbeschreibung<textarea name="source_note" maxLength={5000} placeholder="Woher weißt du das?"/></label>
      <details><summary>Originalerfassung verknüpfen</summary><label>Erfassungs-ID<input name="source_capture_id"/></label><label>Wörtliches Quellenzitat<textarea name="source_quote" maxLength={4000}/></label></details>
      <button disabled={busy}>Als Vorschlag speichern</button>
    </form>}
    <div className="person-form">
      {!personId&&<label>Person<select value={subject} onChange={e=>{setSubject(e.target.value);setOffset(0);}}><option value="">Alle</option>{people.map(p=><option value={p.id} key={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>}
      <label>Eigenschaft<input value={predicate} onChange={e=>{setPredicate(e.target.value);setOffset(0);}} placeholder="Alle Eigenschaften"/></label>
      <label>Status<select value={status} onChange={e=>{setStatus(e.target.value);setOffset(0);}}><option value="">Alle</option>{Object.entries(statusLabel).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
      <label>Möglicherweise gültig am<input type="date" value={asOf} onChange={e=>{setAsOf(e.target.value);setOffset(0);}}/></label>
    </div>
    {loading?<p className="muted">Fakten werden geladen …</p>:rows.length===0?<p className="muted">Keine passenden Fakten.</p>:rows.map(f=>{
      const person=people.find(p=>p.id===f.person_id);
      return <article className="inbox-item" key={f.id}><h3>{f.predicate}: {f.value}</h3>
        {!personId&&<p>{person?person.first_name+" "+person.last_name:"Person"}</p>}
        <p>{f.valid_from??"Beginn unbekannt"} – {f.valid_until?f.valid_until+" (exklusiv)":"Ende offen/unbekannt"}</p>
        <p className="muted">{statusLabel[f.status]} · Vertrauen: {confidenceLabel[f.confidence]}</p>
        {f.source_note&&<p style={{whiteSpace:"pre-wrap"}}>Quelle: {f.source_note}</p>}{f.source_quote&&<blockquote>{f.source_quote}</blockquote>}
        {f.source_capture_id&&<small>Quellerfassung: {f.source_capture_id}</small>}
        <div className="commitment-actions">{f.status!=="confirmed"&&<button type="button" disabled={busy} onClick={()=>review(f,"confirmed")}>Bestätigen</button>}{f.status!=="rejected"&&<button type="button" className="quiet" disabled={busy} onClick={()=>review(f,"rejected")}>Verwerfen</button>}{f.status==="rejected"&&<button type="button" className="quiet" disabled={busy} onClick={()=>review(f,"proposed")}>Erneut prüfen</button>}{f.status==="confirmed"&&!f.valid_until&&<button type="button" className="quiet" onClick={()=>setEnding(ending===f.id?"":f.id)}>Gültigkeit beenden</button>}</div>
        {ending===f.id&&<form className="person-form" onSubmit={e=>{e.preventDefault();const date=new FormData(e.currentTarget).get("until");void run(()=>request("/api/facts/"+f.id+"/end",{method:"PATCH",body:JSON.stringify({valid_until:date})}),()=>setEnding(""));}}><label>Ab welchem Tag nicht mehr gültig?<input type="date" name="until" required/></label><button disabled={busy}>Enddatum speichern</button></form>}
      </article>;
    })}
    <div className="commitment-actions"><button type="button" className="quiet" disabled={offset===0||loading||busy} onClick={()=>setOffset(v=>Math.max(0,v-50))}>Zurück</button><button type="button" className="quiet" disabled={rows.length<50||loading||busy} onClick={()=>setOffset(v=>v+50)}>Weiter</button></div>
  </section>;
}
