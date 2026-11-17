"use client";

import { FormEvent, useEffect, useState } from "react";

type Person = { id: string; first_name: string; last_name: string; birthday?: string | null; notes: string };
type Memory = { id: string; title: string; content: string; created_at: string };
type Task = { id: string; title: string; status: string; due_at?: string | null };
type Conversation = { id: string; title: string; original_note: string; occurred_at?: string | null; location: string; participant_ids: string[] };
type Loan = { id: string; item_name: string; lender_person_id?: string | null; borrower_person_id?: string | null; due_at?: string | null };
type Gift = { id: string; person_id: string; title: string; occasion: string; status: string };
type Event = { id: string; title: string; starts_at: string; location: string; participant_ids: string[] };
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

  async function login(event: FormEvent) {
    event.preventDefault(); setMessage("");
    try { const result = await request<{ access_token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }); setToken(result.access_token); }
    catch (error) { setMessage(String(error)); }
  }
  async function createPerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await request("/api/people", { method: "POST", body: JSON.stringify({ first_name: form.get("first_name"), last_name: form.get("last_name"), birthday: form.get("birthday") || null, notes: form.get("notes") }) }); event.currentTarget.reset(); setMessage("Person gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function capture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const content = String(form.get("content") ?? "").trim();
    if (!content) return;
    try { await request("/api/memories", { method: "POST", body: JSON.stringify({ title: content.slice(0, 80), content, occurred_at: new Date().toISOString() }) }); event.currentTarget.reset(); setMessage("Erinnerung gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await request("/api/tasks", { method: "POST", body: JSON.stringify({ title: form.get("title") }) }); event.currentTarget.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const participant = String(form.get("person_id") ?? "");
    try { await request("/api/conversations", { method: "POST", body: JSON.stringify({ title: form.get("title"), original_note: form.get("original_note"), participant_ids: participant ? [participant] : [], occurred_at: form.get("occurred_at") || null, location: form.get("location") || "" }) }); event.currentTarget.reset(); setMessage("Gespräch gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createLoan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await request("/api/loans", { method: "POST", body: JSON.stringify({ item_name: form.get("item_name"), borrower_person_id: form.get("person_id") || null }) }); event.currentTarget.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createGift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await request("/api/gifts", { method: "POST", body: JSON.stringify({ person_id: form.get("person_id"), title: form.get("title"), occasion: form.get("occasion") || "" }) }); event.currentTarget.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function returnLoan(id: string) { try { await request(`/api/loans/${id}/return`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function createEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget); const person = String(form.get("person_id") ?? "");
    try { await request("/api/events", { method: "POST", body: JSON.stringify({ title: form.get("title"), location: form.get("location") || "", starts_at: form.get("starts_at"), participant_ids: person ? [person] : [] }) }); event.currentTarget.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function finishReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "done" }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function snoozeReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "scheduled", snoozed_until: new Date(Date.now() + 60 * 60 * 1000).toISOString() }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function complete(id: string) { try { await request(`/api/tasks/${id}/complete`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function search(event: FormEvent) { event.preventDefault(); try { const result = await request<{ people: Person[]; memories: Memory[]; tasks: Task[] }>(`/api/search?q=${encodeURIComponent(query)}`); setPeople(result.people); setMemories(result.memories); setTasks(result.tasks); } catch (error) { setMessage(String(error)); } }

  if (!token) return <main className="login"><div className="brand">L<span>·</span>P</div><p className="eyebrow">DEIN PERSÖNLICHES GEDÄCHTNIS</p><h1>Alles Wichtige<br />im Kopf. Ohne Kopf.</h1><form onSubmit={login} className="card stack"><label>Benutzername<input value={username} onChange={e => setUsername(e.target.value)} /></label><label>Passwort<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button>Anmelden</button>{message && <p className="error">{message}</p>}</form></main>;

  return <main className="shell"><aside className="sidebar"><div className="brand">L<span>·</span>P</div><p className="eyebrow">LIFEPILOT</p><nav><a className="active">◷　Übersicht</a><a href="#people">♙　Menschen</a><a href="#memories">▤　Gedächtnis</a><a href="#tasks">✓　Aufgaben</a></nav><div className="profile"><div className="avatar">{username[0]?.toUpperCase()}</div><div>{username}<small>Persönlicher Bereich</small></div><button className="quiet" onClick={() => { localStorage.removeItem("lifepilot-token"); setToken(""); }}>Abmelden</button></div></aside>
    <section className="content"><header><div><p className="eyebrow">DEIN ZWEITGEDÄCHTNIS</p><h1>Guten Tag.</h1><p className="muted">Was möchtest du heute festhalten?</p></div><span className="date">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date())}</span></header>
      {message && <p className="notice" role="status">{message}<button className="quiet" onClick={() => setMessage("")}>×</button></p>}
      {notifications.length > 0 && <section className="card panel notification-panel"><div className="panel-head"><div><span className="eyebrow">JETZT FÄLLIG</span><h2>Erinnerungen</h2></div><span className="count">{notifications.length}</span></div>{notifications.map(n => <div className="list-item" key={n.id}><span>{n.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(n.due_at))}</small></span><button className="quiet" onClick={() => void snoozeReminder(n.id)}>+1 Std.</button><button className="quiet" onClick={() => void finishReminder(n.id)}>Erledigt</button></div>)}</section>}
      <section className="capture card"><div><span className="eyebrow">SCHNELLERFASSUNG</span><h2>Ein Gedanke, gut aufgehoben.</h2></div><form onSubmit={capture}><textarea name="content" placeholder="Schreib einfach los. Ein Gespräch, eine Idee, etwas zum Erinnern …" required /><div className="row"><span className="muted">Deine Notiz bleibt privat.</span><button>Speichern <span aria-hidden="true">↗</span></button></div></form></section>
      <div className="search card"><span>⌕</span><form onSubmit={search}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Menschen, Erinnerungen und Aufgaben durchsuchen …" /></form><kbd>↵</kbd></div>
      <div className="grid"><section id="tasks" className="card panel"><div className="panel-head"><div><span className="eyebrow">IM BLICK</span><h2>Aufgaben</h2></div><span className="count">{tasks.length}</span></div><form className="inline-form" onSubmit={createTask}><input name="title" placeholder="Neue Aufgabe …" required /><button aria-label="Aufgabe hinzufügen">+</button></form>{tasks.length ? tasks.map(t => <div className="list-item" key={t.id}><button className="check" onClick={() => void complete(t.id)} aria-label="Aufgabe abschließen" /><span>{t.title}</span></div>) : <p className="empty">Alles im Blick. Neue Aufgaben kannst du oben ergänzen.</p>}</section>
      <section id="people" className="card panel"><div className="panel-head"><div><span className="eyebrow">DEIN UMFELD</span><h2>Menschen</h2></div><span className="count">{people.length}</span></div><form className="person-form" onSubmit={createPerson}><input name="first_name" placeholder="Vorname" required /><input name="last_name" placeholder="Nachname" /><input name="birthday" type="date" aria-label="Geburtstag" /><input name="notes" placeholder="Notiz (optional)" /><button>Person hinzufügen</button></form>{people.map(p => <div className="list-item person" key={p.id}><div className="avatar small">{p.first_name[0]}</div><span>{p.first_name} {p.last_name}<small>{p.birthday ? `Geburtstag: ${p.birthday}` : p.notes}</small></span></div>)}</section></div>
      <section id="memories" className="card panel memory-panel"><div className="panel-head"><div><span className="eyebrow">ZULETZT GESPEICHERT</span><h2>Erinnerungen</h2></div><span className="count">{memories.length}</span></div>{memories.length ? memories.slice(0, 6).map(m => <article className="memory" key={m.id}><span className="memory-dot" /><div><h3>{m.title}</h3><p>{m.content}</p><time>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(m.created_at))}</time></div></article>) : <p className="empty">Hier erscheinen deine gespeicherten Gedanken und Begegnungen.</p>}</section>
      <div className="grid domain-grid"><section className="card panel"><div className="panel-head"><div><span className="eyebrow">EPISODISCHES GEDÄCHTNIS</span><h2>Gespräche</h2></div><span className="count">{conversations.length}</span></div><form className="person-form" onSubmit={createConversation}><input name="title" placeholder="Titel" required /><select name="person_id" defaultValue=""><option value="">Person (optional)</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="occurred_at" type="datetime-local" aria-label="Zeitpunkt" /><input name="location" placeholder="Ort (optional)" /><textarea name="original_note" placeholder="Gesprächsnotiz im Original …" required /><button>Gespräch speichern</button></form>{conversations.slice(0, 4).map(c => <article className="memory" key={c.id}><span className="memory-dot" /><div><h3>{c.title}</h3><p>{c.original_note}</p><time>{c.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(c.occurred_at)) : "Zeitpunkt offen"}{c.location ? ` · ${c.location}` : ""}</time></div></article>)}</section>
      <section className="card panel"><div className="panel-head"><div><span className="eyebrow">IM UMLAUF</span><h2>Leihgaben</h2></div><span className="count">{loans.length}</span></div><form className="inline-form" onSubmit={createLoan}><input name="item_name" placeholder="Gegenstand" required /><select name="person_id" defaultValue="" required><option value="">Entleiher …</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><button aria-label="Leihgabe speichern">+</button></form>{loans.map(l => <div className="list-item" key={l.id}><span>{l.item_name}<small>{people.find(p => p.id === l.borrower_person_id)?.first_name ?? "Unbekannt"}</small></span><button className="quiet" onClick={() => void returnLoan(l.id)}>Zurück</button></div>)}<div className="panel-head gift-heading"><div><span className="eyebrow">VORMERKEN</span><h2>Geschenkideen</h2></div><span className="count">{gifts.length}</span></div><form className="inline-form" onSubmit={createGift}><select name="person_id" defaultValue="" required><option value="">Für wen?</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="title" placeholder="Geschenkidee" required /><input name="occasion" placeholder="Anlass" /><button aria-label="Geschenkidee speichern">+</button></form>{gifts.slice(0, 5).map(g => <div className="list-item" key={g.id}><span>{g.title}<small>{people.find(p => p.id === g.person_id)?.first_name} · {g.occasion || "Idee"}</small></span></div>)}</section></div>
      <section className="card panel events-panel"><div className="panel-head"><div><span className="eyebrow">VORAUSSCHAU</span><h2>Termine</h2></div><span className="count">{events.length}</span></div><form className="event-form" onSubmit={createEvent}><input name="title" placeholder="Termin" required /><input name="starts_at" type="datetime-local" required aria-label="Beginn" /><select name="person_id" defaultValue=""><option value="">Person (optional)</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="location" placeholder="Ort" /><button>Termin speichern</button></form>{events.filter(e => new Date(e.starts_at) >= new Date()).slice(0, 5).map(e => <div className="list-item" key={e.id}><span>{e.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(e.starts_at))}{e.location ? ` · ${e.location}` : ""}</small></span></div>)}</section>
      <footer>Deine Daten. Dein Server. Dein Gedächtnis.</footer>
    </section></main>;
}
