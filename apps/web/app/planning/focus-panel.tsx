"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type Task = { id: string; title: string; status?: string; next_step?: string | null; estimated_minutes?: number | null };
type Focus = { id: string; task_id: string | null; task_title: string; planned_minutes: number; started_at: string; ended_at: string | null; elapsed_seconds: number | null; outcome: "finished" | "interrupted" | null; checkpoint_id: string | null };
const formatTime = (seconds: number) => [Math.floor(seconds / 60), seconds % 60].map(n => String(n).padStart(2, "0")).join(":");

export function FocusPanel({request, tasks, onSaved}: {request: Request; tasks: Task[]; onSaved: () => Promise<void>}) {
  const [active, setActive] = useState<Focus | null>(null);
  const [history, setHistory] = useState<Focus[]>([]);
  const [taskId, setTaskId] = useState("");
  const [minutes, setMinutes] = useState("25");
  const [now, setNow] = useState(Date.now());
  const [interrupt, setInterrupt] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const [session, rows] = await Promise.all([request<Focus | null>("/api/focus/active"), request<Focus[]>("/api/focus/history?limit=10")]);
      setActive(session); setHistory(rows); setNow(Date.now()); setError("");
    } catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setLoading(false); }
  }, [request]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    const refresh = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", refresh);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [active, load]);
  const elapsed = active ? Math.max(0, Math.floor((now - Date.parse(active.started_at)) / 1000)) : 0;
  const remaining = active ? Math.max(0, active.planned_minutes * 60 - elapsed) : 0;
  async function start(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const session = await request<Focus>("/api/focus/start", {method:"POST",body:JSON.stringify({task_id:taskId,planned_minutes:Number(minutes)})});
      setActive(session); setNow(Date.now()); setInterrupt(false);
    } catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function end(outcome: "finished" | "interrupted", checkpoint?: Record<string, string>) {
    if (!active) return;
    setBusy(true); setError("");
    try {
      await request<Focus>(`/api/focus/${active.id}/end`, {method:"POST",body:JSON.stringify({outcome,checkpoint:checkpoint ?? null})});
      setActive(null); setInterrupt(false); await load(); await onSaved();
    } catch(e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  function saveInterruption(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const data = new FormData(e.currentTarget);
    void end("interrupted", Object.fromEntries(["progress","blocker","next_step","resources"].map(k => [k,String(data.get(k) ?? "")])));
  }
  return <section className="card panel focus-panel">
    <div className="panel-head"><div><span className="eyebrow">ZEIT FÜR EINE SACHE</span><h2>Fokusmodus</h2></div><button className="quiet" type="button" disabled={busy} onClick={() => void load()}>Aktualisieren</button></div>
    {error && <p className="error" role="alert">{error}</p>}
    {loading ? <p className="muted">Fokusstatus wird geladen …</p> : active ? <>
      <h3>{active.task_title}</h3><p className="muted">{tasks.find(t => t.id === active.task_id)?.next_step || "Konzentriere dich auf einen konkreten Schritt."}</p>
      <div className="focus-clock" aria-label="Verbleibende Zeit">{formatTime(remaining)}</div>
      <progress aria-label="Fokusfortschritt" max={active.planned_minutes * 60} value={Math.min(elapsed, active.planned_minutes * 60)}/>
      <p className="muted" role="status">{remaining === 0 ? "Dein Zeitblock ist abgelaufen. Beende die Sitzung, sobald du fertig bist." : "Die Sitzung läuft. Du kannst die Seite neu laden und später fortsetzen."} Verstrichen: {formatTime(elapsed)}</p>
      <div className="commitment-actions"><button type="button" disabled={busy} onClick={() => void end("finished")}>Fokus beenden</button><button type="button" className="quiet" disabled={busy} onClick={() => setInterrupt(v => !v)}>Unterbrechen</button></div>
      {interrupt && <form className="person-form" onSubmit={saveInterruption}>
        <label>Was ist erledigt?<textarea name="progress" maxLength={20000}/></label><label>Was blockiert mich?<textarea name="blocker" maxLength={10000}/></label>
        <label>Nächster Schritt<textarea name="next_step" required maxLength={10000} defaultValue={tasks.find(t => t.id === active.task_id)?.next_step ?? ""}/></label>
        <label>Benötigte Dateien, Links oder Hinweise<textarea name="resources" maxLength={20000}/></label>
        <button type="submit" disabled={busy}>Unterbrechen und Arbeitsstand speichern</button><button type="button" className="quiet" disabled={busy} onClick={() => void end("interrupted")}>Ohne Arbeitsstand beenden</button>
      </form>}
    </> : <form className="person-form" onSubmit={start}>
      <label>Aufgabe<select required value={taskId} onChange={e => {const id=e.target.value;setTaskId(id);const estimate=tasks.find(t => t.id===id)?.estimated_minutes;if(estimate) setMinutes(String(Math.min(180,estimate)));}}><option value="">Aufgabe auswählen</option>{tasks.filter(t => !t.status || t.status==="open").map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
      <label>Fokuszeit (Minuten)<input type="number" required min={1} max={180} value={minutes} onChange={e => setMinutes(e.target.value)}/></label><button type="submit" disabled={busy || !taskId}>Fokus starten</button>
    </form>}
    {history.length > 0 && <div><h3>Letzte Fokussitzungen</h3>{history.map(row => <div className="list-item" key={row.id}><span>{row.task_title}<small>{new Date(row.started_at).toLocaleString("de-DE")} · {formatTime(row.elapsed_seconds ?? 0)} / {row.planned_minutes} Min. · {row.outcome === "interrupted" ? "Unterbrochen" : "Beendet"}</small></span>{row.checkpoint_id && <a href="/commitments">Arbeitsstand</a>}</div>)}</div>}
  </section>;
}
