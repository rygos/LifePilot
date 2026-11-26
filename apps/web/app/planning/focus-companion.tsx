"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type State = "on_track" | "distracted" | "blocked" | "skip";
type CheckIn = {id: string; state: State; note: string; next_step: string; created_at: string};
type Companion = {interval_minutes: number | null; goal: string; next_due_at: string | null; suggested_next_step: string; checkins: CheckIn[]};
type Prefill = {progress: string; blocker: string; next_step: string};
const labels: Record<State,string> = {on_track:"Ich bin dran",distracted:"Abgelenkt",blocked:"Ich komme nicht weiter",skip:"Übersprungen"};
const guidance: Record<Exclude<State,"skip">,string> = {
  on_track:"Bleib bei einem Schritt. Du musst nicht alles in diesem Zeitblock erledigen.",
  distracted:"Halte den anderen Gedanken kurz fest. Kehre dann zum kleinsten nächsten Schritt zurück.",
  blocked:"Was fehlt dir gerade? Wähle einen kleinen Schritt, den du trotzdem machen kannst, oder sichere deinen Arbeitsstand."
};
function requestId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2,"0")).join("");
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join("-");
}

export function FocusCompanion({request, sessionId, now, remaining, onInterrupt, disabled}: {request: Request; sessionId: string; now: number; remaining: number; onInterrupt: (prefill: Prefill) => void; disabled: boolean}) {
  const [data,setData] = useState<Companion|null>(null);
  const [choice,setChoice] = useState<Exclude<State,"skip">>("on_track");
  const [note,setNote] = useState("");
  const [nextStep,setNextStep] = useState("");
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState("");
  const pending = useRef<{request_id:string; state:State; note:string; next_step:string}|null>(null);
  const path = `/api/focus/${sessionId}`;
  const refresh = useCallback(async () => {
    try { setData(await request<Companion>(path+"/companion"));if(!pending.current)setError(""); }
    catch(e) {setError(e instanceof Error?e.message:String(e));}
  },[request,path]);
  useEffect(()=>{void refresh();const visible=()=>{if(document.visibilityState==="visible")void refresh();};document.addEventListener("visibilitychange",visible);return()=>document.removeEventListener("visibilitychange",visible);},[refresh]);
  const due = !!data?.next_due_at && remaining > 0 && Date.parse(data.next_due_at) <= now;
  async function save(state:State) {
    if (busy || disabled) return;
    setBusy(true);setError("");
    const payload = pending.current ?? {request_id:requestId(),state,note:state==="skip"?"":note,next_step:state==="skip"?"":nextStep};
    pending.current=payload;
    try {
      setData(await request<Companion>(path+"/checkins",{method:"POST",body:JSON.stringify(payload)}));
      pending.current=null;setNote("");setNextStep("");setChoice("on_track");
    } catch(e) {setError(e instanceof Error?e.message:String(e));}
    finally {setBusy(false);}
  }
  function submit(e:FormEvent<HTMLFormElement>) {e.preventDefault();void save(choice);}
  const last = data?.checkins.find(c=>c.state!=="skip");
  return <div className="focus-companion">
    <h3>Virtueller Arbeitsbegleiter</h3>
    <p className="muted">Freiwillige Check-ins, ohne Leistungsbewertung oder Überwachung.</p>
    {error && <p className="error" role="alert">{error} <button type="button" className="quiet" disabled={busy||disabled} onClick={()=>void (pending.current?save(pending.current.state):refresh())}>Erneut versuchen</button></p>}
    {!data ? <p className="muted">Arbeitsbegleiter wird geladen …</p> : <>
      {data.goal && <p><strong>Ziel für diese Sitzung:</strong> {data.goal}</p>}
      {data.suggested_next_step && <p><strong>Möglicher nächster Schritt:</strong> {data.suggested_next_step}</p>}
      <p role="status" className={due?"notice":"muted"}>{due?"Zeit für einen kurzen Check-in: Wie läuft es gerade?":data.next_due_at&&remaining>0?"Nächster Check-in um "+new Date(data.next_due_at).toLocaleTimeString("de-DE",{hour:"2-digit",minute:"2-digit"}):"Kein weiterer geplanter Check-in in diesem Zeitblock."}</p>
      <form className="person-form" onSubmit={submit}>
        <label>Wie läuft es gerade?<select value={choice} disabled={busy||!!pending.current||disabled} onChange={e=>setChoice(e.target.value as Exclude<State,"skip">)}>{(["on_track","distracted","blocked"] as const).map(s=><option key={s} value={s}>{labels[s]}</option>)}</select></label>
        <p className="muted">{guidance[choice]}</p>
        <label>Kurze Notiz (optional)<textarea maxLength={4000} value={note} disabled={busy||!!pending.current||disabled} onChange={e=>setNote(e.target.value)}/></label>
        <label>Nächster konkreter Schritt (optional)<textarea maxLength={1000} value={nextStep} disabled={busy||!!pending.current||disabled} onChange={e=>setNextStep(e.target.value)}/></label>
        <div className="commitment-actions"><button type="submit" disabled={busy||disabled||!!pending.current}>Check-in speichern</button><button type="button" className="quiet" disabled={busy||disabled||!!pending.current} onClick={()=>void save("skip")}>Überspringen</button>{choice==="blocked"&&<button type="button" className="quiet" disabled={busy||disabled||!!pending.current} onClick={()=>onInterrupt({progress:"",blocker:note,next_step:nextStep||data.suggested_next_step})}>Arbeitsstand sichern</button>}</div>
      </form>
      {last&&<p className="muted">Letzter Check-in: {labels[last.state]}{last.note?" · "+last.note:""}{last.next_step?" · Weiter: "+last.next_step:""}</p>}
    </>}
  </div>;
}
