"use client";

import { useState, type FormEvent } from "react";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type Task = {id: string; title: string; estimated_minutes?: number | null; mental_effort?: string | null; start_friction?: string | null; work_context?: string | null; next_step?: string | null};
type Result = {recommended: {task: Task; reason: string}[]; needs_details: Task[]};
const effortOptions = <><option value="">Nicht angegeben</option><option value="low">Niedrig</option><option value="medium">Mittel</option><option value="high">Hoch</option></>;
const contextOptions = <><option value="any">Überall / flexibel</option><option value="computer">Computer</option><option value="phone">Handy</option><option value="home">Zuhause</option><option value="outside">Unterwegs</option></>;

export function NextActionPanel({request, tasks, onSaved}: {request: Request; tasks: Task[]; onSaved: () => Promise<void>}) {
  const [minutes, setMinutes] = useState("15");
  const [energy, setEnergy] = useState("medium");
  const [context, setContext] = useState("any");
  const [result, setResult] = useState<Result | null>(null);
  const [editing, setEditing] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const task = tasks.find(t => t.id === editing);
  async function find(e?: FormEvent) {
    e?.preventDefault(); setBusy(true); setError(""); setResult(null);
    try { setResult(await request<Result>(`/api/planning/next-actions?minutes=${minutes}&energy=${energy}&context=${context}`)); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const f = new FormData(e.currentTarget); if (!task) return;
    setBusy(true); setError("");
    try {
      await request(`/api/tasks/${task.id}/planning`, {method: "PATCH", body: JSON.stringify({
        estimated_minutes: f.get("estimated_minutes") ? Number(f.get("estimated_minutes")) : null,
        mental_effort: f.get("mental_effort") || null, start_friction: f.get("start_friction") || null,
        work_context: f.get("work_context") || null, next_step: f.get("next_step") || null
      })});
      setEditing(""); setResult(null); await onSaved();
    } catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <section className="card panel next-action-panel">
    <div className="panel-head"><div><span className="eyebrow">EIN SCHRITT GENÜGT</span><h2>Was soll ich jetzt machen?</h2></div></div>
    <form className="person-form" onSubmit={find}>
      <label>Verfügbare Minuten<input type="number" min="1" max="1440" required value={minutes} onChange={e => {setMinutes(e.target.value);setResult(null);}}/></label>
      <label>Energie<select value={energy} onChange={e => {setEnergy(e.target.value);setResult(null);}}><option value="low">Wenig</option><option value="medium">Normal</option><option value="high">Viel</option></select></label>
      <label>Kontext<select value={context} onChange={e => {setContext(e.target.value);setResult(null);}}>{contextOptions}</select></label>
      <button type="submit" disabled={busy}>Passende Aufgaben finden</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <h3>Deine nächsten Schritte</h3>
      {result.recommended.length === 0 && <p className="empty">Keine ausreichend beschriebene Aufgabe passt gerade. Du kannst mehr Zeit wählen oder eine Aufgabe ergänzen.</p>}
      {result.recommended.map(({task, reason}, i) => <article className="inbox-item" key={task.id}><strong>{i === 0 ? "Empfehlung: " : ""}{task.title}</strong><p className="muted">{reason}</p><p>{task.next_step || "Lege zunächst einen konkreten nächsten Schritt fest."}</p><button type="button" className="quiet" onClick={() => setEditing(task.id)}>Planung bearbeiten</button></article>)}
      {result.needs_details.length > 0 && <><h3>Noch nicht ausreichend eingeschätzt</h3>{result.needs_details.map(t => <div className="list-item" key={t.id}><span>{t.title}</span><button type="button" className="quiet" onClick={() => setEditing(t.id)}>Ergänzen</button></div>)}</>}
    </div>}
    <div className="person-form"><label>Aufgabenplanung bearbeiten<select value={editing} onChange={e => setEditing(e.target.value)}><option value="">Aufgabe auswählen</option>{tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label></div>
    {task && <form className="person-form" key={task.id} onSubmit={save}>
      <label>Geschätzte Dauer (Minuten)<input type="number" name="estimated_minutes" min="1" max="1440" defaultValue={task.estimated_minutes ?? ""}/></label>
      <label>Mentaler Aufwand<select name="mental_effort" defaultValue={task.mental_effort ?? ""}>{effortOptions}</select></label>
      <label>Einstiegshürde<select name="start_friction" defaultValue={task.start_friction ?? ""}>{effortOptions}</select></label>
      <label>Benötigter Kontext<select name="work_context" defaultValue={task.work_context ?? ""}><option value="">Nicht angegeben</option>{contextOptions}</select></label>
      <label>Nächster konkreter Schritt<textarea name="next_step" maxLength={5000} defaultValue={task.next_step ?? ""}/></label>
      <button type="submit" disabled={busy}>Planung speichern</button><button type="button" className="quiet" onClick={() => setEditing("")}>Abbrechen</button>
    </form>}
  </section>;
}
