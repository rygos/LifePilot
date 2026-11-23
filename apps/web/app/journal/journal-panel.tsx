"use client";

import { type ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";
import type { Event, Person, Project } from "../page";
import { PersonPicker } from "../people/person-picker";

type JournalMood = "freudig" | "ruhig" | "neutral" | "traurig" | "gestresst" | "dankbar" | "energiegeladen";
type JournalEntry = { id: string; entry_date: string; title: string; content: string; mood: JournalMood | null; person_ids: string[]; project_ids: string[]; event_ids: string[]; created_at: string; updated_at: string };
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;

const moods: { value: JournalMood; label: string }[] = [
  { value: "freudig", label: "Freudig" },
  { value: "ruhig", label: "Ruhig" },
  { value: "neutral", label: "Neutral" },
  { value: "traurig", label: "Traurig" },
  { value: "gestresst", label: "Gestresst" },
  { value: "dankbar", label: "Dankbar" },
  { value: "energiegeladen", label: "Energiegeladen" },
];

function localDate(): string {
  const date = new Date();
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 10);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date(`${value}T12:00:00`));
}

function JournalEntryForm({ entry, people, projects, events, busy, onSave, onCancel }: { entry?: JournalEntry; people: Person[]; projects: Project[]; events: Event[]; busy: boolean; onSave: (event: FormEvent<HTMLFormElement>, entryId?: string) => Promise<void>; onCancel?: () => void }) {
  const [eventIds, setEventIds] = useState<string[]>(entry?.event_ids ?? []);
  const [personIds, setPersonIds] = useState<string[]>(() => {
    const eventPeople = events.filter(item => entry?.event_ids.includes(item.id)).flatMap(item => item.participant_ids);
    return [...new Set([...(entry?.person_ids ?? []), ...eventPeople])];
  });
  const sortedEvents = [...events].sort((left, right) => right.starts_at.localeCompare(left.starts_at));

  function updateEvents(event: ChangeEvent<HTMLSelectElement>) {
    const nextIds = Array.from(event.currentTarget.selectedOptions, option => option.value);
    const participants = events.filter(item => nextIds.includes(item.id)).flatMap(item => item.participant_ids);
    setEventIds(nextIds);
    setPersonIds(current => [...new Set([...current, ...participants])]);
  }

  return <form key={entry?.id ?? "new"} className="journal-entry-form" onSubmit={event => void onSave(event, entry?.id)}>
    <label>Datum<input name="entry_date" type="date" defaultValue={entry?.entry_date ?? localDate()} required /></label>
    <label>Titel (optional)<input name="title" maxLength={240} defaultValue={entry?.title ?? ""} placeholder="Ein Titel für den Tag" /></label>
    <label className="journal-content-label">Dein Eintrag<textarea name="content" rows={5} maxLength={20000} defaultValue={entry?.content ?? ""} placeholder="Was möchtest du aus diesem Tag festhalten?" required /></label>
    <label>Stimmung (optional)<select name="mood" defaultValue={entry?.mood ?? ""}><option value="">Keine Angabe</option>{moods.map(mood => <option key={mood.value} value={mood.value}>{mood.label}</option>)}</select></label>
    <div className="journal-link-picker"><label htmlFor={`journal-person-${entry?.id ?? "new"}`}>Personen verknüpfen</label><PersonPicker id={`journal-person-${entry?.id ?? "new"}`} name="person_ids" people={people} selectedIds={personIds} onSelectedIdsChange={setPersonIds} /></div>
    <label>Projekte verknüpfen<select name="project_ids" multiple defaultValue={entry?.project_ids ?? []}>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
    <label>Ereignisse verknüpfen<select name="event_ids" multiple value={eventIds} onChange={updateEvents}>{sortedEvents.map(item => <option key={item.id} value={item.id}>{item.title} · {new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.starts_at))}</option>)}</select></label>
    <p className="journal-select-hint">Die Teilnehmenden ausgewählter Ereignisse werden automatisch als Personen übernommen. Bei Projekten und Ereignissen kannst du mehrere Einträge mit Strg- oder Cmd-Taste auswählen.</p>
    <button type="submit" disabled={busy}>{busy ? "Wird gespeichert …" : entry ? "Änderungen speichern" : "Eintrag speichern"}</button>
    {entry && <button type="button" className="quiet" onClick={onCancel}>Abbrechen</button>}
  </form>;
}

export function JournalPanel({ people, projects, events, request, onMessage }: { people: Person[]; projects: Project[]; events: Event[]; request: Request; onMessage: (message: string) => void }) {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formVersion, setFormVersion] = useState(0);

  const reload = useCallback(async () => {
    const params = new URLSearchParams();
    if (fromDate) params.set("from_date", fromDate);
    if (toDate) params.set("to_date", toDate);
    if (query.trim()) params.set("q", query.trim());
    params.set("limit", "100");
    setEntries(await request<JournalEntry[]>(`/api/journal?${params.toString()}`));
  }, [fromDate, query, request, toDate]);

  useEffect(() => { void reload().catch(error => onMessage(String(error))); }, [onMessage, reload]);

  async function save(event: FormEvent<HTMLFormElement>, entryId?: string) {
    event.preventDefault();
    setBusy(true);
    const form = new FormData(event.currentTarget);
    const body = {
      entry_date: form.get("entry_date"),
      title: form.get("title"),
      content: form.get("content"),
      mood: form.get("mood") || null,
      person_ids: form.getAll("person_ids"),
      project_ids: form.getAll("project_ids"),
      event_ids: form.getAll("event_ids"),
    };
    try {
      await request(entryId ? `/api/journal/${entryId}` : "/api/journal", { method: entryId ? "PATCH" : "POST", body: JSON.stringify(body) });
      setEditingId(null);
      setFormVersion(version => version + 1);
      onMessage(entryId ? "Tagebucheintrag aktualisiert" : "Tagebucheintrag gespeichert");
      await reload();
    } catch (error) {
      onMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function remove(entry: JournalEntry) {
    if (!window.confirm("Diesen Tagebucheintrag dauerhaft löschen?")) return;
    try {
      await request(`/api/journal/${entry.id}`, { method: "DELETE" });
      setEntries(current => current.filter(item => item.id !== entry.id));
      onMessage("Tagebucheintrag gelöscht");
    } catch (error) {
      onMessage(String(error));
    }
  }

  return <section className="card panel journal-panel">
    <div className="panel-head"><div><span className="eyebrow">DEIN TAGEBUCH</span><h2>Was du festhalten möchtest</h2></div><span className="count">{entries.length}</span></div>
    <p className="muted">Private, chronologische Einträge. Verknüpfe bei Bedarf Personen, Projekte und Ereignisse. Stimmung ist freiwillig und wird nur so gespeichert, wie du sie auswählst.</p>
    <details className="journal-new-entry" open={entries.length === 0}><summary>Neuen Tagebucheintrag schreiben</summary><JournalEntryForm key={`new-${formVersion}`} people={people} projects={projects} events={events} busy={busy} onSave={save} /></details>
    <form className="journal-filters" onSubmit={event => { event.preventDefault(); void reload(); }}>
      <label>Suchen<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Im Tagebuch suchen" /></label>
      <label>Von<input type="date" value={fromDate} onChange={event => setFromDate(event.target.value)} /></label>
      <label>Bis<input type="date" value={toDate} onChange={event => setToDate(event.target.value)} /></label>
      <button type="submit">Anwenden</button>
    </form>
    <div className="journal-timeline" aria-live="polite">{entries.length === 0 ? <p className="empty">Noch keine Einträge in diesem Zeitraum.</p> : entries.map(entry => {
      const linkedPeople = entry.person_ids.map(id => people.find(person => person.id === id)).filter((person): person is Person => Boolean(person));
      const linkedProjects = entry.project_ids.map(id => projects.find(project => project.id === id)).filter((project): project is Project => Boolean(project));
      const linkedEvents = entry.event_ids.map(id => events.find(item => item.id === id)).filter((item): item is Event => Boolean(item));
      return <article className="journal-entry" key={entry.id}>
        {editingId === entry.id ? <JournalEntryForm key={entry.id} entry={entry} people={people} projects={projects} events={events} busy={busy} onSave={save} onCancel={() => setEditingId(null)} /> : <>
          <div className="journal-entry-header"><div><time>{formatDate(entry.entry_date)}</time><h3>{entry.title || "Eintrag"}</h3></div><div className="journal-entry-actions"><button type="button" className="quiet" onClick={() => setEditingId(entry.id)}>Bearbeiten</button><button type="button" className="quiet danger-text" onClick={() => void remove(entry)}>Löschen</button></div></div>
          <p className="journal-entry-content">{entry.content}</p>
          {entry.mood && <span className="journal-mood">{moods.find(mood => mood.value === entry.mood)?.label}</span>}
          {(linkedPeople.length > 0 || linkedProjects.length > 0 || linkedEvents.length > 0) && <div className="journal-links">
            {linkedPeople.map(person => <a key={person.id} href={`/people/${person.id}`}>{person.first_name} {person.last_name}</a>)}
            {linkedProjects.map(project => <span key={project.id}>{project.name}</span>)}
            {linkedEvents.map(item => <a key={item.id} href="/events">{item.title}</a>)}
          </div>}
        </>}
      </article>;
    })}</div>
  </section>;
}
