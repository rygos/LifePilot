"use client";
import {useCallback,useEffect,useRef,useState,type FormEvent} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Step = {id:string;title:string;position:number;archived:boolean;completed:boolean};
export type Routine = {id:string;title:string;weekdays:number[];window_start:string|null;window_end:string|null;archived:boolean;local_date:string;scheduled_today:boolean;window_state:string;steps:Step[]};
type History = {step_id:string;title:string;local_date:string;completed_at:string};
const weekdays = ["Mo","Di","Mi","Do","Fr","Sa","So"];
const windows:Record<string,string> = {anytime:"Jederzeit",upcoming:"Später",active:"Jetzt im Zeitfenster",past:"Zeitfenster vorbei",not_scheduled:"Heute nicht geplant"};
const time = (s:string|null)=>s?.slice(0,5)??"";
const root = "/api/routines";
function ScheduleForm({routine,busy,onSave,onCancel}:{routine?:Routine;busy:boolean;onSave:(body:unknown)=>Promise<void>;onCancel?:()=>void}) {
  const [days,setDays]=useState(routine?.weekdays??[0,1,2,3,4,5,6]);
  const [title,setTitle]=useState(routine?.title??"");
  const [start,setStart]=useState(time(routine?.window_start??null));
  const [end,setEnd]=useState(time(routine?.window_end??null));
  const [steps,setSteps]=useState("");
  function submit(e:FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const body={title,weekdays:days,window_start:start||null,window_end:end||null,...(!routine?{steps:steps.split("\n").map(s=>s.trim()).filter(Boolean).map(title=>({title}))}:{})};
    void onSave(body);
  }
  return <form className="person-form" onSubmit={submit}>
    <label>Name<input required maxLength={240} value={title} onChange={e=>setTitle(e.target.value)}/></label>
    <fieldset><legend>Wochentage</legend><div className="commitment-actions">{weekdays.map((day,i)=><label key={day}><input type="checkbox" checked={days.includes(i)} onChange={e=>setDays(old=>e.target.checked?[...old,i]:old.filter(d=>d!==i))}/>{day}</label>)}</div></fieldset>
    <label>Von (optional)<input type="time" value={start} required={!!end} onChange={e=>setStart(e.target.value)}/></label>
    <label>Bis (optional)<input type="time" value={end} required={!!start} onChange={e=>setEnd(e.target.value)}/></label>
    {!routine&&<label>Schritte (je einer pro Zeile)<textarea required maxLength={7500} value={steps} onChange={e=>setSteps(e.target.value)} placeholder={"Wasser trinken\nTagesplanung ansehen"}/></label>}
    <div className="commitment-actions"><button type="submit" disabled={busy||!days.length}>{routine?"Änderungen speichern":"Routine anlegen"}</button>{onCancel&&<button type="button" className="quiet" onClick={onCancel}>Abbrechen</button>}</div>
  </form>;
}
export function RoutinesPanel({request,onSaved}:{request:Request;onSaved:()=>Promise<void>}) {
  const [rows,setRows]=useState<Routine[]>([]);
  const [all,setAll]=useState(false);
  const [archived,setArchived]=useState(false);
  const [creating,setCreating]=useState(false);
  const [editing,setEditing]=useState("");
  const [history,setHistory]=useState<{id:string;items:History[]}|null>(null);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const generation=useRef(0);
  const load=useCallback(async()=>{
    const version=++generation.current;
    const result=await request<Routine[]>(root+`?today_only=${!all}&include_archived=${all&&archived}`);
    if(version===generation.current)setRows(result);
  },[request,all,archived]);
  useEffect(()=>{
    let live=true;
    setLoading(true);
    load().catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});
    const refresh=()=>{if(document.visibilityState==="visible")void load().catch(e=>setError(String(e)));};
    const timer=window.setInterval(refresh,60000);
    document.addEventListener("visibilitychange",refresh);
    return()=>{live=false;generation.current++;window.clearInterval(timer);document.removeEventListener("visibilitychange",refresh);};
  },[load]);
  async function run(action:()=>Promise<unknown>,after?:()=>void) {
    setBusy(true);setError("");
    try {await action();after?.();await load();await onSaved();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const mutate=(path:string,method:string,body:unknown)=>request(path,{method,body:JSON.stringify(body)});
  return <section className="card panel routines-panel" id="routines">
    <div className="panel-head"><div><span className="eyebrow">DEIN TAGESABLAUF</span><h2>Routinen</h2></div><button type="button" className="quiet" onClick={()=>{setAll(v=>!v);setEditing("");setHistory(null);}}>{all?"Nur heute":"Alle verwalten"}</button></div>
    <div className="commitment-actions"><button type="button" className="quiet" onClick={()=>setCreating(v=>!v)}>{creating?"Schließen":"Neue Routine"}</button>{all&&<label><input type="checkbox" checked={archived} onChange={e=>setArchived(e.target.checked)}/> Archivierte anzeigen</label>}<button type="button" className="quiet" disabled={busy} onClick={()=>void load().catch(e=>setError(String(e)))}>Aktualisieren</button></div>
    {error&&<p className="error" role="alert">{error}</p>}
    {creating&&<ScheduleForm busy={busy} onSave={body=>run(()=>mutate(root,"POST",body),()=>setCreating(false))} onCancel={()=>setCreating(false)}/>}
    {loading?<p className="muted">Routinen werden geladen …</p>:rows.length===0?<p className="empty">{all?"Noch keine Routinen.":"Heute sind keine Routinen geplant."}</p>:rows.map(r=>{
      const active=r.steps.filter(s=>!s.archived);
      const done=active.filter(s=>s.completed).length;
      return <article className="inbox-item" key={r.id}>
        <h3>{r.title}</h3><p className="muted">{r.weekdays.map(d=>weekdays[d]).join(" · ")}{r.window_start?" · "+time(r.window_start)+"–"+time(r.window_end):""} · {r.archived?"Archiviert":windows[r.window_state]}</p>
        {r.scheduled_today&&<><p>{done} von {active.length} Schritten erledigt</p><progress max={active.length||1} value={done} aria-label="Routinenfortschritt"/></>}
        {r.steps.map(s=><div className="list-item" key={s.id}><label><input type="checkbox" checked={s.completed} disabled={busy||!r.scheduled_today||s.archived} onChange={e=>void run(()=>mutate(`${root}/${r.id}/steps/${s.id}/completion`,"PATCH",{local_date:r.local_date,completed:e.target.checked}))}/><span style={{textDecoration:s.completed?"line-through":"none"}}>{s.title}{s.archived?" (archiviert)":""}</span></label>{all&&<button type="button" className="quiet" disabled={busy} onClick={()=>void run(()=>mutate(`${root}/${r.id}/steps/${s.id}/archive`,"PATCH",{archived:!s.archived}))}>{s.archived?"Wiederherstellen":"Archivieren"}</button>}</div>)}
        {all&&<><div className="commitment-actions"><button type="button" className="quiet" onClick={()=>setEditing(editing===r.id?"":r.id)}>Bearbeiten</button><button type="button" className="quiet" disabled={busy} onClick={()=>void run(()=>mutate(`${root}/${r.id}/archive`,"PATCH",{archived:!r.archived}))}>{r.archived?"Wiederherstellen":"Routine archivieren"}</button><button type="button" className="quiet" disabled={busy} onClick={()=>{if(history?.id===r.id)setHistory(null);else void run(async()=>setHistory({id:r.id,items:await request<History[]>(`${root}/${r.id}/history`)}));}}>Verlauf</button></div>
        {editing===r.id&&<ScheduleForm key={r.id} routine={r} busy={busy} onSave={body=>run(()=>mutate(`${root}/${r.id}`,"PUT",body),()=>setEditing(""))} onCancel={()=>setEditing("")}/>}
        {!r.archived&&<form className="person-form" onSubmit={e=>{e.preventDefault();const f=e.currentTarget;const title=new FormData(f).get("title");void run(()=>mutate(`${root}/${r.id}/steps`,"POST",{title}),()=>f.reset());}}><label>Weiterer Schritt<input name="title" maxLength={240} required/></label><button type="submit" disabled={busy}>Hinzufügen</button></form>}
        {history?.id===r.id&&<div><h4>Erledigungen der letzten 30 Tage</h4>{history.items.length?history.items.map(h=><p key={h.step_id+h.local_date}>{h.local_date} · {h.title}</p>):<p className="muted">Noch keine Erledigungen gespeichert.</p>}</div>}</>}
      </article>;
    })}
  </section>;
}
