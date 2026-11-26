"use client";
import { useEffect, useState, type FormEvent } from "react";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type DraftStep = {title: string; estimated_minutes: number | null};
type Step = DraftStep & {id: string; position: number; completed_at: string | null};
export function TaskStepsPanel({request, taskId}: {request: Request; taskId: string}) {
  const path = `/api/tasks/${taskId}/steps`;
  const [steps,setSteps] = useState<Step[]>([]);
  const [draft,setDraft] = useState<DraftStep[]>([]);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const [loaded,setLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    request<Step[]>(path).then(rows => {if(live){setSteps(rows);setLoaded(true);}}).catch(e => {if(live)setError(String(e));});
    return () => {live=false;};
  },[path,request]);
  async function run(action: () => Promise<void>) {
    setBusy(true);setError("");
    try {await action();} catch(e) {setError(e instanceof Error ? e.message : String(e));} finally {setBusy(false);}
  }
  async function reload() {setSteps(await request<Step[]>(path));setLoaded(true);}
  function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();const form=e.currentTarget;const f=new FormData(form);
    void run(async()=>{await request(path,{method:"POST",body:JSON.stringify({steps:[{title:f.get("title"),estimated_minutes:f.get("minutes")?Number(f.get("minutes")):null}]})});form.reset();await reload();});
  }
  const done=steps.filter(s=>s.completed_at).length;
  return <div className="task-steps-panel">
    <h3>Aufgabe in kleine Schritte zerlegen</h3>
    {error && <p role="alert" className="error">{error}</p>}
    {loaded && <><p className="muted">{done} von {steps.length} Schritten erledigt</p>{steps.length>0 && <progress value={done} max={steps.length} aria-label="Aufgabenfortschritt"/>}
      {steps.map(s=><label className="list-item" key={s.id}><input type="checkbox" checked={!!s.completed_at} disabled={busy} onChange={e=>{const completed=e.target.checked;void run(async()=>{const updated=await request<Step>(`${path}/${s.id}`,{method:"PATCH",body:JSON.stringify({completed})});setSteps(rows=>rows.map(row=>row.id===updated.id?updated:row));});}}/><span style={{textDecoration:s.completed_at?"line-through":"none"}}>{s.title}{s.estimated_minutes && <small>{s.estimated_minutes} Min. (Schätzung)</small>}</span></label>)}
    </>}
    <form className="person-form" onSubmit={add}><label>Eigener Teilschritt<input name="title" required maxLength={240}/></label><label>Geschätzte Minuten<input name="minutes" type="number" min="1" max="180"/></label><button type="submit" disabled={busy||!loaded}>Schritt hinzufügen</button></form>
    <button type="button" className="quiet" disabled={busy||!loaded} onClick={()=>void run(async()=>{setDraft((await request<{steps:DraftStep[]}>(path+"/draft",{method:"POST"})).steps);})}>KI-Vorschläge erstellen</button>
    {draft.length>0 && <div><h4>Vorschau – noch nicht gespeichert</h4><p className="muted">Prüfe und bearbeite die vorgeschlagenen Schritte. Zeitangaben sind Schätzungen.</p>
      <form className="person-form" onSubmit={e=>{e.preventDefault();void run(async()=>{await request(path,{method:"POST",body:JSON.stringify({steps:draft})});setDraft([]);await reload();});}}>
        {draft.map((s,i)=><div key={i}><label>Schritt {i+1}<input required maxLength={240} value={s.title} onChange={e=>setDraft(rows=>rows.map((row,j)=>i===j?{...row,title:e.target.value}:row))}/></label><label>Minuten<input type="number" min="1" max="180" value={s.estimated_minutes??""} onChange={e=>setDraft(rows=>rows.map((row,j)=>i===j?{...row,estimated_minutes:e.target.value?Number(e.target.value):null}:row))}/></label><button type="button" className="quiet" disabled={busy} onClick={()=>setDraft(rows=>rows.filter((_,j)=>i!==j))}>Vorschlag entfernen</button></div>)}
        <button disabled={busy} type="submit">Geprüfte Schritte übernehmen</button><button disabled={busy} type="button" className="quiet" onClick={()=>setDraft([])}>Verwerfen</button>
      </form></div>}
  </div>;
}
