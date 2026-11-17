"use client";

import { FormEvent, useEffect, useState } from "react";

type Person = { id: string; first_name: string; last_name: string; birthday?: string | null; notes: string };
type Memory = { id: string; title: string; content: string; created_at: string };
type Task = { id: string; title: string; status: string; due_at?: string | null };
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [token, setToken] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${api}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init.headers } });
    if (!response.ok) throw new Error((await response.json()).detail ?? "Anfrage fehlgeschlagen");
    return response.status === 204 ? undefined as T : response.json();
  }
  async function refresh() {
    try {
      const [p, m, t] = await Promise.all([request<Person[]>("/api/people"), request<Memory[]>("/api/memories"), request<Task[]>("/api/tasks?status=open")]);
      setPeople(p); setMemories(m); setTasks(t);
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
  async function complete(id: string) { try { await request(`/api/tasks/${id}/complete`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function search(event: FormEvent) { event.preventDefault(); try { const result = await request<{ people: Person[]; memories: Memory[]; tasks: Task[] }>(`/api/search?q=${encodeURIComponent(query)}`); setPeople(result.people); setMemories(result.memories); setTasks(result.tasks); } catch (error) { setMessage(String(error)); } }

  if (!token) return <main className="login"><div className="brand">L<span>·</span>P</div><p className="eyebrow">DEIN PERSÖNLICHES GEDÄCHTNIS</p><h1>Alles Wichtige<br />im Kopf. Ohne Kopf.</h1><form onSubmit={login} className="card stack"><label>Benutzername<input value={username} onChange={e => setUsername(e.target.value)} /></label><label>Passwort<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button>Anmelden</button>{message && <p className="error">{message}</p>}</form></main>;

  return <main className="shell"><aside className="sidebar"><div className="brand">L<span>·</span>P</div><p className="eyebrow">LIFEPILOT</p><nav><a className="active">◷　Übersicht</a><a href="#people">♙　Menschen</a><a href="#memories">▤　Gedächtnis</a><a href="#tasks">✓　Aufgaben</a></nav><div className="profile"><div className="avatar">{username[0]?.toUpperCase()}</div><div>{username}<small>Persönlicher Bereich</small></div><button className="quiet" onClick={() => { localStorage.removeItem("lifepilot-token"); setToken(""); }}>Abmelden</button></div></aside>
    <section className="content"><header><div><p className="eyebrow">DEIN ZWEITGEDÄCHTNIS</p><h1>Guten Tag.</h1><p className="muted">Was möchtest du heute festhalten?</p></div><span className="date">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date())}</span></header>
      {message && <p className="notice" role="status">{message}<button className="quiet" onClick={() => setMessage("")}>×</button></p>}
      <section className="capture card"><div><span className="eyebrow">SCHNELLERFASSUNG</span><h2>Ein Gedanke, gut aufgehoben.</h2></div><form onSubmit={capture}><textarea name="content" placeholder="Schreib einfach los. Ein Gespräch, eine Idee, etwas zum Erinnern …" required /><div className="row"><span className="muted">Deine Notiz bleibt privat.</span><button>Speichern <span aria-hidden="true">↗</span></button></div></form></section>
      <div className="search card"><span>⌕</span><form onSubmit={search}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="Menschen, Erinnerungen und Aufgaben durchsuchen …" /></form><kbd>↵</kbd></div>
      <div className="grid"><section id="tasks" className="card panel"><div className="panel-head"><div><span className="eyebrow">IM BLICK</span><h2>Aufgaben</h2></div><span className="count">{tasks.length}</span></div><form className="inline-form" onSubmit={createTask}><input name="title" placeholder="Neue Aufgabe …" required /><button aria-label="Aufgabe hinzufügen">+</button></form>{tasks.length ? tasks.map(t => <div className="list-item" key={t.id}><button className="check" onClick={() => void complete(t.id)} aria-label="Aufgabe abschließen" /><span>{t.title}</span></div>) : <p className="empty">Alles im Blick. Neue Aufgaben kannst du oben ergänzen.</p>}</section>
      <section id="people" className="card panel"><div className="panel-head"><div><span className="eyebrow">DEIN UMFELD</span><h2>Menschen</h2></div><span className="count">{people.length}</span></div><form className="person-form" onSubmit={createPerson}><input name="first_name" placeholder="Vorname" required /><input name="last_name" placeholder="Nachname" /><input name="birthday" type="date" aria-label="Geburtstag" /><input name="notes" placeholder="Notiz (optional)" /><button>Person hinzufügen</button></form>{people.map(p => <div className="list-item person" key={p.id}><div className="avatar small">{p.first_name[0]}</div><span>{p.first_name} {p.last_name}<small>{p.birthday ? `Geburtstag: ${p.birthday}` : p.notes}</small></span></div>)}</section></div>
      <section id="memories" className="card panel memory-panel"><div className="panel-head"><div><span className="eyebrow">ZULETZT GESPEICHERT</span><h2>Erinnerungen</h2></div><span className="count">{memories.length}</span></div>{memories.length ? memories.slice(0, 6).map(m => <article className="memory" key={m.id}><span className="memory-dot" /><div><h3>{m.title}</h3><p>{m.content}</p><time>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(m.created_at))}</time></div></article>) : <p className="empty">Hier erscheinen deine gespeicherten Gedanken und Begegnungen.</p>}</section>
      <footer>Deine Daten. Dein Server. Dein Gedächtnis.</footer>
    </section></main>;
}
