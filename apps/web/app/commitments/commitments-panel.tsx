"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { Person, Project } from "../page";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type Commitment = { id: string; title: string; notes: string; direction: "outgoing" | "incoming"; status: "open" | "done" | "cancelled"; due_at: string | null; person_id: string | null; project_id: string | null; conversation_id: string | null; source_capture_id?: string | null; source_quote?: string | null };
type Checkpoint = { id: string; title: string; progress: string; blocker: string; next_step: string; resources: string; task_id: string | null; project_id: string | null; archived: boolean; updated_at: string };
type Props = { request: Request; people: Person[]; projects: Project[]; tasks: {id: string; title: string}[] };
const PAGE_SIZE = 100;
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const localDate = (value: string) => { const d = new Date(value); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); };

export function CommitmentsPanel({ request, people, projects, tasks }: Props) {
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [history, setHistory] = useState(false);
  const [archived, setArchived] = useState(false);
  const [editCommitment, setEditCommitment] = useState<Commitment | null>(null);
  const [editCheckpoint, setEditCheckpoint] = useState<Checkpoint | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [commitmentOffset, setCommitmentOffset] = useState(0);
  const [checkpointOffset, setCheckpointOffset] = useState(0);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, w] = await Promise.all([
        request<Commitment[]>(`/api/commitments?status=${history ? "all" : "open"}&offset=${commitmentOffset}`),
        request<Checkpoint[]>(`/api/checkpoints?archived=${archived}&offset=${checkpointOffset}`)
      ]);
      setCommitments(c); setCheckpoints(w); setError("");
    } catch (e) { setError(errorText(e)); }
    finally { setLoading(false); }
  }, [request, history, archived, commitmentOffset, checkpointOffset]);
  useEffect(() => { void load(); }, [load]);
  const name = (id: string | null) => { const person = people.find(p => p.id === id); return person ? [person.first_name, person.last_name].filter(Boolean).join(" ") : ""; };
  const projectName = (id: string | null) => projects.find(p => p.id === id)?.name ?? "";
  const taskName = (id: string | null) => tasks.find(t => t.id === id)?.title ?? "";
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true); setError("");
    try { await action(); await load(); }
    catch(e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  function saveCommitment(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const f = new FormData(form);
    const due = String(f.get("due_at") ?? "");
    void mutate(async () => {
      await request(editCommitment ? `/api/commitments/${editCommitment.id}` : "/api/commitments", {method: editCommitment ? "PUT" : "POST", body: JSON.stringify({
        title: f.get("title"), notes: f.get("notes"), direction: f.get("direction"), person_id: f.get("person_id") || null, project_id: f.get("project_id") || null, conversation_id: editCommitment?.conversation_id ?? null, due_at: due ? new Date(due).toISOString() : null
      })});
      form.reset(); setEditCommitment(null);
    });
  }
  function saveCheckpoint(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); const form = e.currentTarget; const f = new FormData(form);
    void mutate(async () => {
      await request(editCheckpoint ? `/api/checkpoints/${editCheckpoint.id}` : "/api/checkpoints", {method: editCheckpoint ? "PUT" : "POST", body: JSON.stringify({
        title: f.get("title"), progress: f.get("progress"), blocker: f.get("blocker"), next_step: f.get("next_step"), resources: f.get("resources"), task_id: f.get("task_id") || null, project_id: f.get("project_id") || null
      })}); form.reset(); setEditCheckpoint(null);
    });
  }
  return <div className="commitment-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    {loading && <p className="muted" role="status">Einträge werden geladen …</p>}
    <section className="card panel">
      <div className="panel-head"><div><span className="eyebrow">VERSPRECHEN & RÜCKMELDUNGEN</span><h2>Verpflichtungen</h2></div><button type="button" className="quiet" onClick={() => {setHistory(v => !v); setCommitmentOffset(0);}}>{history ? "Nur offene" : "Verlauf anzeigen"}</button></div>
      <form className="person-form" key={editCommitment?.id ?? "new"} onSubmit={saveCommitment}>
        <label>Was wurde vereinbart?<input name="title" required maxLength={240} defaultValue={editCommitment?.title}/></label>
        <label>Richtung<select name="direction" defaultValue={editCommitment?.direction ?? "outgoing"}><option value="outgoing">Ich habe etwas versprochen</option><option value="incoming">Ich warte auf jemanden</option></select></label>
        <label>Person<select name="person_id" defaultValue={editCommitment?.person_id ?? ""}><option value="">Keine Zuordnung</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>
        <label>Projekt<select name="project_id" defaultValue={editCommitment?.project_id ?? ""}><option value="">Kein Projekt</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label>Fällig am<input type="datetime-local" name="due_at" defaultValue={editCommitment?.due_at ? localDate(editCommitment.due_at) : ""}/></label>
        <label>Details<textarea name="notes" maxLength={20000} defaultValue={editCommitment?.notes}/></label>
        <button disabled={busy} type="submit">{editCommitment ? "Änderung speichern" : "Verpflichtung festhalten"}</button>
        {editCommitment && <button type="button" className="quiet" onClick={() => setEditCommitment(null)}>Abbrechen</button>}
      </form>
      {(["outgoing", "incoming"] as const).map(direction => <div key={direction} className="commitment-group"><h3>{direction === "outgoing" ? "Meine Versprechen" : "Ich warte auf"}</h3>
        {!commitments.some(c => c.direction === direction) && <p className="empty">Keine Einträge.</p>}
        {commitments.filter(c => c.direction === direction).map(c => <article className="inbox-item" key={c.id}><strong>{c.title}</strong><p className="muted">{[name(c.person_id), projectName(c.project_id), c.due_at ? new Date(c.due_at).toLocaleString("de-DE") : "Ohne Frist", c.status === "done" ? "Erledigt" : c.status === "cancelled" ? "Abgebrochen" : c.due_at && new Date(c.due_at).getTime() < Date.now() ? "Überfällig" : "Offen"].filter(Boolean).join(" · ")}</p><p style={{whiteSpace:"pre-wrap"}}>{c.notes}</p>{c.source_quote && <p className="muted">Originalzitat: „{c.source_quote}“{c.source_capture_id && <> · <a href={`/inbox#capture-${c.source_capture_id}`}>Erfassung</a></>}</p>}
          <div className="commitment-actions"><button type="button" className="quiet" disabled={busy} onClick={() => setEditCommitment(c)}>Bearbeiten</button>{c.status === "open" ? <><button type="button" disabled={busy} onClick={() => void mutate(() => request(`/api/commitments/${c.id}/status`, {method:"PATCH",body:JSON.stringify({status:"done"})}))}>Erledigt</button><button type="button" className="quiet" disabled={busy} onClick={() => void mutate(() => request(`/api/commitments/${c.id}/status`, {method:"PATCH",body:JSON.stringify({status:"cancelled"})}))}>Abbrechen</button></> : <button type="button" disabled={busy} onClick={() => void mutate(() => request(`/api/commitments/${c.id}/status`, {method:"PATCH",body:JSON.stringify({status:"open"})}))}>Wieder öffnen</button>}</div>
        </article>)}
      </div>)}
      <div className="commitment-actions"><button className="quiet" disabled={loading || !commitmentOffset} onClick={() => setCommitmentOffset(v => Math.max(0,v-PAGE_SIZE))}>Zurück</button><button className="quiet" disabled={loading || commitments.length < PAGE_SIZE} onClick={() => setCommitmentOffset(v => v+PAGE_SIZE)}>Weiter</button></div>
    </section>
    <section className="card panel">
      <div className="panel-head"><div><span className="eyebrow">WIEDEREINSTIEG</span><h2>Wo war ich stehen geblieben?</h2></div><button type="button" className="quiet" onClick={() => {setArchived(v => !v); setCheckpointOffset(0);}}>{archived ? "Aktive anzeigen" : "Archiv anzeigen"}</button></div>
      <form className="person-form" key={editCheckpoint?.id ?? "new"} onSubmit={saveCheckpoint}>
        <label>Woran arbeite ich?<input name="title" required maxLength={240} defaultValue={editCheckpoint?.title}/></label>
        <label>Was ist bereits erledigt?<textarea name="progress" defaultValue={editCheckpoint?.progress} maxLength={20000}/></label>
        <label>Was blockiert mich?<textarea name="blocker" defaultValue={editCheckpoint?.blocker} maxLength={10000}/></label>
        <label>Nächster konkreter Schritt<textarea name="next_step" required defaultValue={editCheckpoint?.next_step} maxLength={10000}/></label>
        <label>Benötigte Dateien, Links oder Hinweise<textarea name="resources" defaultValue={editCheckpoint?.resources} maxLength={20000}/></label>
        <label>Aufgabe<select name="task_id" defaultValue={editCheckpoint?.task_id ?? ""}><option value="">Keine Aufgabe</option>{tasks.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></label>
        <label>Projekt<select name="project_id" defaultValue={editCheckpoint?.project_id ?? ""}><option value="">Kein Projekt</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <button type="submit" disabled={busy}>{editCheckpoint ? "Änderung speichern" : "Arbeitsstand speichern"}</button>{editCheckpoint && <button type="button" className="quiet" onClick={() => setEditCheckpoint(null)}>Abbrechen</button>}
      </form>
      {checkpoints.length === 0 && <p className="empty">Noch keine Arbeitsstände in dieser Ansicht.</p>}
      {checkpoints.map(c => <article className="inbox-item" key={c.id}><h3>{c.title}</h3><p className="muted">{[taskName(c.task_id), projectName(c.project_id), new Date(c.updated_at.endsWith("Z") || /[+-]\d\d:\d\d$/.test(c.updated_at) ? c.updated_at : c.updated_at+"Z").toLocaleString("de-DE")].filter(Boolean).join(" · ")}</p><strong>Nächster Schritt</strong><p style={{whiteSpace:"pre-wrap"}}>{c.next_step}</p>{c.progress && <><strong>Bisher erledigt</strong><p style={{whiteSpace:"pre-wrap"}}>{c.progress}</p></>}{c.blocker && <><strong>Blockade</strong><p style={{whiteSpace:"pre-wrap"}}>{c.blocker}</p></>}{c.resources && <><strong>Ressourcen</strong><p style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{c.resources}</p></>}
      <div className="commitment-actions"><button className="quiet" type="button" disabled={busy} onClick={() => setEditCheckpoint(c)}>Bearbeiten / fortsetzen</button><button type="button" disabled={busy} onClick={() => void mutate(() => request(`/api/checkpoints/${c.id}/archive`, {method:"PATCH",body:JSON.stringify({archived:!c.archived})}))}>{c.archived ? "Wiederherstellen" : "Archivieren"}</button></div></article>)}
      <div className="commitment-actions"><button className="quiet" disabled={loading || !checkpointOffset} onClick={() => setCheckpointOffset(v => Math.max(0,v-PAGE_SIZE))}>Zurück</button><button className="quiet" disabled={loading || checkpoints.length < PAGE_SIZE} onClick={() => setCheckpointOffset(v => v+PAGE_SIZE)}>Weiter</button></div>
    </section>
  </div>;
}
