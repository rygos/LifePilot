"use client";

import { FormEvent, useEffect, useState } from "react";

type Person = { id: string; first_name: string; last_name: string; nickname?: string | null; birthday?: string | null; email?: string | null; phone?: string | null; address: string; website?: string | null; job_title?: string | null; organization?: string | null; notes: string };
type Relationship = { id: string; source_person_id: string; source_person_name: string; target_person_id: string; target_person_name: string; relationship_type: string; inverse_relationship_type: string; confirmed: boolean };
type Profile = { username: string; full_name: string; nickname?: string | null; birthday?: string | null; email?: string | null; phone?: string | null; address: string; timezone_name: string; quiet_hours_start?: string | null; quiet_hours_end?: string | null };
type Memory = { id: string; title: string; content: string; created_at: string };
type Task = { id: string; title: string; status: string; due_at?: string | null; repeat_interval_days?: number | null; repeat_until?: string | null };
type Conversation = { id: string; title: string; original_note: string; occurred_at?: string | null; location: string; participant_ids: string[] };
type Loan = { id: string; item_name: string; lender_person_id?: string | null; borrower_person_id?: string | null; due_at?: string | null };
type Gift = { id: string; person_id: string; title: string; occasion: string; status: string };
type Event = { id: string; title: string; starts_at: string; ends_at?: string | null; description?: string; location: string; participant_ids: string[] };
type Reminder = { id: string; title: string; due_at: string; state: string };
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [notifications, setNotifications] = useState<Reminder[]>([]);
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [showProfile, setShowProfile] = useState(false);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
    if (!response.ok) throw new Error((await response.json()).detail ?? "Anfrage fehlgeschlagen");
    return response.status === 204 ? undefined as T : response.json();
  }
  async function refresh() {
    try {
      const [p, m, t, c, l, g, e, n] = await Promise.all([request<Person[]>("/api/people"), request<Memory[]>("/api/memories"), request<Task[]>("/api/tasks?status=open"), request<Conversation[]>("/api/conversations"), request<Loan[]>("/api/loans"), request<Gift[]>("/api/gifts"), request<Event[]>("/api/events"), request<Reminder[]>("/api/notifications")]);
      setPeople(p); setMemories(m); setTasks(t); setConversations(c); setLoans(l); setGifts(g); setEvents(e); setNotifications(n);
    } catch (error) { setMessage(String(error)); }
  }
  useEffect(() => { const saved = localStorage.getItem("lifepilot-token"); if (saved) setToken(saved); }, []);
  useEffect(() => { if (token) { localStorage.setItem("lifepilot-token", token); void refresh(); } }, [token]);
  useEffect(() => { if (token) void request<Profile>("/api/profile").then(setProfile).catch(error => setMessage(String(error))); }, [token]);

  async function selectPerson(person: Person) {
    setSelectedPerson(person);
    try {
      const [full, links] = await Promise.all([request<Person>(`/api/people/${person.id}`), request<Relationship[]>(`/api/relationships?person_id=${person.id}`)]);
      setSelectedPerson(full); setRelationships(links);
    } catch (error) { setMessage(String(error)); }
  }
  async function savePerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const form = new FormData(event.currentTarget);
    try {
      const saved = await request<Person>(`/api/people/${selectedPerson.id}`, { method: "PATCH", body: JSON.stringify({ first_name: form.get("first_name"), last_name: form.get("last_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", website: form.get("website") || null, job_title: form.get("job_title") || null, organization: form.get("organization") || null, notes: form.get("notes") || "" }) });
      setSelectedPerson(saved); await refresh(); setMessage("Profil gespeichert");
    } catch (error) { setMessage(String(error)); }
  }
  async function saveRelationship(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const relationshipForm = event.currentTarget;
    const form = new FormData(relationshipForm);
    try {
      const [relationshipType, inverseType] = String(form.get("relationship_type") ?? "").split("|");
      await request("/api/relationships", { method: "POST", body: JSON.stringify({ source_person_id: selectedPerson.id, target_person_id: form.get("target_id"), relationship_type: relationshipType, inverse_relationship_type: inverseType }) });
      relationshipForm.reset(); await selectPerson(selectedPerson);
    } catch (error) { setMessage(String(error)); }
  }
  async function deleteRelationship(id: string) {
    try { await request(`/api/relationships/${id}`, { method: "DELETE" }); setRelationships(links => links.filter(link => link.id !== id)); }
    catch (error) { setMessage(String(error)); }
  }
  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try {
      const saved = await request<Profile>("/api/profile", { method: "PATCH", body: JSON.stringify({ full_name: form.get("full_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", timezone_name: form.get("timezone_name"), quiet_hours_start: form.get("quiet_hours_start") || null, quiet_hours_end: form.get("quiet_hours_end") || null }) });
      setProfile(saved); setMessage("Dein Profil wurde gespeichert");
    } catch (error) { setMessage(String(error)); }
  }

  async function login(event: FormEvent) {
    event.preventDefault(); setMessage("");
    try { const result = await request<{ access_token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }); setToken(result.access_token); }
    catch (error) { setMessage(String(error)); }
  }
  async function createPerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/people", { method: "POST", body: JSON.stringify({ first_name: form.get("first_name"), last_name: form.get("last_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", website: form.get("website") || null, job_title: form.get("job_title") || null, organization: form.get("organization") || null, notes: form.get("notes") || "" }) }); formElement.reset(); setMessage("Person gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function capture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const content = String(form.get("content") ?? "").trim();
    if (!content) return;
    try { await request("/api/memories", { method: "POST", body: JSON.stringify({ title: content.slice(0, 80), content, occurred_at: new Date().toISOString() }) }); formElement.reset(); setMessage("Erinnerung gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    const interval = String(form.get("repeat_interval_days") ?? "");
    try { await request("/api/tasks", { method: "POST", body: JSON.stringify({ title: form.get("title"), due_at: utcDateTime(form.get("due_at")), repeat_interval_days: interval ? Number(interval) : null, repeat_until: utcDateTime(form.get("repeat_until")) }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const participant = String(form.get("person_id") ?? "");
    try { await request("/api/conversations", { method: "POST", body: JSON.stringify({ title: form.get("title"), original_note: form.get("original_note"), participant_ids: participant ? [participant] : [], occurred_at: form.get("occurred_at") || null, location: form.get("location") || "" }) }); formElement.reset(); setMessage("Gespräch gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createLoan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/loans", { method: "POST", body: JSON.stringify({ item_name: form.get("item_name"), borrower_person_id: form.get("person_id") || null }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createGift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/gifts", { method: "POST", body: JSON.stringify({ person_id: form.get("person_id"), title: form.get("title"), occasion: form.get("occasion") || "" }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function returnLoan(id: string) { try { await request(`/api/loans/${id}/return`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function createEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const person = String(form.get("person_id") ?? "");
    try { await request("/api/events", { method: "POST", body: JSON.stringify({ title: form.get("title"), location: form.get("location") || "", starts_at: utcDateTime(form.get("starts_at")), participant_ids: person ? [person] : [] }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function updateEvent(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request(`/api/events/${id}`, { method: "PATCH", body: JSON.stringify({ title: form.get("title"), starts_at: utcDateTime(form.get("starts_at")), location: form.get("location") || "", participant_ids: form.get("person_id") ? [form.get("person_id")] : [] }) }); await refresh(); setMessage("Termin wurde aktualisiert; die Erinnerung ist angepasst"); }
    catch (error) { setMessage(String(error)); }
  }
  function utcDateTime(value: FormDataEntryValue | null) { return value ? new Date(String(value)).toISOString() : null; }
  function localDateTime(value: string) { const date = new Date(value); const offset = date.getTimezoneOffset() * 60000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
  async function finishReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "done" }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function snoozeReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "scheduled", snoozed_until: new Date(Date.now() + 60 * 60 * 1000).toISOString() }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function complete(id: string) { try { await request(`/api/tasks/${id}/complete`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function search(event: FormEvent) { event.preventDefault(); try { const result = await request<{ people: Person[]; memories: Memory[]; tasks: Task[] }>(`/api/search?q=${encodeURIComponent(query)}`); setPeople(result.people); setMemories(result.memories); setTasks(result.tasks); } catch (error) { setMessage(String(error)); } }

  if (!token) return <main className="login"><div className="brand">L<span>·</span>P</div><p className="eyebrow">DEIN PERSÖNLICHES GEDÄCHTNIS</p><h1>Alles Wichtige<br />im Kopf. Ohne Kopf.</h1><form onSubmit={login} className="card stack"><label>Benutzername<input value={username} onChange={e => setUsername(e.target.value)} /></label><label>Passwort<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button>Anmelden</button>{message && <p className="error">{message}</p>}</form></main>;

  return <main className="shell"><aside className="sidebar"><div className="brand">L<span>·</span>P</div><p className="eyebrow">LIFEPILOT</p><nav><a className="active">◷　Übersicht</a><a href="#people">♙　Menschen</a><a href="#memories">▤　Gedächtnis</a><a href="#tasks">✓　Aufgaben</a></nav><div className="profile"><div className="avatar">{username[0]?.toUpperCase()}</div><div>{username}<small>Persönlicher Bereich</small></div><button className="quiet" onClick={() => { localStorage.removeItem("lifepilot-token"); setToken(""); }}>Abmelden</button></div></aside>
    <section className="content"><header><div><p className="eyebrow">DEIN ZWEITGEDÄCHTNIS</p><h1>Guten Tag.</h1><p className="muted">Was möchtest du heute festhalten?</p></div><div className="header-actions"><span className="date">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date())}</span><button className="quiet profile-toggle" onClick={() => setShowProfile(open => !open)}>{profile?.full_name || profile?.username || "Mein Profil"}</button></div></header>
      {showProfile && profile && <section className="card panel profile-panel"><div className="panel-head"><div><span className="eyebrow">PERSÖNLICHER BEREICH</span><h2>Mein Profil</h2></div><button className="quiet" onClick={() => setShowProfile(false)}>Schließen</button></div><form className="person-form" onSubmit={saveProfile}><label>Vollständiger Name<input name="full_name" defaultValue={profile.full_name} /></label><label>Spitzname<input name="nickname" defaultValue={profile.nickname ?? ""} /></label><label>Geburtstag<input name="birthday" type="date" defaultValue={profile.birthday ?? ""} /></label><label>E-Mail<input name="email" type="email" defaultValue={profile.email ?? ""} /></label><label>Telefon<input name="phone" type="tel" defaultValue={profile.phone ?? ""} /></label><label>Adresse<textarea name="address" defaultValue={profile.address} /></label><label>Zeitzone<input name="timezone_name" defaultValue={profile.timezone_name} required /></label><label>Ruhezeit von<input name="quiet_hours_start" type="time" defaultValue={profile.quiet_hours_start ?? ""} /></label><label>Ruhezeit bis<input name="quiet_hours_end" type="time" defaultValue={profile.quiet_hours_end ?? ""} /></label><p className="form-hint">Während der Ruhezeit werden In-App-Benachrichtigungen ausgeblendet. Beide Zeiten leer lassen, um die Ruhezeit auszuschalten.</p><button>Profil speichern</button></form></section>}
      {message && <p className="notice" role="status">{message}<button className="quiet" onClick={() => setMessage("")}>×</button></p>}
      {notifications.length > 0 && <section className="card panel notification-panel"><div className="panel-head"><div><span className="eyebrow">JETZT FÄLLIG</span><h2>Erinnerungen</h2></div><span className="count">{notifications.length}</span></div>{notifications.map(n => <div className="list-item" key={n.id}><span>{n.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(n.due_at))}</small></span><button className="quiet" onClick={() => void snoozeReminder(n.id)}>+1 Std.</button><button className="quiet" onClick={() => void finishReminder(n.id)}>Erledigt</button></div>)}</section>}
      <section className="capture card"><div><span className="eyebrow">SCHNELLERFASSUNG</span><h2>Ein Gedanke, gut aufgehoben.</h2></div><form onSubmit={capture}><textarea name="content" placeholder="Schreib einfach los. Ein Gespräch, eine Idee, etwas zum Erinnern …" required /><div className="row"><span className="muted">Deine Notiz bleibt privat.</span><button>Speichern <span aria-hidden="true">↗</span></button></div></form></section>
      <div className="search card"><span>⌕</span><form onSubmit={search}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Menschen, Erinnerungen und Aufgaben durchsuchen …" /></form><kbd>↵</kbd></div>
      <div className="grid"><section id="tasks" className="card panel"><div className="panel-head"><div><span className="eyebrow">IM BLICK</span><h2>Aufgaben</h2></div><span className="count">{tasks.length}</span></div><form className="task-form" onSubmit={createTask}><label>Aufgabe<input name="title" placeholder="Neue Aufgabe …" required /></label><label>Fällig am<input name="due_at" type="datetime-local" /></label><label>Alle (Tage)<input name="repeat_interval_days" type="number" min="1" max="365" placeholder="Ohne Wiederholung" /></label><label>Wiederholen bis<input name="repeat_until" type="datetime-local" /></label><button>Aufgabe speichern</button></form>{tasks.length ? tasks.map(t => <div className="list-item" key={t.id}><button className="check" onClick={() => void complete(t.id)} aria-label="Aufgabe abschließen" /><span>{t.title}<small>{t.due_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(t.due_at)) : "Ohne Fälligkeit"}{t.repeat_interval_days ? ` · alle ${t.repeat_interval_days} Tage` : ""}</small></span></div>) : <p className="empty">Alles im Blick. Neue Aufgaben kannst du oben ergänzen.</p>}</section>
      <section id="people" className="card panel"><div className="panel-head"><div><span className="eyebrow">DEIN UMFELD</span><h2>Menschen</h2></div><span className="count">{people.length}</span></div><form className="person-form" onSubmit={createPerson}><label>Vorname<input name="first_name" required /></label><label>Nachname<input name="last_name" /></label><label>Spitzname<input name="nickname" /></label><label>Geburtstag<input name="birthday" type="date" /></label><label>E-Mail<input name="email" type="email" /></label><label>Telefon<input name="phone" type="tel" /></label><button>Person hinzufügen</button></form>{people.map(p => <button className="list-item person person-button" key={p.id} onClick={() => void selectPerson(p)}><span className="avatar small">{p.first_name[0]}</span><span>{p.first_name} {p.last_name}{p.nickname ? ` (${p.nickname})` : ""}<small>{p.birthday ? `Geburtstag: ${p.birthday}` : p.email || p.phone || p.notes || "Profil öffnen"}</small></span></button>)}</section></div>
      {selectedPerson && <section className="card panel person-profile"><div className="panel-head"><div><span className="eyebrow">PERSONENPROFIL</span><h2>{selectedPerson.first_name} {selectedPerson.last_name}</h2></div><button className="quiet" onClick={() => setSelectedPerson(null)}>Schließen</button></div><form key={selectedPerson.id} className="person-form" onSubmit={savePerson}><label>Vorname<input name="first_name" defaultValue={selectedPerson.first_name} required /></label><label>Nachname<input name="last_name" defaultValue={selectedPerson.last_name} /></label><label>Spitzname<input name="nickname" defaultValue={selectedPerson.nickname ?? ""} /></label><label>Geburtstag<input name="birthday" type="date" defaultValue={selectedPerson.birthday ?? ""} /></label><label>E-Mail<input name="email" type="email" defaultValue={selectedPerson.email ?? ""} /></label><label>Telefon<input name="phone" type="tel" defaultValue={selectedPerson.phone ?? ""} /></label><label>Beruf<input name="job_title" defaultValue={selectedPerson.job_title ?? ""} /></label><label>Organisation<input name="organization" defaultValue={selectedPerson.organization ?? ""} /></label><label>Webseite<input name="website" type="url" defaultValue={selectedPerson.website ?? ""} /></label><label>Adresse<textarea name="address" defaultValue={selectedPerson.address} /></label><label className="wide-field">Notizen<textarea name="notes" defaultValue={selectedPerson.notes} /></label><button>Profil speichern</button></form><div className="relationship-section"><div className="panel-head"><div><span className="eyebrow">VERBUNDENE MENSCHEN</span><h3>Beziehungen</h3></div><span className="count">{relationships.length}</span></div>{relationships.length ? relationships.map(link => <div className="list-item" key={link.id}><span>{link.source_person_name} <b>ist {link.relationship_type} →</b> {link.target_person_name} <b>ist {link.inverse_relationship_type}</b><small>{link.confirmed ? "Bestätigt" : "Noch unbestätigt"}</small></span><button className="quiet" onClick={() => void deleteRelationship(link.id)} aria-label="Beziehung entfernen">Entfernen</button></div>) : <p className="empty">Noch keine Beziehungen gespeichert.</p>}<form className="relationship-form" onSubmit={saveRelationship}><label>Verbinde mit<select name="target_id" required defaultValue=""><option value="" disabled>Person auswählen</option>{people.filter(person => person.id !== selectedPerson.id).map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label><label>Beziehungstyp<select name="relationship_type" required defaultValue=""><option value="" disabled>Beziehung auswählen</option><option value="Tochter von|Vater von">Diese Person ist Tochter von / andere ist Vater</option><option value="Tochter von|Mutter von">Diese Person ist Tochter von / andere ist Mutter</option><option value="Sohn von|Vater von">Diese Person ist Sohn von / andere ist Vater</option><option value="Sohn von|Mutter von">Diese Person ist Sohn von / andere ist Mutter</option><option value="Elternteil von|Kind von">Diese Person ist Elternteil von / andere ist Kind</option><option value="Kind von|Elternteil von">Diese Person ist Kind von / andere ist Elternteil</option><option value="Partner von|Partner von">Partner</option><option value="Ehepartner von|Ehepartner von">Ehepartner</option><option value="Geschwister von|Geschwister von">Geschwister</option><option value="kennt|kennt">Kennt</option><option value="Kollege von|Kollege von">Kollege</option></select></label><button disabled={people.length < 2}>Beziehung hinzufügen</button></form></div></section>}
      <section id="memories" className="card panel memory-panel"><div className="panel-head"><div><span className="eyebrow">ZULETZT GESPEICHERT</span><h2>Erinnerungen</h2></div><span className="count">{memories.length}</span></div>{memories.length ? memories.slice(0, 6).map(m => <article className="memory" key={m.id}><span className="memory-dot" /><div><h3>{m.title}</h3><p>{m.content}</p><time>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(m.created_at))}</time></div></article>) : <p className="empty">Hier erscheinen deine gespeicherten Gedanken und Begegnungen.</p>}</section>
      <div className="grid domain-grid"><section className="card panel"><div className="panel-head"><div><span className="eyebrow">EPISODISCHES GEDÄCHTNIS</span><h2>Gespräche</h2></div><span className="count">{conversations.length}</span></div><form className="person-form" onSubmit={createConversation}><input name="title" placeholder="Titel" required /><select name="person_id" defaultValue=""><option value="">Person (optional)</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="occurred_at" type="datetime-local" aria-label="Zeitpunkt" /><input name="location" placeholder="Ort (optional)" /><textarea name="original_note" placeholder="Gesprächsnotiz im Original …" required /><button>Gespräch speichern</button></form>{conversations.slice(0, 4).map(c => <article className="memory" key={c.id}><span className="memory-dot" /><div><h3>{c.title}</h3><p>{c.original_note}</p><time>{c.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(c.occurred_at)) : "Zeitpunkt offen"}{c.location ? ` · ${c.location}` : ""}</time></div></article>)}</section>
      <section className="card panel"><div className="panel-head"><div><span className="eyebrow">IM UMLAUF</span><h2>Leihgaben</h2></div><span className="count">{loans.length}</span></div><form className="inline-form" onSubmit={createLoan}><input name="item_name" placeholder="Gegenstand" required /><select name="person_id" defaultValue="" required><option value="">Entleiher …</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><button aria-label="Leihgabe speichern">+</button></form>{loans.map(l => <div className="list-item" key={l.id}><span>{l.item_name}<small>{people.find(p => p.id === l.borrower_person_id)?.first_name ?? "Unbekannt"}</small></span><button className="quiet" onClick={() => void returnLoan(l.id)}>Zurück</button></div>)}<div className="panel-head gift-heading"><div><span className="eyebrow">VORMERKEN</span><h2>Geschenkideen</h2></div><span className="count">{gifts.length}</span></div><form className="inline-form" onSubmit={createGift}><select name="person_id" defaultValue="" required><option value="">Für wen?</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="title" placeholder="Geschenkidee" required /><input name="occasion" placeholder="Anlass" /><button aria-label="Geschenkidee speichern">+</button></form>{gifts.slice(0, 5).map(g => <div className="list-item" key={g.id}><span>{g.title}<small>{people.find(p => p.id === g.person_id)?.first_name} · {g.occasion || "Idee"}</small></span></div>)}</section></div>
      <section className="card panel events-panel"><div className="panel-head"><div><span className="eyebrow">VORAUSSCHAU</span><h2>Termine</h2></div><span className="count">{events.length}</span></div><form className="event-form" onSubmit={createEvent}><label>Titel<input name="title" placeholder="Termin" required /></label><label>Beginn<input name="starts_at" type="datetime-local" required /></label><label>Person<select name="person_id" defaultValue=""><option value="">Optional auswählen</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label><label>Ort<input name="location" placeholder="Ort" /></label><button>Termin speichern</button></form>{events.filter(e => new Date(e.starts_at) >= new Date()).slice(0, 5).map(e => <div className="list-item event-item" key={e.id}><span>{e.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(e.starts_at))}{e.location ? ` · ${e.location}` : ""}</small></span><details><summary>Bearbeiten</summary><form className="event-edit-form" onSubmit={event => void updateEvent(event, e.id)}><label>Titel<input name="title" required defaultValue={e.title} /></label><label>Beginn<input name="starts_at" type="datetime-local" required defaultValue={localDateTime(e.starts_at)} /></label><label>Ort<input name="location" defaultValue={e.location} /></label><label>Person<select name="person_id" defaultValue={e.participant_ids[0] ?? ""}><option value="">Keine Person</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label><button>Änderungen speichern</button></form></details></div>)}</section>
      <footer>Deine Daten. Dein Server. Dein Gedächtnis.</footer>
    </section></main>;
}
