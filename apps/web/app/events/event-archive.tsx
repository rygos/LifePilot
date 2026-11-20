"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Person } from "../page";
import { PersonPicker } from "../people/person-picker";

type EventRecord = { id: string; title: string; record_type: "appointment" | "experience"; starts_at: string; ends_at?: string | null; description?: string | null; location: string; location_address: string; source_memory_id: string | null; participant_ids: string[] };
type EventPhoto = { id: string; event_id: string; caption: string; created_at: string };
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;

function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function birthdayDateForYear(birthday: string, year: number): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(birthday);
  if (!match) return null;
  const month = Number(match[2]);
  const originalDay = Number(match[3]);
  const day = month === 2 && originalDay === 29 && !((year % 4 === 0 && year % 100 !== 0) || year % 400 === 0) ? 28 : originalDay;
  const date = new Date(year, month - 1, day);
  return date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

function localInput(value: string): string {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function ParticipantPhoto({ person, token, api }: { person: Person; token: string; api: string }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (!person.photo_key) { setUrl(""); return; }
    let objectUrl = "";
    const controller = new AbortController();
    void fetch(`${api}/api/people/${person.id}/photo`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error("Profilbild nicht verfügbar"); return response.blob(); })
      .then(blob => { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); })
      .catch(error => { if (!(error instanceof DOMException && error.name === "AbortError")) setUrl(""); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [api, person.id, person.photo_key, token]);
  return url ? <img className="avatar-photo" src={url} alt={`Profilbild ${person.first_name} ${person.last_name}`} /> : <span className="avatar">{person.first_name[0]?.toLocaleUpperCase("de-DE")}</span>;
}

function Photo({ eventId, photo, token, api, onDelete }: { eventId: string; photo: EventPhoto; token: string; api: string; onDelete: () => void }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    let objectUrl = "";
    const controller = new AbortController();
    void fetch(`${api}/api/events/${eventId}/photos/${photo.id}/image`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error("Bild nicht verfügbar"); return response.blob(); })
      .then(blob => { objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); })
      .catch(error => { if (!(error instanceof DOMException && error.name === "AbortError")) setUrl(""); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [api, eventId, photo.id, token]);
  return <figure className="event-photo-card">{url ? <img src={url} alt={photo.caption || "Bild zum Ereignis"} /> : <div className="event-photo-loading" aria-label="Bild wird geladen" />}<figcaption>{photo.caption || "Ohne Bildbeschreibung"}<button type="button" className="quiet danger-text" onClick={onDelete} aria-label="Ereignisbild löschen">Löschen</button></figcaption></figure>;
}

export function EventArchive({ events, people, memories, token, api, request, onRefresh, onDelete }: { events: EventRecord[]; people: Person[]; memories: { id: string; title: string; content: string }[]; token: string; api: string; request: Request; onRefresh: () => Promise<void>; onDelete: (id: string) => Promise<void> }) {
  const experiences = events.filter(event => event.record_type === "experience");
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [day, setDay] = useState(() => dateKey(new Date()));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [photos, setPhotos] = useState<EventPhoto[]>([]);
  const [participantResetKey, setParticipantResetKey] = useState(0);
  const selected = experiences.find(event => event.id === selectedId) ?? experiences.find(event => dateKey(new Date(event.starts_at)) === day) ?? null;
  const monthEvents = useMemo(() => experiences.filter(event => new Date(event.starts_at).getFullYear() === month.getFullYear() && new Date(event.starts_at).getMonth() === month.getMonth()), [experiences, month]);
  const dayEvents = experiences.filter(event => dateKey(new Date(event.starts_at)) === day).sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const monthBirthdays = useMemo(() => people.flatMap(person => {
    if (!person.birthday) return [];
    const date = birthdayDateForYear(person.birthday, month.getFullYear());
    return date && date.getMonth() === month.getMonth() ? [{ person, date, date_key: dateKey(date) }] : [];
  }).sort((left, right) => `${left.person.first_name} ${left.person.last_name}`.localeCompare(`${right.person.first_name} ${right.person.last_name}`, "de")), [month, people]);
  const dayBirthdays = monthBirthdays.filter(item => item.date_key === day);
  const calendarCells = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7;
    const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    return [...Array.from({ length: offset }, () => null), ...Array.from({ length: days }, (_, index) => index + 1)];
  }, [month]);

  useEffect(() => {
    if (!selected) { setPhotos([]); return; }
    void request<EventPhoto[]>(`/api/events/${selected.id}/photos`).then(setPhotos).catch(() => setPhotos([]));
  }, [request, selected?.id]);

  function moveMonth(amount: number) { setMonth(current => new Date(current.getFullYear(), current.getMonth() + amount, 1)); }
  async function save(event: FormEvent<HTMLFormElement>, id?: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const payload = { title: data.get("title"), record_type: "experience", starts_at: new Date(String(data.get("starts_at"))).toISOString(), ends_at: data.get("ends_at") ? new Date(String(data.get("ends_at"))).toISOString() : null, description: data.get("description") || "", location: data.get("location") || "", location_address: data.get("location_address") || "", participant_ids: data.getAll("participant_ids").map(String) };
    try {
      const saved = await request<EventRecord>(id ? `/api/events/${id}` : "/api/events", { method: id ? "PATCH" : "POST", body: JSON.stringify(payload) });
      if (!id) { form.reset(); setParticipantResetKey(current => current + 1); }
      setSelectedId(saved.id); setIsEditing(false); setDay(dateKey(new Date(saved.starts_at))); setMonth(new Date(new Date(saved.starts_at).getFullYear(), new Date(saved.starts_at).getMonth(), 1)); await onRefresh();
    } catch (error) { window.alert(error instanceof Error ? error.message : String(error)); }
  }
  async function upload(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault(); const form = event.currentTarget;
    try {
      const response = await fetch(`${api}/api/events/${id}/photos`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: new FormData(form) });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Bild konnte nicht gespeichert werden");
      form.reset(); setPhotos(await request<EventPhoto[]>(`/api/events/${id}/photos`));
    } catch (error) { window.alert(error instanceof Error ? error.message : String(error)); }
  }
  async function deletePhoto(id: string, photoId: string) {
    try { await request(`/api/events/${id}/photos/${photoId}`, { method: "DELETE" }); setPhotos(current => current.filter(photo => photo.id !== photoId)); }
    catch (error) { window.alert(error instanceof Error ? error.message : String(error)); }
  }

  return <section className="card panel event-archive">
    <div className="panel-head"><div><span className="eyebrow">EREIGNISSE & GEBURTSTAGE</span><h2>Ereignisarchiv</h2></div><span className="count">{experiences.length}</span></div>
    <p className="muted">Vergangene Treffen, Erlebnisse und bekannte Geburtstage erscheinen im Kalender. Ereignisse kannst du ergänzen, auswählen und mit Bildern versehen.</p>
    <details className="event-create"><summary>Ereignis manuell festhalten</summary><form className="event-edit-form" onSubmit={event => void save(event)}>
      <label>Titel<input name="title" required placeholder="Zum Beispiel: Lego-Nachmittag bei Christian" /></label><label>Beginn<input name="starts_at" type="datetime-local" required defaultValue={localInput(new Date().toISOString())} /></label>
      <label>Ende (optional)<input name="ends_at" type="datetime-local" /></label><label>Ort<input name="location" placeholder="Name des Ortes" /></label><label>Adresse (optional)<input name="location_address" placeholder="Straße, Ort" /></label>
      <div className="event-participants"><label htmlFor="new-event-participants">Teilnehmende</label><PersonPicker key={participantResetKey} id="new-event-participants" people={people} /></div>
      <label className="event-context">Kontext und Notizen<textarea name="description" rows={3} placeholder="Was ist passiert? Worüber habt ihr gesprochen?" /></label><button>Ereignis speichern</button>
    </form></details>
    <div className="event-archive-layout">
      <section className="event-calendar" aria-label="Ereigniskalender">
        <div className="event-calendar-heading"><button type="button" className="quiet" onClick={() => moveMonth(-1)} aria-label="Vorheriger Monat">‹</button><h3>{new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(month)}</h3><button type="button" className="quiet" onClick={() => moveMonth(1)} aria-label="Nächster Monat">›</button></div>
        <div className="event-calendar-legend" aria-label="Kalenderlegende"><span><i /> Ereignis</span><span><i className="birthday-marker" /> Geburtstag</span></div>
        <div className="event-calendar-grid">{["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map(name => <span className="event-weekday" key={name}>{name}</span>)}{calendarCells.map((cell, index) => {
          if (cell === null) return <span key={`blank-${index}`} />;
          const key = dateKey(new Date(month.getFullYear(), month.getMonth(), cell)); const hasEvents = monthEvents.some(event => dateKey(new Date(event.starts_at)) === key); const hasBirthdays = monthBirthdays.some(item => item.date_key === key);
          const markerLabel = hasEvents && hasBirthdays ? "Ereignisse und Geburtstage vorhanden" : hasBirthdays ? "Geburtstage vorhanden" : "Ereignisse vorhanden";
          return <button type="button" key={key} className={`event-day${day === key ? " selected" : ""}${hasEvents || hasBirthdays ? " has-events" : ""}${hasBirthdays ? " has-birthdays" : ""}`} aria-pressed={day === key} onClick={() => { setDay(key); setSelectedId(null); setIsEditing(false); }}>{cell}{(hasEvents || hasBirthdays) && <i aria-label={markerLabel} />}</button>;
        })}</div>
        <h3 className="event-day-heading">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date(`${day}T12:00:00`))}</h3>
        {dayEvents.length || dayBirthdays.length ? <div className="event-day-list">{dayBirthdays.map(item => <a key={`birthday-${item.person.id}`} className="event-day-item birthday-day-item" href={`/people/${item.person.id}`}><strong>{item.person.first_name} {item.person.last_name}</strong><small>Geburtstag · wird {month.getFullYear() - Number(item.person.birthday?.slice(0, 4))} Jahre{item.person.nickname ? ` · „${item.person.nickname}“` : ""}</small></a>)}{dayEvents.map(item => <button key={item.id} type="button" className={`event-day-item${selected?.id === item.id ? " active" : ""}`} onClick={() => { setSelectedId(item.id); setIsEditing(false); }}><strong>{item.title}</strong><small>{new Intl.DateTimeFormat("de-DE", { timeStyle: "short" }).format(new Date(item.starts_at))}{item.location ? ` · ${item.location}` : ""}</small></button>)}</div> : <p className="empty">Für diesen Tag sind keine Ereignisse oder Geburtstage gespeichert.</p>}
      </section>
      <section className="event-detail" aria-label="Ereignisdetails">
        {!selected ? <p className="empty">{dayBirthdays.length ? "An diesem Tag haben Personen Geburtstag. Wähle einen Namen in der Tagesliste, um das Profil zu öffnen." : "Wähle ein Ereignis im Kalender aus oder halte ein neues fest."}</p> : <>
          <div className="panel-head"><div><span className="eyebrow">EREIGNISDETAILS</span><h3>{selected.title}</h3></div><div className="event-detail-actions">{isEditing ? <button type="button" className="quiet" onClick={() => setIsEditing(false)}>Abbrechen</button> : <><button type="button" className="quiet" onClick={() => setIsEditing(true)}>Bearbeiten</button><button type="button" className="quiet danger-text" onClick={() => void onDelete(selected.id)}>Löschen</button></>}</div></div>
          {isEditing ? <form className="event-edit-form" onSubmit={event => void save(event, selected.id)}>
            <label>Titel<input name="title" required defaultValue={selected.title} /></label><label>Beginn<input name="starts_at" type="datetime-local" required defaultValue={localInput(selected.starts_at)} /></label><label>Ende (optional)<input name="ends_at" type="datetime-local" defaultValue={selected.ends_at ? localInput(selected.ends_at) : ""} /></label><label>Ort<input name="location" defaultValue={selected.location} placeholder="Name des Ortes" /></label><label>Adresse<input name="location_address" defaultValue={selected.location_address} placeholder="Straße, Ort" /></label>
            <div className="event-participants"><label htmlFor={`edit-event-participants-${selected.id}`}>Teilnehmende</label><PersonPicker key={`${selected.id}-${selected.participant_ids.join(",")}`} id={`edit-event-participants-${selected.id}`} people={people} initialIds={selected.participant_ids} /></div><label className="event-context">Kontext und Notizen<textarea name="description" rows={4} defaultValue={selected.description ?? ""} placeholder="Was ist passiert?" /></label><button>Änderungen speichern</button>
          </form> : <div className="event-summary">
            <p className="event-summary-date">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full", timeStyle: "short" }).format(new Date(selected.starts_at))}{selected.ends_at ? ` bis ${new Intl.DateTimeFormat("de-DE", { timeStyle: "short" }).format(new Date(selected.ends_at))}` : ""}</p>
            {selected.description && <section className="event-summary-context"><h4>Kontext</h4><p>{selected.description}</p></section>}
            {(selected.location || selected.location_address) && <div className="event-place"><h4>Ort</h4><p>{selected.location || "Ort ohne Namen"}</p>{selected.location_address && <small>{selected.location_address}</small>}</div>}
            <h4>Teilnehmende</h4>{selected.participant_ids.length ? <div className="event-participant-cards">{selected.participant_ids.map(id => people.find(person => person.id === id)).filter((person): person is Person => Boolean(person)).map(person => <a className="event-participant-card" href={`/people/${person.id}`} key={person.id}><ParticipantPhoto person={person} token={token} api={api} /><strong>{person.first_name} {person.last_name}</strong>{person.nickname && <small>{person.nickname}</small>}</a>)}</div> : <p className="muted">Noch keine Teilnehmenden zugeordnet.</p>}
          </div>}
          <div className="event-image-section"><div className="panel-head"><h4>Bilder</h4><span className="count">{photos.length}</span></div><form className="event-photo-upload" onSubmit={event => void upload(event, selected.id)}><label>Bild hinzufügen<input name="file" type="file" accept="image/jpeg,image/png,image/webp" required /></label><label>Bildbeschreibung (optional)<input name="caption" maxLength={240} /></label><button>Hochladen</button></form>{photos.length ? <div className="event-photo-grid">{photos.map(photo => <Photo key={photo.id} eventId={selected.id} photo={photo} token={token} api={api} onDelete={() => void deletePhoto(selected.id, photo.id)} />)}</div> : <p className="empty">Zu diesem Ereignis wurden noch keine Bilder hinzugefügt.</p>}</div>
          {selected.source_memory_id && memories.find(memory => memory.id === selected.source_memory_id) && <details className="event-source"><summary>Ursprüngliche Eingabe</summary><p>{memories.find(memory => memory.id === selected.source_memory_id)?.content}</p></details>}
        </>}
      </section>
    </div>
  </section>;
}
