"use client";

import { FormEvent, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useLifePilotSession } from "./use-life-pilot-session";
import { AccountSettingsPanel, type Profile } from "./settings/account-settings-panel";
import { CaptureChatReview } from "./chat/capture-chat-review";
import { EventArchive } from "./events/event-archive";
import { PersonPicker } from "./people/person-picker";
import { AdminPanel } from "./admin/admin-panel";

export type Person = { id: string; first_name: string; last_name: string; nickname?: string | null; birthday?: string | null; gender: "female" | "male" | "diverse" | "unspecified"; email?: string | null; phone?: string | null; address: string; website?: string | null; job_title?: string | null; organization?: string | null; notes: string; is_self: boolean; photo_key?: string | null; created_at: string };
type ChatSource = { id: string; kind: string; title: string; excerpt: string; href: string };
type ChatEntry = { id: string; mode: "capture" | "ask"; role: "user" | "assistant"; text: string; sources?: ChatSource[]; captureId?: string };
type PersonName = { id: string; name: string; name_type: string; valid_until?: string | null; confirmed: boolean; source_capture_id?: string | null };
type Organization = { id: string; name: string; organization_type: "club" | "company" | "school" | "other"; notes: string; members: Membership[] };
type Membership = { id: string; person_id: string; person_name: string; person_photo_key: string | null; person_birthday: string | null; organization_id: string; organization_name: string; organization_type: string; role: string; valid_from: string | null; valid_until: string | null };
type Relationship = { id: string; source_person_id: string; source_person_name: string; target_person_id: string; target_person_name: string; relationship_type: string; inverse_relationship_type: string; confirmed: boolean };
export type Memory = { id: string; title: string; content: string; created_at: string; occurred_at?: string | null };
type Task = { id: string; title: string; status: string; due_at?: string | null; repeat_interval_days?: number | null; repeat_until?: string | null };
type Conversation = { id: string; title: string; original_note: string; summary?: string; occurred_at?: string | null; location: string; participant_ids: string[] };
type Loan = { id: string; item_name: string; lender_person_id?: string | null; borrower_person_id?: string | null; due_at?: string | null };
type Gift = { id: string; person_id: string; title: string; occasion: string; status: string };
type Event = { id: string; title: string; record_type: "appointment" | "experience"; starts_at: string; ends_at?: string | null; description: string; location: string; location_address: string; source_memory_id: string | null; participant_ids: string[] };
type Reminder = { id: string; title: string; due_at: string; state: string };
export type CaptureSuggestion = { kind: "fact" | "conversation" | "relationship" | "owner_relationship" | "former_name" | "life_event" | "task" | "event" | "project_link" | "loan"; title: string; content: string; person_name: string | null; person_gender: "female" | "male" | "diverse" | null; person_gender_basis: "explicit" | "name_inference" | null; person_id: string | null; person_candidates: string[]; project_name: string | null; project_id: string | null; project_candidates: string[]; relationship_type: string | null; inverse_relationship_type: string | null; related_person_name: string | null; related_person_gender: "female" | "male" | "diverse" | null; related_person_gender_basis: "explicit" | "name_inference" | null; related_person_id: string | null; related_person_candidates: string[]; participant_names: string[]; location: string | null; location_address: string | null; due_at: string | null; occurred_at: string | null; date_precision: string; confirmation_required: boolean };
export type Capture = { id: string; parent_capture_id: string | null; original_text: string; source: "capture" | "chat"; status: "pending" | "ready" | "unavailable" | "failed" | "reviewed"; suggestions: CaptureSuggestion[]; processing_error: string; created_at: string };
export type Project = { id: string; name: string; description: string; status: string };
type Approval = { id: string; operation: string; resource_id: string; resource_label: string; status: string; created_at: string };
type DailyBriefing = { date: string; timezone: string; open_tasks: Task[]; today_events: Event[]; upcoming_reminders: { id: string; title: string; due_at: string; source_type: string; source_id: string }[] };
type PersonBriefing = { memories: Memory[]; conversations: Conversation[]; open_tasks: Task[]; open_loans: Loan[]; gift_ideas: Gift[]; upcoming_events: Event[]; owner_relationships: { id: string; relationship_type: string; valid_from?: string | null; valid_until?: string | null; source_capture_id?: string | null }[]; former_names: { id: string; name: string; valid_until?: string | null; source_capture_id?: string | null }[]; life_events: { id: string; title: string; details: string; occurred_at?: string | null; date_precision: string; source_capture_id?: string | null }[] };
const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const MAX_CHAT_HISTORY_ENTRIES = 40;
const MAX_CHAT_CAPTURE_THREADS = MAX_CHAT_HISTORY_ENTRIES / 2;
const ownerRelationshipDateFormatter = new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" });
function calculateAge(birthday?: string | null): number | null {
  if (!birthday) return null;
  const date = new Date(`${birthday}T12:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  const now = new Date();
  let age = now.getFullYear() - date.getFullYear();
  if (now.getMonth() < date.getMonth() || (now.getMonth() === date.getMonth() && now.getDate() < date.getDate())) age -= 1;
  return age >= 0 && age < 130 ? age : null;
}

function genderName(gender?: Person["gender"]): string {
  return { female: "Weiblich", male: "Männlich", diverse: "Divers", unspecified: "Keine Angabe" }[gender ?? "unspecified"];
}

function PersonPhoto({ person, token, api, className = "" }: { person: Person | Pick<Membership, "person_id" | "person_name" | "person_photo_key">; token: string; api: string; className?: string }) {
  const [imageUrl, setImageUrl] = useState("");
  const id = "id" in person ? person.id : person.person_id;
  const name = "first_name" in person ? `${person.first_name} ${person.last_name}`.trim() : person.person_name;
  const photoKey = "id" in person ? person.photo_key ?? null : person.person_photo_key;
  useEffect(() => {
    if (!photoKey || !token) { setImageUrl(""); return; }
    let objectUrl = "";
    const controller = new AbortController();
    void fetch(`${api}/api/people/${id}/photo`, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error("Profilbild nicht verfügbar");
      return response.blob();
    }).then(blob => { objectUrl = URL.createObjectURL(blob); setImageUrl(objectUrl); }).catch(error => {
      if (!(error instanceof DOMException && error.name === "AbortError")) setImageUrl("");
    });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [api, id, photoKey, token]);
  return imageUrl ? <img className={`avatar-photo ${className}`} src={imageUrl} alt={`Profilbild ${name}`} /> : <span className={`avatar ${className}`} aria-label={`Kein Profilbild für ${name}`}>{name[0]?.toLocaleUpperCase("de-DE") ?? "?"}</span>;
}

export default function Home() {
  const pathname = usePathname();
  const currentView = pathname === "/" ? "dashboard" : pathname.startsWith("/people/") ? "person" : pathname.slice(1).split("/")[0] || "dashboard";
  const personRouteId = currentView === "person" ? pathname.split("/")[2] : null;
  const { token, setToken, isAuthenticated, sessionMessage, clearSession, request, currentUser } = useLifePilotSession(api);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [personOrganizations, setPersonOrganizations] = useState<Membership[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [gifts, setGifts] = useState<Gift[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [eventParticipantResetKey, setEventParticipantResetKey] = useState(0);
  const [notifications, setNotifications] = useState<Reminder[]>([]);
  const [captures, setCaptures] = useState<Capture[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selectedSuggestions, setSelectedSuggestions] = useState<Record<string, number[]>>({});
  const [captureBusy, setCaptureBusy] = useState(false);
  const [selectedPerson, setSelectedPersonState] = useState<Person | null>(null);
  const setSelectedPerson = (person: Person | null) => {
    if (person === null && currentView === "person") { window.location.assign("/people"); return; }
    setSelectedPersonState(person);
  };
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [personNames, setPersonNames] = useState<PersonName[]>([]);
  const [dailyBriefing, setDailyBriefing] = useState<DailyBriefing | null>(null);
  const [personBriefing, setPersonBriefing] = useState<PersonBriefing | null>(null);
  const [searchRelationships, setSearchRelationships] = useState<Relationship[]>([]);
  const [searchLifeEvents, setSearchLifeEvents] = useState<{ id: string; title: string; details: string; occurred_at?: string | null; date_precision: string; source_capture_id?: string | null }[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [showProfile, setShowProfile] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [personFilter, setPersonFilter] = useState("");
  const [personSort, setPersonSort] = useState("name");
  const [personKindFilter, setPersonKindFilter] = useState("all");
  const [chatMode, setChatMode] = useState<"capture" | "ask">("capture");
  const [chatEntries, setChatEntries] = useState<ChatEntry[]>([]);
  const [activeCaptureId, setActiveCaptureId] = useState<string | null>(null);
  const [chatBusy, setChatBusy] = useState(false);
  const [message, setMessage] = useState("");

  function appendChatEntry(entry: ChatEntry) {
    setChatEntries(entries => {
      const next = [...entries, entry];
      const modeEntries = next.filter(item => item.mode === entry.mode).slice(-MAX_CHAT_HISTORY_ENTRIES);
      return [...next.filter(item => item.mode !== entry.mode), ...modeEntries];
    });
  }

  useEffect(() => {
    if ("serviceWorker" in navigator && window.isSecureContext) {
      void navigator.serviceWorker.register("/sw.js").catch(() => setMessage("Offline-Speicherung konnte nicht aktiviert werden."));
    }
  }, []);

  async function refresh() {
    try {
      const [p, m, t, c, l, g, e, n, inbox, projectRows, approvalRows, briefing, orgs] = await Promise.all([request<Person[]>("/api/people"), request<Memory[]>("/api/memories"), request<Task[]>("/api/tasks?status=open"), request<Conversation[]>("/api/conversations"), request<Loan[]>("/api/loans"), request<Gift[]>("/api/gifts"), request<Event[]>("/api/events"), request<Reminder[]>("/api/notifications"), request<Capture[]>("/api/captures"), request<Project[]>("/api/projects"), request<Approval[]>("/api/approvals"), request<DailyBriefing>("/api/briefing/daily"), request<Organization[]>("/api/organizations")]);
      setPeople(p); setMemories(m); setTasks(t); setConversations(c); setLoans(l); setGifts(g); setEvents(e); setNotifications(n); setCaptures(inbox); setProjects(projectRows); setApprovals(approvalRows); setDailyBriefing(briefing); setOrganizations(orgs);
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
  }
  useEffect(() => {
    if (!isAuthenticated) return;
    void Promise.all([refresh(), request<Profile>("/api/profile")])
      .then(([, currentProfile]) => setProfile(currentProfile))
      .catch(error => setMessage(error instanceof Error ? error.message : String(error)));
  }, [isAuthenticated]);
  useEffect(() => {
    if (currentView === "settings") setShowProfile(true);
    if (personRouteId && token && people.length > 0 && selectedPerson?.id !== personRouteId) {
      const person = people.find(item => item.id === personRouteId);
      if (person) void selectPerson(person);
    }
    if (currentView === "people" && !personRouteId) setSelectedPerson(null);
  }, [currentView, personRouteId, token, people, selectedPerson?.id]);
  useEffect(() => {
    if (!token || !captures.some(item => item.status === "pending")) return;
    const timer = window.setInterval(() => { void request<Capture[]>("/api/captures").then(setCaptures).catch(error => setMessage(String(error))); }, 3000);
    return () => window.clearInterval(timer);
  }, [captures, token]);
  useEffect(() => {
    if (currentView !== "chat" || chatEntries.some(entry => entry.mode === "capture")) return;
    const history = captures.filter(item => item.source === "chat").sort((left, right) => left.created_at.localeCompare(right.created_at)).slice(-MAX_CHAT_CAPTURE_THREADS);
    if (history.length === 0) {
      setActiveCaptureId(null);
      return;
    }
    setChatEntries(entries => [...entries.filter(entry => entry.mode !== "capture"), ...history.flatMap(item => [
      { id: `${item.id}-user`, mode: "capture" as const, role: "user" as const, text: item.original_text },
      { id: `${item.id}-assistant`, mode: "capture" as const, role: "assistant" as const, text: item.status === "pending" ? "Die Analyse läuft …" : item.status === "ready" ? "Hier sind die noch offenen Vorschläge." : item.status === "reviewed" ? "Alle Vorschläge aus dieser Eingabe wurden umgesetzt." : item.processing_error || "Originaltext gespeichert.", captureId: item.id },
    ])]);
    setActiveCaptureId(history.at(-1)?.id ?? null);
  }, [currentView, captures, chatEntries]);

  async function selectPerson(person: Person) {
    if (currentView !== "person") { window.location.assign(`/people/${person.id}`); return; }
    setSelectedPerson(person);
    try {
      const [full, links, briefing, names, memberships] = await Promise.all([request<Person>(`/api/people/${person.id}`), request<Relationship[]>(`/api/relationships?person_id=${person.id}`), request<PersonBriefing>(`/api/briefing/person/${person.id}`), request<PersonName[]>(`/api/people/${person.id}/names`), request<Membership[]>(`/api/people/${person.id}/organizations`)]);
      setSelectedPerson(full); setRelationships(links); setPersonBriefing(briefing); setPersonNames(names); setPersonOrganizations(memberships);
    } catch (error) { setMessage(String(error)); }
  }
  async function savePerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const form = new FormData(event.currentTarget);
    try {
      const saved = await request<Person>(`/api/people/${selectedPerson.id}`, { method: "PATCH", body: JSON.stringify({ first_name: form.get("first_name"), last_name: form.get("last_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, gender: form.get("gender"), email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", website: form.get("website") || null, job_title: form.get("job_title") || null, organization: form.get("organization") || null, notes: form.get("notes") || "" }) });
      setSelectedPerson(saved); await refresh(); setMessage("Profil gespeichert");
    } catch (error) { setMessage(String(error)); }
  }
  async function uploadPersonPhoto(file: File) {
    if (!selectedPerson || !token) return;
    try {
      const response = await fetch(`${api}/api/people/${selectedPerson.id}/photo`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: (() => { const data = new FormData(); data.set("file", file); return data; })() });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Profilbild konnte nicht gespeichert werden");
      const saved = await response.json() as Person;
      setSelectedPerson(saved); await refresh(); setMessage("Profilbild gespeichert");
    } catch (error) { setMessage(String(error)); }
  }
  async function createOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try {
      await request("/api/organizations", { method: "POST", body: JSON.stringify({ name: form.get("organization_name"), organization_type: form.get("organization_type"), notes: "" }) });
      formElement.reset(); await refresh(); setMessage("Verein gespeichert. Du kannst jetzt Personen verbinden.");
    } catch (error) { setMessage(String(error)); }
  }
  async function addOrganizationMembership(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const formElement = event.currentTarget; const form = new FormData(formElement);
    try {
      await request(`/api/people/${selectedPerson.id}/organizations`, { method: "POST", body: JSON.stringify({ organization_id: form.get("organization_id"), role: form.get("role") || "" }) });
      formElement.reset(); await refresh(); await selectPerson(selectedPerson); setMessage("Mitgliedschaft gespeichert");
    } catch (error) { setMessage(String(error)); }
  }
  async function removeOrganizationMembership(membership: Membership) {
    try {
      await request(`/api/organizations/${membership.organization_id}/members/${membership.person_id}`, { method: "DELETE" });
      if (selectedPerson) await selectPerson(selectedPerson);
      await refresh();
    } catch (error) { setMessage(String(error)); }
  }
  async function saveRelationship(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const relationshipForm = event.currentTarget;
    const form = new FormData(relationshipForm);
    try {
      await request("/api/relationships", { method: "POST", body: JSON.stringify({ source_person_id: selectedPerson.id, target_person_id: form.get("target_id"), relationship_type: form.get("relationship_type") }) });
      relationshipForm.reset(); await selectPerson(selectedPerson);
    } catch (error) { setMessage(String(error)); }
  }
  async function deleteRelationship(id: string) {
    try { await request(`/api/relationships/${id}`, { method: "DELETE" }); setRelationships(links => links.filter(link => link.id !== id)); }
    catch (error) { setMessage(String(error)); }
  }
  async function saveOwnerRelationship(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedPerson) return;
    const relationshipForm = event.currentTarget;
    const form = new FormData(relationshipForm);
    try {
      await request(`/api/people/${selectedPerson.id}/owner-relationships`, { method: "POST", body: JSON.stringify({ relationship_type: form.get("relationship_type"), valid_from: form.get("valid_from") ? new Date(`${form.get("valid_from")}T00:00:00`).toISOString() : null }) });
      relationshipForm.reset(); await selectPerson(selectedPerson); setMessage("Beziehung zu dir gespeichert");
    } catch (error) { setMessage(String(error)); }
  }
  async function deleteOwnerRelationship(id: string) {
    try { await request(`/api/owner-relationships/${id}`, { method: "DELETE" }); if (selectedPerson) await selectPerson(selectedPerson); }
    catch (error) { setMessage(String(error)); }
  }
  async function login(event: FormEvent) {
    event.preventDefault(); clearSession(); setMessage("");
    try { const result = await request<{ access_token: string }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }); setToken(result.access_token); }
    catch (error) { setMessage(String(error)); }
  }
  async function createPerson(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/people", { method: "POST", body: JSON.stringify({ first_name: form.get("first_name"), last_name: form.get("last_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, gender: form.get("gender"), email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", website: form.get("website") || null, job_title: form.get("job_title") || null, organization: form.get("organization") || null, notes: form.get("notes") || "" }) }); formElement.reset(); setMessage("Person gespeichert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function capture(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const content = String(form.get("content") ?? "").trim();
    if (!content) return;
    setCaptureBusy(true);
    try { const saved = await request<Capture>("/api/captures", { method: "POST", body: JSON.stringify({ original_text: content }) }); formElement.reset(); setActiveCaptureId(saved.id); setMessage(saved.status === "pending" ? "Originaltext gespeichert. Die KI erstellt Vorschläge im Hintergrund." : saved.status === "ready" ? "Eingabe gespeichert. Bitte prüfe die Vorschläge im Eingang." : saved.processing_error || "Originaltext gespeichert."); await refresh(); }
    catch (error) { setMessage(String(error)); }
    finally { setCaptureBusy(false); }
  }
  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/projects", { method: "POST", body: JSON.stringify({ name: form.get("name"), description: form.get("description") || "" }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function updateProject(event: FormEvent<HTMLFormElement>, projectId: string) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { await request("/api/projects/" + projectId, { method: "PATCH", body: JSON.stringify({ name: form.get("name"), description: form.get("description"), status: form.get("status") }) }); setMessage("Projekt aktualisiert"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function decideApproval(id: string, decision: "approve" | "reject") {
    try { await request("/api/approvals/" + id + "/" + decision, { method: "POST" }); setMessage(decision === "approve" ? "Freigabe ausgeführt" : "Freigabe abgelehnt"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function reviewCapture(item: Capture, selected?: number[]): Promise<boolean> {
    const accepted = selected ?? selectedSuggestions[item.id] ?? item.suggestions.map((_, index) => index);
    if (accepted.length === 0) return true;
    const personAssignments = Object.fromEntries(accepted.flatMap(index => { const choice = document.querySelector<HTMLSelectElement>(`[name="capture-person-${item.id}-${index}"]`)?.value; return choice ? [[index, choice]] : []; }));
    const relatedPersonAssignments = Object.fromEntries(accepted.flatMap(index => { const choice = document.querySelector<HTMLSelectElement>(`[name="capture-related-person-${item.id}-${index}"]`)?.value; return choice ? [[index, choice]] : []; }));
    const projectAssignments = Object.fromEntries(accepted.flatMap(index => { const choice = document.querySelector<HTMLSelectElement>(`[name="capture-project-${item.id}-${index}"]`)?.value; return choice ? [[index, choice]] : []; }));
    const createPeople = accepted.filter(index => document.querySelector<HTMLInputElement>(`[name="capture-create-person-${item.id}-${index}"]`)?.checked);
    const createRelatedPeople = accepted.filter(index => document.querySelector<HTMLInputElement>(`[name="capture-create-related-${item.id}-${index}"]`)?.checked);
    const confirmations = [...new Set([...accepted.filter(index => document.querySelector<HTMLInputElement>(`[name="capture-confirm-${item.id}-${index}"]`)?.checked), ...createPeople, ...createRelatedPeople])];
    try {
      await request(`/api/captures/${item.id}/review`, { method: "POST", body: JSON.stringify({ accepted_indices: accepted, person_assignments: personAssignments, related_person_assignments: relatedPersonAssignments, project_assignments: projectAssignments, create_people: createPeople, create_related_people: createRelatedPeople, confirmations }) });
      setSelectedSuggestions(current => ({ ...current, [item.id]: [] }));
      setMessage(`${accepted.length} geprüfte Änderungen übernommen`);
      await refresh();
      return true;
    } catch (error) { setMessage(String(error)); return false; }
  }
  async function discardCapture(item: Capture) {
    try { await request(`/api/captures/${item.id}`, { method: "DELETE" }); setMessage("Eingabe gelöscht"); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function continueCapture(event: FormEvent<HTMLFormElement>, parentCaptureId: string) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const content = String(form.get("follow_up") ?? "").trim();
    if (!content) return;
    try {
      const saved = await request<Capture>("/api/captures", { method: "POST", body: JSON.stringify({ original_text: content, parent_capture_id: parentCaptureId }) });
      formElement.reset();
      setActiveCaptureId(saved.id);
      setMessage("Nachtrag gespeichert. Die Vorschläge berücksichtigen jetzt den bisherigen Verlauf.");
      await refresh();
    } catch (error) { setMessage(String(error)); }
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
    const personId = String(form.get("person_id") ?? "");
    const dueDate = String(form.get("due_at") ?? "");
    const isLentByMe = form.get("direction") === "lent";
    try { await request("/api/loans", { method: "POST", body: JSON.stringify({ item_name: form.get("item_name"), lender_person_id: isLentByMe ? null : personId || null, borrower_person_id: isLentByMe ? personId || null : null, due_at: dueDate ? `${dueDate}T12:00:00Z` : null }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function createGift(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request("/api/gifts", { method: "POST", body: JSON.stringify({ person_id: form.get("person_id"), title: form.get("title"), occasion: form.get("occasion") || "" }) }); formElement.reset(); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function returnLoan(id: string) { try { await request(`/api/loans/${id}/return`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function createEvent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement); const participants = form.getAll("participant_ids").map(String);
    try { await request("/api/events", { method: "POST", body: JSON.stringify({ title: form.get("title"), location: form.get("location") || "", starts_at: utcDateTime(form.get("starts_at")), participant_ids: participants }) }); formElement.reset(); setEventParticipantResetKey(current => current + 1); await refresh(); }
    catch (error) { setMessage(String(error)); }
  }
  async function updateEvent(event: FormEvent<HTMLFormElement>, id: string) {
    event.preventDefault(); const formElement = event.currentTarget; const form = new FormData(formElement);
    try { await request(`/api/events/${id}`, { method: "PATCH", body: JSON.stringify({ title: form.get("title"), starts_at: utcDateTime(form.get("starts_at")), location: form.get("location") || "", participant_ids: form.getAll("participant_ids").map(String) }) }); await refresh(); setMessage("Termin wurde aktualisiert; die Erinnerung ist angepasst"); }
    catch (error) { setMessage(String(error)); }
  }
  async function deleteRecord(path: string, label: string) {
    if (!window.confirm(`${label} wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.`)) return;
    try { await request(path, { method: "DELETE" }); if (selectedPerson && path === `/api/people/${selectedPerson.id}`) { setSelectedPerson(null); window.location.assign("/people"); } await refresh(); setMessage(`${label} gelöscht`); }
    catch (error) { setMessage(String(error)); }
  }
  async function sendChatMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const text = String(form.get("chat_message") ?? "").trim();
    if (!text || chatBusy) return;
    setChatBusy(true);
    appendChatEntry({ id: crypto.randomUUID(), mode: chatMode, role: "user", text });
    formElement.reset();
    try {
      if (chatMode === "capture") {
        const activeCapture = captures.find(item => item.id === activeCaptureId);
        const checkedSuggestions = activeCapture ? selectedSuggestions[activeCapture.id] ?? [] : [];
        if (activeCapture?.status === "ready" && checkedSuggestions.length > 0) {
          const applied = await reviewCapture(activeCapture, checkedSuggestions);
          if (!applied) throw new Error("Die ausgewählten Vorschläge konnten nicht übernommen werden. Bitte prüfe die Zuordnungen im Chat.");
        }
        const saved = await request<Capture>("/api/captures", { method: "POST", body: JSON.stringify({ original_text: text, parent_capture_id: activeCaptureId, source: "chat" }) });
        setActiveCaptureId(saved.id);
        setCaptures(current => [saved, ...current.filter(item => item.id !== saved.id)]);
        const status = saved.status === "pending" ? "Dein Text ist gespeichert. Ich prüfe jetzt, welche offenen Punkte deine Nachricht ergänzt." : saved.processing_error || "Dein Originaltext wurde gespeichert. Die offenen Vorschläge bleiben hier im Chat.";
        appendChatEntry({ id: crypto.randomUUID(), mode: "capture", role: "assistant", text: status, captureId: saved.id });
      } else {
        const response = await request<{ answer: string; sources: ChatSource[] }>("/api/chat/ask", { method: "POST", body: JSON.stringify({ question: text }) });
        appendChatEntry({ id: crypto.randomUUID(), mode: "ask", role: "assistant", text: response.answer, sources: response.sources });
      }
    } catch (error) {
      appendChatEntry({ id: crypto.randomUUID(), mode: chatMode, role: "assistant", text: `Das hat nicht funktioniert: ${String(error)}` });
    } finally {
      setChatBusy(false);
    }
  }
  function utcDateTime(value: FormDataEntryValue | null) { return value ? new Date(String(value)).toISOString() : null; }
  function localDateTime(value: string) { const date = new Date(value); const offset = date.getTimezoneOffset() * 60000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
  async function finishReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "done" }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function snoozeReminder(id: string) { try { await request(`/api/reminders/${id}`, { method: "PATCH", body: JSON.stringify({ state: "scheduled", snoozed_until: new Date(Date.now() + 60 * 60 * 1000).toISOString() }) }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function complete(id: string) { try { await request(`/api/tasks/${id}/complete`, { method: "PATCH" }); await refresh(); } catch (error) { setMessage(String(error)); } }
  async function search(event: FormEvent) { event.preventDefault(); try { const result = await request<{ people: Person[]; memories: Memory[]; tasks: Task[]; conversations: Conversation[]; relationships: Relationship[]; projects: Project[]; life_events: { id: string; title: string; details: string; occurred_at?: string | null; date_precision: string; source_capture_id?: string | null }[] }>(`/api/search?q=${encodeURIComponent(query)}`); setPeople(result.people); setMemories(result.memories); setTasks(result.tasks); setConversations(result.conversations); setProjects(result.projects); setSearchRelationships(result.relationships); setSearchLifeEvents(result.life_events); } catch (error) { setMessage(String(error)); } }

  async function reindexMemories() {
    try {
      const result = await request<{ queued: number; failed: number }>("/api/search/reindex", { method: "POST" });
      setMessage(result.failed ? result.queued + " Einträge eingeplant; " + result.failed + " konnten nicht eingereiht werden" : result.queued + " Einträge für die semantische Suche eingeplant");
    } catch (error) { setMessage(String(error)); }
  }

  if (!token || !isAuthenticated) return <main className="login"><div className="brand">L<span>·</span>P</div><p className="eyebrow">DEIN PERSÖNLICHES GEDÄCHTNIS</p><h1>Alles Wichtige<br />im Kopf. Ohne Kopf.</h1><form onSubmit={login} className="card stack"><label>Benutzername<input value={username} onChange={e => setUsername(e.target.value)} /></label><label>Passwort<input type="password" value={password} onChange={e => setPassword(e.target.value)} /></label><button>Anmelden</button>{(sessionMessage || message) && <p className="error">{sessionMessage || message}</p>}</form></main>;

  const navItems: [string, string][] = [["/", "Übersicht"], ["/chat", "Chat"], ["/people", "Menschen"], ["/memory", "Gedächtnis"], ["/events", "Ereignisse"], ["/planning", "Planung"], ["/things", "Gegenstände"], ["/inbox", "Eingang"], ["/settings", "Einstellungen"]];
  if (currentUser?.role === "admin") navItems.push(["/admin", "Administration"]);
  const pageTitle = currentView === "person" ? (selectedPerson ? `${selectedPerson.first_name} ${selectedPerson.last_name}` : "Personenprofil") : ({ dashboard: "Übersicht", chat: "Chat", people: "Menschen", memory: "Gedächtnis", events: "Ereignisse", planning: "Planung", things: "Gegenstände", inbox: "Eingang", settings: "Einstellungen", admin: "Administration" } as Record<string, string>)[currentView] ?? "LifePilot";
  const inboxCaptures = currentView === "inbox" ? captures.filter(item => item.source !== "chat").slice(0, 30) : captures.filter(item => item.source !== "chat" && item.status !== "reviewed").slice(0, 5);
  const searchablePeople = people.filter(person => `${person.first_name} ${person.last_name} ${person.nickname ?? ""} ${person.email ?? ""} ${person.phone ?? ""} ${person.organization ?? ""} ${organizations.filter(org => org.members.some(member => member.person_id === person.id)).map(org => org.name).join(" ")}`.toLocaleLowerCase("de-DE").includes(personFilter.trim().toLocaleLowerCase("de-DE"))).filter(person => personKindFilter === "all" || (personKindFilter === "birthday" && Boolean(person.birthday)) || (personKindFilter === "photo" && Boolean(person.photo_key)) || (personKindFilter === "organization" && organizations.some(org => org.members.some(member => member.person_id === person.id))));
  const sortedPeople = [...searchablePeople].sort((left, right) => {
    if (personSort === "age") return (calculateAge(right.birthday) ?? -1) - (calculateAge(left.birthday) ?? -1);
    if (personSort === "birthday") return (left.birthday ?? "9999-99-99").slice(5).localeCompare((right.birthday ?? "9999-99-99").slice(5));
    if (personSort === "recent") return right.created_at.localeCompare(left.created_at);
    return `${left.first_name} ${left.last_name}`.localeCompare(`${right.first_name} ${right.last_name}`, "de");
  });
  const relationshipGroups = [
    { title: "Familie", items: relationships.filter(link => /mutter|vater|eltern|tochter|sohn|kind|geschwister|bruder|schwester|ehepartner|ehefrau|ehemann|partner/i.test(`${link.relationship_type} ${link.inverse_relationship_type}`)) },
    { title: "Freunde", items: relationships.filter(link => /freund/i.test(`${link.relationship_type} ${link.inverse_relationship_type}`)) },
    { title: "Arbeitskollegen", items: relationships.filter(link => /kolleg|arbeit|chef|mitarbeiter/i.test(`${link.relationship_type} ${link.inverse_relationship_type}`)) },
    { title: "Weitere Beziehungen", items: relationships.filter(link => !/mutter|vater|eltern|tochter|sohn|kind|geschwister|bruder|schwester|ehepartner|ehefrau|ehemann|partner|freund|kolleg|arbeit|chef|mitarbeiter/i.test(`${link.relationship_type} ${link.inverse_relationship_type}`)) },
  ].filter(group => group.items.length > 0);
  return <main className="shell" data-view={currentView}><aside className="sidebar"><a className="brand" href="/">L<span>·</span>P</a><p className="eyebrow">LIFEPILOT</p><nav aria-label="Hauptnavigation">{navItems.map(([href, label]) => <a key={href} href={href} className={currentView === (href === "/" ? "dashboard" : href.slice(1)) || (currentView === "person" && href === "/people") ? "active" : undefined}>{label}</a>)}</nav><div className="profile"><div className="avatar">{username[0]?.toUpperCase()}</div><div>{profile?.full_name || username}<small>Persönlicher Bereich</small></div><button className="quiet" onClick={() => clearSession()}>Abmelden</button></div></aside>
    <section className="content"><header><div><p className="eyebrow">DEIN ZWEITGEDÄCHTNIS</p><h1>{pageTitle}</h1><p className="muted">{currentView === "chat" ? "Erfasse Gedanken oder frage dein gespeichertes Gedächtnis." : currentView === "people" ? "Kontakte und ihre Beziehungen" : currentView === "planning" ? "Aufgaben und Termine" : currentView === "memory" ? "Gespräche, Ereignisse und Notizen" : currentView === "things" ? "Leihgaben und Geschenkideen" : currentView === "inbox" ? "Eingaben prüfen und zuordnen" : currentView === "settings" ? "Dein persönliches Profil" : "Was möchtest du heute festhalten?"}</p></div><div className="header-actions"><span className="date">{new Intl.DateTimeFormat("de-DE", { dateStyle: "full" }).format(new Date())}</span><button type="button" onClick={() => setCaptureOpen(true)}>Schnellerfassung</button>{selectedPerson && !selectedPerson.is_self && currentView === "person" && <button type="button" className="danger-button" onClick={() => void deleteRecord(`/api/people/${selectedPerson.id}`, "Person")}>Person löschen</button>}<a className="quiet profile-toggle" href="/settings">{profile?.full_name || profile?.username || "Mein Profil"}</a></div></header>
      {currentView === "chat" && <section className="card panel chat-panel"><div className="chat-modes" role="group" aria-label="Chat-Modus"><button type="button" className={chatMode === "capture" ? "selected" : "quiet"} aria-pressed={chatMode === "capture"} onClick={() => setChatMode("capture")}>Festhalten</button><button type="button" className={chatMode === "ask" ? "selected" : "quiet"} aria-pressed={chatMode === "ask"} onClick={() => setChatMode("ask")}>Fragen</button></div><p className="chat-guidance">{chatMode === "capture" ? "Schreib frei, was du festhalten möchtest. Du entscheidest direkt hier, welche Vorschläge gespeichert werden." : "Frage nach Personen, Gesprächen, Aufgaben, Terminen, Leihgaben und anderen gespeicherten Informationen. Antworten stützen sich auf angezeigte Datenbankquellen."}</p>{chatMode === "capture" && <div className="chat-review-note">Hake passende Vorschläge ab und übernimm sie hier. Beim nächsten Chatbeitrag werden ausgewählte Punkte zuerst gespeichert; offene Vorschläge bleiben sichtbar.</div>}<p className="chat-history-note">Es werden höchstens die letzten {MAX_CHAT_HISTORY_ENTRIES} Nachrichten dieses Modus angezeigt. Ältere Festhalten-Eingaben bleiben gespeichert.</p><div className="chat-transcript" aria-live="polite">{chatEntries.filter(entry => entry.mode === chatMode).length === 0 ? <p className="empty">{chatMode === "capture" ? "Zum Beispiel: „Ich habe Anna heute getroffen und wir haben über ihren Umzug gesprochen.“" : "Zum Beispiel: „Wem habe ich meine Bohrmaschine geliehen?“"}</p> : chatEntries.filter(entry => entry.mode === chatMode).slice(-MAX_CHAT_HISTORY_ENTRIES).map(entry => <article className={`chat-entry ${entry.role}`} key={entry.id}><p>{entry.text}</p>{entry.sources?.map(source => <a className="chat-source" key={`${source.kind}-${source.id}`} href={source.href}><strong>{source.title}</strong><small>{source.kind} · {source.excerpt || "Gespeicherter Datensatz"}</small></a>)}{entry.captureId && (() => { const capture = captures.find(item => item.id === entry.captureId); if (!capture) return <p>Vorschläge werden geladen.</p>; return <CaptureChatReview capture={capture} people={people} projects={projects} selectedIndices={selectedSuggestions[capture.id] ?? []} busy={chatBusy} onToggle={(index, checked) => setSelectedSuggestions(current => { const selected = current[capture.id] ?? []; return { ...current, [capture.id]: checked ? [...selected, index] : selected.filter(value => value !== index) }; })} onApply={() => void reviewCapture(capture, selectedSuggestions[capture.id] ?? [])} />; })()}</article>)}</div><form className="chat-composer" onSubmit={event => void sendChatMessage(event)}><label htmlFor="chat-message">{chatMode === "capture" ? "Was möchtest du festhalten?" : "Deine Frage"}</label><textarea id="chat-message" name="chat_message" rows={3} maxLength={2000} required placeholder={chatMode === "capture" ? "Schreib einfach los …" : "Frag dein persönliches Gedächtnis …"} /><button disabled={chatBusy}>{chatBusy ? "Wird verarbeitet …" : chatMode === "capture" ? "Nachricht senden" : "Frage stellen"}</button></form></section>}
      {currentView === "people" && <div className="people-toolbar"><label>Personen suchen<input type="search" value={personFilter} onChange={event => setPersonFilter(event.target.value)} placeholder="Name, Spitzname, Verein oder Kontakt …" /></label><label>Filtern<select value={personKindFilter} onChange={event => setPersonKindFilter(event.target.value)}><option value="all">Alle Personen</option><option value="birthday">Mit Geburtstag</option><option value="photo">Mit Profilbild</option><option value="organization">Mit Verein/Organisation</option></select></label><label>Sortieren<select value={personSort} onChange={event => setPersonSort(event.target.value)}><option value="name">Name</option><option value="age">Alter</option><option value="birthday">Nächster Geburtstag</option><option value="recent">Zuletzt hinzugefügt</option></select></label></div>}
      {captureOpen && <dialog open className="capture-dialog"><div className="panel-head"><h2>Schnellerfassung</h2><button type="button" className="quiet" onClick={() => setCaptureOpen(false)}>Schließen</button></div><form onSubmit={event => { setCaptureOpen(false); void capture(event); }}><label>Gedanke oder Gespräch<textarea name="content" autoFocus required placeholder="Schreib einfach los …" /></label><button>Speichern</button></form></dialog>}
      {showProfile && profile && <AccountSettingsPanel profile={profile} request={request} onClose={() => setShowProfile(false)} onMessage={setMessage} onProfileSaved={saved => { setProfile(saved); void refresh(); }} />}
      {message && <p className="notice" role="status">{message}<button className="quiet" onClick={() => setMessage("")}>×</button></p>}
      {notifications.length > 0 && <section className="card panel notification-panel"><div className="panel-head"><div><span className="eyebrow">JETZT FÄLLIG</span><h2>Erinnerungen</h2></div><span className="count">{notifications.length}</span></div>{notifications.map(n => <div className="list-item" key={n.id}><span>{n.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short" }).format(new Date(n.due_at))}</small></span><button className="quiet" onClick={() => void snoozeReminder(n.id)}>+1 Std.</button><button className="quiet" onClick={() => void finishReminder(n.id)}>Erledigt</button></div>)}</section>}
      {dailyBriefing && <section className="card panel briefing-panel"><div className="panel-head"><div><span className="eyebrow">TAGESBRIEFING · {new Intl.DateTimeFormat("de-DE", { dateStyle: "full", timeZone: dailyBriefing.timezone }).format(new Date(`${dailyBriefing.date}T12:00:00Z`))}</span><h2>Das steht heute an</h2></div><span className="count">{dailyBriefing.today_events.length + dailyBriefing.open_tasks.length + dailyBriefing.upcoming_reminders.length}</span></div>{dailyBriefing.today_events.length === 0 && dailyBriefing.open_tasks.length === 0 && dailyBriefing.upcoming_reminders.length === 0 && <p className="empty">Heute ist nichts geplant. Hier erscheinen Termine, offene Aufgaben und Wiedervorlagen.</p>}{dailyBriefing.today_events.map(event => <div className="list-item" key={event.id}><span>{event.title}<small>{new Intl.DateTimeFormat("de-DE", { timeStyle: "short", timeZone: dailyBriefing.timezone }).format(new Date(event.starts_at))}{event.location ? ` · ${event.location}` : ""} · Termin</small></span></div>)}{dailyBriefing.open_tasks.slice(0, 5).map(task => <div className="list-item" key={task.id}><span>{task.title}<small>{task.due_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeZone: dailyBriefing.timezone }).format(new Date(task.due_at)) : "Ohne Fälligkeit"} · Aufgabe</small></span></div>)}{dailyBriefing.upcoming_reminders.slice(0, 5).map(reminder => <div className="list-item" key={reminder.id}><span>{reminder.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "short", timeStyle: "short", timeZone: dailyBriefing.timezone }).format(new Date(reminder.due_at))} · Wiedervorlage</small></span></div>)}</section>}
      <section className="capture card"><div><span className="eyebrow">SCHNELLERFASSUNG</span><h2>Ein Gedanke, gut aufgehoben.</h2></div><form onSubmit={capture}><textarea name="content" placeholder="Schreib einfach los. Ein Gespräch, eine Idee, etwas zum Erinnern …" required /><div className="row"><span className="muted">Dein Original bleibt erhalten.</span><button disabled={captureBusy}>{captureBusy ? "Wird gespeichert …" : <>Speichern <span aria-hidden="true">↗</span></>}</button></div></form></section>
      <section id="dashboard-panels" className="grid domain-grid">
        <section className="card panel"><div className="panel-head"><div><span className="eyebrow">VORHABEN</span><h2>Projekte</h2></div><span className="count">{projects.length}</span></div><form className="inline-form" onSubmit={createProject}><input name="name" placeholder="Projektname" required /><input name="description" placeholder="Beschreibung (optional)" /><button aria-label="Projekt speichern">+</button></form>{projects.slice(0, 5).map(project => <details className="project-item" key={project.id}><summary className="list-item"><span>{project.name}<small>{project.description || project.status}</small></span><span className="muted">{project.status}</span></summary><form className="event-edit-form" onSubmit={event => void updateProject(event, project.id)}><label>Name<input name="name" required defaultValue={project.name} /></label><label>Beschreibung<input name="description" defaultValue={project.description} /></label><label>Status<select name="status" defaultValue={project.status}><option value="active">Aktiv</option><option value="paused">Pausiert</option><option value="completed">Abgeschlossen</option><option value="archived">Archiviert</option></select></label><button>Änderungen speichern</button></form></details>)}</section>
        <section className="card panel"><div className="panel-head"><div><span className="eyebrow">MCP-AKTIONEN</span><h2>Freigaben</h2></div><span className="count">{approvals.length}</span></div>{approvals.length === 0 ? <p className="empty">Keine ausstehenden kritischen Aktionen.</p> : approvals.map(approval => <div className="list-item" key={approval.id}><span>{({ person_delete: "Person löschen", relationship_delete: "Beziehung löschen", memory_delete: "Erinnerung löschen", project_delete: "Projekt löschen", conversation_delete: "Gespräch löschen", task_delete: "Aufgabe löschen", event_delete: "Termin löschen", reminder_delete: "Wiedervorlage löschen", loan_delete: "Leihgabe löschen", gift_delete: "Geschenkidee löschen" } as Record<string, string>)[approval.operation] ?? approval.operation}<small>{approval.resource_label || approval.resource_id}</small></span><button onClick={() => void decideApproval(approval.id, "approve")}>Freigeben</button><button className="quiet" onClick={() => void decideApproval(approval.id, "reject")}>Ablehnen</button></div>)}</section>
      </section>
      <section className="card panel inbox-panel"><div className="panel-head"><div><span className="eyebrow">PRÜFEN & ZUORDNEN</span><h2>Eingang</h2></div><span className="count">{inboxCaptures.length}</span></div>{inboxCaptures.length === 0 ? <p className="empty">Neue Eingaben und KI-Vorschläge erscheinen hier.</p> : inboxCaptures.map(item => <article className="inbox-item" id={`capture-${item.id}`} key={item.id}><p className="inbox-original">{item.original_text}</p>{item.parent_capture_id && <p className="muted">Nachtrag im selben Verlauf · vorherige Erfassung #{item.parent_capture_id.slice(0, 8)}</p>}{item.status === "pending" && <p className="muted">KI-Verarbeitung läuft …</p>}{item.status === "ready" && item.suggestions.map((suggestion, index) => <div className="suggestion-card" key={`${item.id}-${index}`}><label className="suggestion"><input type="checkbox" checked={(selectedSuggestions[item.id] ?? item.suggestions.map((_, suggestionIndex) => suggestionIndex)).includes(index)} onChange={event => setSelectedSuggestions(current => { const selected = current[item.id] ?? item.suggestions.map((_, suggestionIndex) => suggestionIndex); return { ...current, [item.id]: event.target.checked ? [...selected, index] : selected.filter(value => value !== index) }; })} /><span><strong>{({fact:"Fakt",conversation:"Gespräch",relationship:"Beziehung",owner_relationship:"Beziehung zu dir",former_name:"Früherer Name",task:"Aufgabe",event:"Termin",project_link:"Projektverknüpfung",loan:"Leihgabe",life_event:"Lebensereignis"} as Record<string,string>)[suggestion.kind]} · {suggestion.title}</strong><small>{suggestion.content}{suggestion.person_name ? ` · Person: ${suggestion.person_name}` : ""}{suggestion.project_name ? ` · Projekt: ${suggestion.project_name}` : ""}{suggestion.occurred_at ? ` · ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: suggestion.date_precision === "exact" ? "short" : undefined }).format(new Date(suggestion.occurred_at))} (${suggestion.date_precision})` : ""}</small></span></label>{suggestion.person_name && (suggestion.person_candidates.length !== 1 || !suggestion.person_id) && <label>Person zuordnen<select name={`capture-person-${item.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.person_name}</option>{people.map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label>}{suggestion.person_name && !suggestion.person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-person-${item.id}-${index}`} /> Als neue Person anlegen</label>}{suggestion.kind === "relationship" && suggestion.related_person_name && (suggestion.related_person_candidates.length !== 1 || !suggestion.related_person_id) && <label>Zweite Person zuordnen<select name={`capture-related-person-${item.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.related_person_name}</option>{people.map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label>}{suggestion.kind === "relationship" && suggestion.related_person_name && !suggestion.related_person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-related-${item.id}-${index}`} /> Zweite Person neu anlegen</label>}{suggestion.project_name && (suggestion.project_candidates.length !== 1 || !suggestion.project_id) && <label>Projekt zuordnen<select name={`capture-project-${item.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.project_name}</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}{suggestion.confirmation_required && <label className="suggestion-confirm"><input type="checkbox" name={`capture-confirm-${item.id}-${index}`} /> Diese unsichere Zuordnung ausdrücklich bestätigen</label>}</div>)}{item.status === "ready" && item.suggestions.length === 0 && <p className="empty">Keine neuen strukturierten Informationen vorgeschlagen.</p>}{item.processing_error && <p className="muted">{item.processing_error}</p>}<div className="inbox-actions">{item.status === "ready" && <button onClick={() => void reviewCapture(item)}>Geprüfte Änderungen übernehmen</button>}<button className="quiet" onClick={() => void discardCapture(item)}>Eingabe löschen</button></div>{currentView === "inbox" && <form className="capture-follow-up" onSubmit={event => void continueCapture(event, item.id)}><label>Ergänzen oder korrigieren<textarea name="follow_up" rows={2} maxLength={2000} placeholder="Zum Beispiel: Du hast Julian und Lukas als Söhne vergessen …" required /></label><button type="submit">Im Verlauf ergänzen</button></form>}</article>)}</section>
      {captures.filter(item => item.status === "ready" && item.suggestions.some(suggestion => (suggestion.person_name && !suggestion.person_id) || (suggestion.kind === "relationship" && suggestion.related_person_name))).map(item => <section className="card panel" key={`capture-related-${item.id}`}><div className="panel-head"><div><span className="eyebrow">PERSONEN ZUORDNEN</span><h2>Unbekannte Personen prüfen</h2></div></div>{item.suggestions.map((suggestion, index) => <div className="suggestion-card" key={`${item.id}-people-${index}`}>{suggestion.person_name && !suggestion.person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-person-${item.id}-${index}`} /> Neue Person anlegen: {suggestion.person_name}</label>}{suggestion.kind === "relationship" && suggestion.related_person_name && <><label>{suggestion.title}<select name={`capture-related-person-${item.id}-${index}`} defaultValue={suggestion.related_person_id ?? ""}><option value="">Person auswählen: {suggestion.related_person_name}</option>{people.map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}{person.nickname ? ` (${person.nickname})` : ""}</option>)}</select></label>{!suggestion.related_person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-related-${item.id}-${index}`} /> Neue Person anlegen: {suggestion.related_person_name}</label>}</>}</div>)}</section>)}
      <div className="search card"><span>⌕</span><form onSubmit={search}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="LifePilot durchsuchen …" /></form><kbd>↵</kbd><button className="quiet" type="button" aria-label="Semantischen Index erneuern" title="Semantischen Index erneuern" onClick={() => void reindexMemories()}>↻</button></div>
      {searchRelationships.length > 0 && <section className="card panel search-relationships" aria-live="polite"><div className="panel-head"><div><span className="eyebrow">WISSENSGRAPH</span><h2>Gefundene Beziehungen</h2></div><span className="count">{searchRelationships.length}</span></div>{searchRelationships.map(link => <div className="list-item" key={link.id}><span>{link.source_person_name} → {link.target_person_name}<small>{link.relationship_type} · {link.confirmed ? "Bestätigt" : "Noch unbestätigt"}</small></span></div>)}</section>}
      {searchLifeEvents.length > 0 && <section className="card panel" aria-live="polite"><div className="panel-head"><div><span className="eyebrow">BIOGRAFIE</span><h2>Gefundene Lebensereignisse</h2></div><span className="count">{searchLifeEvents.length}</span></div>{searchLifeEvents.map(item => <article className="memory" key={item.id}><span className="memory-dot" /><div><h3>{item.title}</h3><p>{item.details}</p><time>{item.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.occurred_at)) : `Zeitraum: ${item.date_precision}`} · Quelle #{item.source_capture_id?.slice(0, 8) ?? "—"}</time></div></article>)}</section>}
      <div className="grid"><section id="tasks" className="card panel"><div className="panel-head"><div><span className="eyebrow">IM BLICK</span><h2>Aufgaben</h2></div><span className="count">{tasks.length}</span></div><form className="task-form" onSubmit={createTask}><label>Aufgabe<input name="title" placeholder="Neue Aufgabe …" required /></label><label>Fällig am<input name="due_at" type="datetime-local" /></label><label>Alle (Tage)<input name="repeat_interval_days" type="number" min="1" max="365" placeholder="Ohne Wiederholung" /></label><label>Wiederholen bis<input name="repeat_until" type="datetime-local" /></label><button>Aufgabe speichern</button></form>{tasks.length ? tasks.map(t => <div className="list-item" key={t.id}><button className="check" onClick={() => void complete(t.id)} aria-label="Aufgabe abschließen" /><span>{t.title}<small>{t.due_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(t.due_at)) : "Ohne Fälligkeit"}{t.repeat_interval_days ? ` · alle ${t.repeat_interval_days} Tage` : ""}</small></span><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/tasks/${t.id}`, "Aufgabe")}>Löschen</button></div>) : <p className="empty">Alles im Blick. Neue Aufgaben kannst du oben ergänzen.</p>}</section>
      <section id="people" className="card panel"><div className="panel-head"><div><span className="eyebrow">DEIN UMFELD</span><h2>Menschen</h2></div><span className="count">{sortedPeople.length} / {people.length}</span></div><form className="person-form" onSubmit={createPerson}><label>Vorname<input name="first_name" required /></label><label>Nachname<input name="last_name" /></label><label>Spitzname<input name="nickname" /></label><label>Geschlecht<select name="gender" defaultValue="unspecified"><option value="unspecified">Keine Angabe</option><option value="female">Weiblich</option><option value="male">Männlich</option><option value="diverse">Divers</option></select></label><label>Geburtstag<input name="birthday" type="date" /></label><label>E-Mail<input name="email" type="email" /></label><label>Telefon<input name="phone" type="tel" /></label><button>Person hinzufügen</button></form><div className="people-grid">{sortedPeople.map(person => <button className="person-card" key={person.id} onClick={() => void selectPerson(person)}><PersonPhoto person={person} token={token} api={api} className="person-card-photo" /><span className="person-card-name">{person.first_name} {person.last_name}{person.nickname ? ` (${person.nickname})` : ""}</span><span className="person-card-meta">{person.is_self ? "Du · eigenes Profil" : calculateAge(person.birthday) !== null ? `${calculateAge(person.birthday)} Jahre` : "Alter unbekannt"}</span><span className="person-card-meta">{genderName(person.gender)}</span><span className="person-card-meta">{organizations.find(org => org.members.some(member => member.person_id === person.id))?.name ?? person.job_title ?? "Profil öffnen"}</span></button>)}</div>{people.length > 0 && sortedPeople.length === 0 && <p className="empty">Keine passenden Personen. Passe Suche oder Filter an.</p>}</section></div>
{selectedPerson && <section className="card panel person-profile"><div className="person-profile-hero"><PersonPhoto person={selectedPerson} token={token} api={api} className="person-profile-photo" /><div className="person-profile-intro"><span className="eyebrow">PERSONENPROFIL{selectedPerson.is_self ? " · DEIN PROFIL" : ""}</span><h2>{selectedPerson.first_name} {selectedPerson.last_name}</h2><p>{selectedPerson.nickname ? `„${selectedPerson.nickname}“ · ` : ""}{calculateAge(selectedPerson.birthday) !== null ? `${calculateAge(selectedPerson.birthday)} Jahre` : "Alter unbekannt"} · {genderName(selectedPerson.gender)}{selectedPerson.job_title ? ` · ${selectedPerson.job_title}` : ""}</p></div><label className="photo-upload"><span>Profilbild ändern</span><span className="photo-upload-button">Bild auswählen</span><input aria-label="Profilbild auswählen" type="file" accept="image/jpeg,image/png,image/webp" onChange={event => { const file = event.currentTarget.files?.[0]; if (file) void uploadPersonPhoto(file); }} /></label><button type="button" className="quiet" onClick={() => setSelectedPerson(null)}>Schließen</button></div><form key={selectedPerson.id} className="person-form" onSubmit={savePerson}><label>Vorname<input name="first_name" defaultValue={selectedPerson.first_name} required /></label><label>Nachname<input name="last_name" defaultValue={selectedPerson.last_name} /></label><label>Spitzname<input name="nickname" defaultValue={selectedPerson.nickname ?? ""} /></label><label>Geburtstag<input name="birthday" type="date" defaultValue={selectedPerson.birthday ?? ""} /></label><label>Geschlecht<select name="gender" defaultValue={selectedPerson.gender ?? "unspecified"}><option value="unspecified">Keine Angabe</option><option value="female">Weiblich</option><option value="male">Männlich</option><option value="diverse">Divers</option></select></label><label>E-Mail<input name="email" type="email" defaultValue={selectedPerson.email ?? ""} /></label><label>Telefon<input name="phone" type="tel" defaultValue={selectedPerson.phone ?? ""} /></label><label>Beruf<input name="job_title" defaultValue={selectedPerson.job_title ?? ""} /></label><label>Organisation<input name="organization" defaultValue={selectedPerson.organization ?? ""} /></label><label>Webseite<input name="website" type="url" defaultValue={selectedPerson.website ?? ""} /></label><label>Adresse<textarea name="address" defaultValue={selectedPerson.address} /></label><label className="wide-field">Notizen<textarea name="notes" defaultValue={selectedPerson.notes} /></label><button type="submit">Profil speichern</button></form><div className="relationship-section"><div className="panel-head"><div><span className="eyebrow">VEREINE & ORGANISATIONEN</span><h3>Mitgliedschaften</h3></div><span className="count">{personOrganizations.length}</span></div>{personOrganizations.length > 0 && <div className="organization-member-grid">{personOrganizations.map(membership => <article className="organization-card" key={membership.id}><div><strong>{membership.organization_name}</strong><span>{membership.role || "Mitglied"}</span><small>{membership.valid_until ? `Bis ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(membership.valid_until))}` : "Aktive Mitgliedschaft"}</small></div><div className="member-avatars">{organizations.find(org => org.id === membership.organization_id)?.members.map(member => <button type="button" className="member-avatar-link" key={member.id} onClick={() => { const person = people.find(candidate => candidate.id === member.person_id); if (person) void selectPerson(person); }} aria-label={`Profil von ${member.person_name} öffnen`}><PersonPhoto person={member} token={token} api={api} className="member-photo" /></button>)}</div><button type="button" className="quiet danger-text" onClick={() => void removeOrganizationMembership(membership)}>Austreten</button></article>)}</div>}{personOrganizations.length === 0 && <p className="empty">Noch keine Mitgliedschaft gespeichert. Auch dein eigenes Profil kann einem Verein zugeordnet werden.</p>}<form className="membership-form" onSubmit={addOrganizationMembership}><label>Verein oder Organisation<select name="organization_id" required defaultValue=""><option value="" disabled>Organisation wählen</option>{organizations.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}</select></label><label>Funktion (optional)<input name="role" placeholder="z. B. Mitglied, Vorstand" /></label><button type="submit" disabled={organizations.length === 0}>Mitgliedschaft hinzufügen</button></form><form className="membership-create-form" onSubmit={createOrganization}><label>Neuen Verein anlegen<input name="organization_name" required maxLength={200} placeholder="z. B. Sportverein Musterstadt" /></label><label>Art<select name="organization_type"><option value="club">Verein</option><option value="company">Unternehmen</option><option value="school">Schule</option><option value="other">Sonstige</option></select></label><button type="submit">Anlegen</button></form></div><div className="relationship-section"><h3>Beziehung zu dir</h3>{personBriefing?.owner_relationships.map(link => <div className="list-item" key={link.id}><span>Du kennst {selectedPerson.first_name} als {link.relationship_type}<small>{link.valid_from ? `Gültig seit ${ownerRelationshipDateFormatter.format(new Date(link.valid_from))}` : "Zeitraum nicht näher eingegrenzt"}{link.source_capture_id ? ` · Quelle #${link.source_capture_id.slice(0, 8)}` : " · Manuell erfasst"}</small></span><button type="button" className="quiet" onClick={() => void deleteOwnerRelationship(link.id)} aria-label="Beziehung zu dir entfernen">Entfernen</button></div>)}{!personBriefing?.owner_relationships.length && <p className="empty">Noch keine Beziehung zu dir gespeichert.</p>}<form className="owner-relationship-form" onSubmit={saveOwnerRelationship}><label>Du kennst diese Person als<select name="relationship_type" required defaultValue=""><option value="" disabled>Beziehung wählen</option><option value="parent">Elternteil</option><option value="child">Kind</option><option value="spouse">Ehepartner:in</option><option value="partner">Partner:in</option><option value="sibling">Geschwister</option><option value="friend">Freund:in</option><option value="colleague">Arbeitskolleg:in</option></select></label><label>Gültig seit (optional)<input name="valid_from" type="date" /></label><button type="submit">Beziehung speichern</button></form></div>{personNames.length > 0 && <div className="relationship-section"><h3>Frühere Namen</h3>{personNames.map(name => <div className="list-item" key={name.id}><span>{name.name}<small>{name.valid_until ? `Gültig bis etwa ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(name.valid_until))}` : "Zeitraum nicht genauer eingegrenzt"} · Quelle #{name.source_capture_id?.slice(0, 8) ?? "—"}</small></span></div>)}</div>}<div className="relationship-section"><div className="panel-head"><div><span className="eyebrow">VERBUNDENE MENSCHEN</span><h3>Beziehungen</h3></div><span className="count">{relationships.length}</span></div>{relationshipGroups.length ? relationshipGroups.map(group => <section className="relationship-group" key={group.title}><h4>{group.title}</h4><div className="relationship-card-grid">{group.items.map(link => { const otherPersonId = link.source_person_id === selectedPerson.id ? link.target_person_id : link.source_person_id; const otherPerson = people.find(person => person.id === otherPersonId); const relationLabel = link.source_person_id === selectedPerson.id ? link.relationship_type : link.inverse_relationship_type; if (!otherPerson) return null; return <article className="relationship-card" key={link.id}><a className="relationship-person-link" href={`/people/${otherPerson.id}`} aria-label={`Profil von ${otherPerson.first_name} ${otherPerson.last_name} öffnen`}><PersonPhoto person={otherPerson} token={token} api={api} className="relationship-photo" /><strong>{otherPerson.first_name} {otherPerson.last_name}</strong><span>{calculateAge(otherPerson.birthday) !== null ? `${calculateAge(otherPerson.birthday)} Jahre` : "Alter unbekannt"}</span><small>{relationLabel}{link.confirmed ? " · Bestätigt" : " · Noch unbestätigt"}</small></a><button type="button" className="relationship-card-remove" title={`Beziehung zu ${otherPerson.first_name} ${otherPerson.last_name} entfernen`} onClick={() => void deleteRelationship(link.id)} aria-label={`Beziehung zu ${otherPerson.first_name} ${otherPerson.last_name} entfernen`}>×</button></article>; })}</div></section>) : <p className="empty">Noch keine Beziehungen gespeichert.</p>}<form className="relationship-form" onSubmit={saveRelationship}><label>Verbinde mit<select name="target_id" required defaultValue=""><option value="" disabled>Person auswählen</option>{people.filter(person => person.id !== selectedPerson.id).map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label><label>Beziehungstyp<select name="relationship_type" required defaultValue=""><option value="" disabled>Beziehung auswählen</option><option value="parent">Elternteil der anderen Person</option><option value="child">Kind der anderen Person</option><option value="spouse">Ehepartner:in</option><option value="partner">Partner:in</option><option value="sibling">Geschwister</option><option value="friend">Freund:in</option><option value="knows">Kennt</option><option value="colleague">Arbeitskolleg:in</option></select></label><button type="submit" disabled={people.length < 2}>Beziehung hinzufügen</button></form></div></section>}
      {selectedPerson && personBriefing && <section className="card panel person-briefing"><div className="panel-head"><div><span className="eyebrow">AUS GESPEICHERTEN QUELLEN</span><h2>Kontext zu {selectedPerson.first_name}</h2></div><span className="count">{personBriefing.conversations.length + personBriefing.memories.length + personBriefing.open_tasks.length + personBriefing.open_loans.length + personBriefing.gift_ideas.length + personBriefing.upcoming_events.length}</span></div>{personBriefing.conversations.map(item => <article className="memory" key={item.id}><span className="memory-dot" /><div><h3>{item.title}</h3><p>{item.summary || item.original_note}</p><time>{item.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.occurred_at)) : "Datum nicht angegeben"} · Gespräch #{item.id.slice(0, 8)}</time></div></article>)}{personBriefing.memories.map(item => <article className="memory" key={item.id}><span className="memory-dot" /><div><h3>{item.title}</h3><p>{item.content}</p><time>{item.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.occurred_at)) : "Erfasst am " + new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.created_at))} · Erinnerung #{item.id.slice(0, 8)}</time></div></article>)}{personBriefing.open_tasks.map(item => <div className="list-item" key={item.id}><span>{item.title}<small>{item.due_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.due_at)) : "Offen"} · Aufgabe #{item.id.slice(0, 8)}</small></span></div>)}{personBriefing.open_loans.map(item => <div className="list-item" key={item.id}><span>{item.item_name}<small>{item.lender_person_id === selectedPerson.id ? "Von dieser Person geliehen" : "An diese Person verliehen"} · Leihgabe #{item.id.slice(0, 8)}</small></span></div>)}{personBriefing.gift_ideas.map(item => <div className="list-item" key={item.id}><span>{item.title}<small>{item.occasion || "Geschenkidee"} · Wunsch #{item.id.slice(0, 8)}</small></span></div>)}{personBriefing.upcoming_events.map(item => <div className="list-item" key={item.id}><span>{item.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(item.starts_at))} · Termin #{item.id.slice(0, 8)}</small></span></div>)}{personBriefing.conversations.length + personBriefing.memories.length + personBriefing.open_tasks.length + personBriefing.open_loans.length + personBriefing.gift_ideas.length + personBriefing.upcoming_events.length === 0 && <p className="empty">Zu dieser Person sind noch keine Kontextdaten gespeichert.</p>}</section>}
      {selectedPerson && personBriefing && personBriefing.life_events.length > 0 && <section className="card panel"><div className="panel-head"><div><span className="eyebrow">BIOGRAFIE</span><h2>Wichtige Lebensereignisse</h2></div><span className="count">{personBriefing.life_events.length}</span></div>{personBriefing.life_events.map(item => <article className="memory" key={item.id}><span className="memory-dot" /><div><h3>{item.title}</h3><p>{item.details}</p><time>{item.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.occurred_at)) : `Zeitraum: ${item.date_precision}`} · Quelle #{item.source_capture_id?.slice(0, 8) ?? "—"}</time></div></article>)}</section>}
      <section id="memories" className="card panel memory-panel"><div className="panel-head"><div><span className="eyebrow">ZULETZT GESPEICHERT</span><h2>Erinnerungen</h2></div><span className="count">{memories.length}</span></div>{memories.length ? memories.slice(0, 6).map(m => <article className="memory" key={m.id}><span className="memory-dot" /><div><h3>{m.title}</h3><p>{m.content}</p><time>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(m.created_at))}</time></div><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/memories/${m.id}`, "Erinnerung")}>Löschen</button></article>) : <p className="empty">Hier erscheinen deine gespeicherten Gedanken und Begegnungen.</p>}</section>
      <div id="memory-domain" className="grid domain-grid"><section className="card panel"><div className="panel-head"><div><span className="eyebrow">EPISODISCHES GEDÄCHTNIS</span><h2>Gespräche</h2></div><span className="count">{conversations.length}</span></div><form className="person-form" onSubmit={createConversation}><input name="title" placeholder="Titel" required /><select name="person_id" defaultValue=""><option value="">Person (optional)</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="occurred_at" type="datetime-local" aria-label="Zeitpunkt" /><input name="location" placeholder="Ort (optional)" /><textarea name="original_note" placeholder="Gesprächsnotiz im Original …" required /><button>Gespräch speichern</button></form>{conversations.slice(0, 4).map(c => <article className="memory" key={c.id}><span className="memory-dot" /><div><h3>{c.title}</h3><p>{c.original_note}</p><time>{c.occurred_at ? new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(c.occurred_at)) : "Zeitpunkt offen"}{c.location ? ` · ${c.location}` : ""}</time></div><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/conversations/${c.id}`, "Gespräch")}>Löschen</button></article>)}</section>
      <section className="card panel"><div className="panel-head"><div><span className="eyebrow">IM UMLAUF</span><h2>Leihgaben</h2></div><span className="count">{loans.length}</span></div><form className="loan-form" onSubmit={createLoan}><input name="item_name" placeholder="Gegenstand" required aria-label="Gegenstand" /><select name="direction" defaultValue="borrowed" aria-label="Leih-Richtung"><option value="borrowed">Von jemandem geliehen</option><option value="lent">An jemanden verliehen</option></select><select name="person_id" defaultValue="" required aria-label="Person"><option value="">Person wählen …</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><label>Rückgabe (optional)<input name="due_at" type="date" /></label><button aria-label="Leihgabe speichern">+</button></form>{loans.map(l => <div className="list-item" key={l.id}><span>{l.item_name}<small>{l.lender_person_id ? `Von ${people.find(p => p.id === l.lender_person_id)?.first_name ?? "Unbekannt"} geliehen` : `An ${people.find(p => p.id === l.borrower_person_id)?.first_name ?? "Unbekannt"} verliehen`}{l.due_at ? ` · Rückgabe bis ${new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(l.due_at))}` : " · Ohne Rückgabedatum"}</small></span><button className="quiet" onClick={() => void returnLoan(l.id)}>Zurück</button><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/loans/${l.id}`, "Leihgabe")}>Löschen</button></div>)}<div className="panel-head gift-heading"><div><span className="eyebrow">VORMERKEN</span><h2>Geschenkideen</h2></div><span className="count">{gifts.length}</span></div><form className="inline-form" onSubmit={createGift}><select name="person_id" defaultValue="" required><option value="">Für wen?</option>{people.map(p => <option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select><input name="title" placeholder="Geschenkidee" required /><input name="occasion" placeholder="Anlass" /><button aria-label="Geschenkidee speichern">+</button></form>{gifts.slice(0, 5).map(g => <div className="list-item" key={g.id}><span>{g.title}<small>{people.find(p => p.id === g.person_id)?.first_name} · {g.occasion || "Idee"}</small></span><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/gifts/${g.id}`, "Geschenkidee")}>Löschen</button></div>)}</section></div>
      <section className="card panel events-panel"><div className="panel-head"><div><span className="eyebrow">VORAUSSCHAU</span><h2>Termine</h2></div><span className="count">{events.filter(item => item.record_type === "appointment").length}</span></div><form className="event-form" onSubmit={createEvent}><label>Titel<input name="title" placeholder="Termin" required /></label><label>Beginn<input name="starts_at" type="datetime-local" required /></label><div className="event-participants"><label htmlFor="new-appointment-participants">Teilnehmende</label><PersonPicker key={eventParticipantResetKey} id="new-appointment-participants" people={people} /></div><label>Ort<input name="location" placeholder="Ort" /></label><button>Termin speichern</button></form>{events.filter(e => e.record_type === "appointment" && new Date(e.starts_at) >= new Date()).slice(0, 5).map(e => <div className="list-item event-item" key={e.id}><span>{e.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium", timeStyle: "short" }).format(new Date(e.starts_at))}{e.location ? ` · ${e.location}` : ""}{e.participant_ids.length ? ` · ${e.participant_ids.map(id => { const p = people.find(person => person.id === id); return p ? `${p.first_name} ${p.last_name}` : ""; }).filter(Boolean).join(", ")}` : ""}</small></span><details><summary>Bearbeiten</summary><form className="event-edit-form" onSubmit={event => void updateEvent(event, e.id)}><label>Titel<input name="title" required defaultValue={e.title} /></label><label>Beginn<input name="starts_at" type="datetime-local" required defaultValue={localDateTime(e.starts_at)} /></label><label>Ort<input name="location" defaultValue={e.location} /></label><div className="event-participants"><label htmlFor={`appointment-participants-${e.id}`}>Teilnehmende</label><PersonPicker key={`${e.id}-${e.participant_ids.join(",")}`} id={`appointment-participants-${e.id}`} people={people} initialIds={e.participant_ids} /></div><button>Änderungen speichern</button></form></details><button type="button" className="quiet danger-text" onClick={() => void deleteRecord(`/api/events/${e.id}`, "Termin")}>Löschen</button></div>)}</section>
      {currentView === "events" && <EventArchive events={events} people={people} memories={memories} token={token} api={api} request={request} onRefresh={refresh} onDelete={async id => { await deleteRecord(`/api/events/${id}`, "Ereignis"); }} />}
      {currentView === "admin" && currentUser?.role === "admin" && <AdminPanel request={request} currentUserId={currentUser.id} />}
      {currentView === "admin" && currentUser?.role !== "admin" && <section className="card panel"><h2>Kein Zugriff</h2><p>Für die Administration brauchst du ein Administratorkonto.</p></section>}
      <footer>Deine Daten. Dein Server. Dein Gedächtnis.</footer>
    </section></main>;
}
