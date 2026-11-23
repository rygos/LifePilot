"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import type { Event, Person } from "../page";

type PetLink = { person_id: string; relationship_type: "owner" | "caretaker" | "lives_with" };
type Pet = { id: string; name: string; species: string; breed: string; sex: "female" | "male" | "unknown"; birthday: string | null; is_neutered: boolean; notes: string; person_links: PetLink[]; event_ids: string[] };
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;

function PetPersonPicker({ id, people, initialLinks = [] }: { id: string; people: Person[]; initialLinks?: PetLink[] }) {
  const [links, setLinks] = useState<PetLink[]>(initialLinks);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const matches = people.filter(person => !links.some(link => link.person_id === person.id) && `${person.first_name} ${person.last_name} ${person.nickname ?? ""}`.toLocaleLowerCase("de-DE").includes(query.trim().toLocaleLowerCase("de-DE"))).slice(0, 7);
  function add(person: Person) {
    setLinks(current => [...current, { person_id: person.id, relationship_type: "owner" }]);
    setQuery("");
    setOpen(false);
  }
  return <div className="pet-person-picker" onBlur={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <div className="pet-person-links">{links.map((link, index) => {
      const person = people.find(item => item.id === link.person_id);
      if (!person) return null;
      return <div className="pet-person-link" key={person.id}>
        <span>{person.first_name} {person.last_name}</span>
        <select aria-label={`Beziehung zu ${person.first_name}`} value={link.relationship_type} onChange={event => setLinks(current => current.map((currentLink, currentIndex) => currentIndex === index ? { ...currentLink, relationship_type: event.target.value as PetLink["relationship_type"] } : currentLink))}><option value="owner">Besitzer:in</option><option value="caretaker">Betreut</option><option value="lives_with">Lebt zusammen</option></select>
        <input type="hidden" name="person_links" value={JSON.stringify(link)} />
        <button type="button" className="quiet" aria-label={`${person.first_name} entfernen`} onClick={() => setLinks(current => current.filter(item => item.person_id !== person.id))}>×</button>
      </div>;
    })}</div>
    <input id={id} role="combobox" aria-label="Person verknüpfen" aria-expanded={open && matches.length > 0} autoComplete="off" value={query} placeholder="Person suchen …" onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setOpen(true); }} />
    {open && matches.length > 0 && <ul className="pet-person-suggestions" role="listbox">{matches.map(person => <li key={person.id}><button type="button" role="option" onMouseDown={event => event.preventDefault()} onClick={() => add(person)}>{person.first_name} {person.last_name}</button></li>)}</ul>}
  </div>;
}

export function PetsPanel({ people, events, request, onMessage }: { people: Person[]; events: Event[]; request: Request; onMessage: (message: string) => void }) {
  const [pets, setPets] = useState<Pet[]>([]);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const reload = useCallback(async () => {
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    setPets(await request<Pet[]>(`/api/pets?${params.toString()}`));
  }, [query, request]);
  useEffect(() => { void reload().catch(error => onMessage(String(error))); }, [onMessage, reload]);

  async function save(event: FormEvent<HTMLFormElement>, petId?: string) {
    event.preventDefault();
    setBusy(true);
    const form = new FormData(event.currentTarget);
    let personLinks: PetLink[];
    try {
      personLinks = form.getAll("person_links").map(value => JSON.parse(String(value)) as PetLink);
    } catch {
      onMessage("Die verknüpften Personen konnten nicht gelesen werden.");
      setBusy(false);
      return;
    }
    const body = {
      name: form.get("name"),
      species: form.get("species"),
      breed: form.get("breed"),
      sex: form.get("sex"),
      birthday: form.get("birthday") || null,
      is_neutered: form.get("is_neutered") === "on",
      notes: form.get("notes"),
      person_links: personLinks,
      event_ids: form.getAll("event_ids"),
    };
    try {
      await request(petId ? `/api/pets/${petId}` : "/api/pets", { method: petId ? "PATCH" : "POST", body: JSON.stringify(body) });
      setEditing(null);
      setFormKey(value => value + 1);
      onMessage(petId ? "Tierprofil aktualisiert" : "Tierprofil gespeichert");
      await reload();
    } catch (error) {
      onMessage(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function remove(pet: Pet) {
    if (!window.confirm(`${pet.name} dauerhaft aus deinen Tierprofilen löschen?`)) return;
    try {
      await request(`/api/pets/${pet.id}`, { method: "DELETE" });
      setPets(current => current.filter(item => item.id !== pet.id));
      onMessage("Tierprofil gelöscht");
    } catch (error) {
      onMessage(String(error));
    }
  }

  function form(pet?: Pet) {
    return <form key={pet?.id ?? `new-${formKey}`} className="pet-form" onSubmit={event => void save(event, pet?.id)}>
      <label>Name<input name="name" required maxLength={160} defaultValue={pet?.name ?? ""} /></label>
      <label>Tierart<input name="species" required maxLength={80} defaultValue={pet?.species ?? ""} placeholder="Hund, Katze, Kaninchen …" /></label>
      <label>Rasse<input name="breed" maxLength={120} defaultValue={pet?.breed ?? ""} /></label>
      <label>Geschlecht<select name="sex" defaultValue={pet?.sex ?? "unknown"}><option value="unknown">Unbekannt</option><option value="female">Weiblich</option><option value="male">Männlich</option></select></label>
      <label>Geburtstag<input name="birthday" type="date" defaultValue={pet?.birthday ?? ""} /></label>
      <label className="pet-neutered"><input name="is_neutered" type="checkbox" defaultChecked={pet?.is_neutered ?? false} /> Kastriert</label>
      <label className="pet-notes">Notizen<textarea name="notes" maxLength={20000} rows={3} defaultValue={pet?.notes ?? ""} /></label>
      <div className="pet-links-field"><label htmlFor={`pet-person-${pet?.id ?? "new"}`}>Menschen verknüpfen</label><PetPersonPicker id={`pet-person-${pet?.id ?? "new"}`} people={people} initialLinks={pet?.person_links ?? []} /></div>
      <label className="pet-events-field">Ereignisse<select name="event_ids" multiple defaultValue={pet?.event_ids ?? []}>{events.map(item => <option key={item.id} value={item.id}>{item.title} · {new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.starts_at))}</option>)}</select></label>
      <p className="pet-select-hint">Für mehrere Ereignisse Strg- oder Cmd-Taste beim Anklicken halten.</p>
      <button type="submit" disabled={busy}>{busy ? "Wird gespeichert …" : pet ? "Änderungen speichern" : "Tierprofil anlegen"}</button>
      {pet && <button type="button" className="quiet" onClick={() => setEditing(null)}>Abbrechen</button>}
    </form>;
  }

  return <section className="card panel pets-panel">
    <div className="panel-head"><div><span className="eyebrow">DEINE TIERE</span><h2>Tierprofile</h2></div><span className="count">{pets.length}</span></div>
    <p className="muted">Speichere wichtige Daten und verknüpfe ein Tier mit seinen Menschen und gemeinsamen Ereignissen.</p>
    <details className="pet-create" open={pets.length === 0}><summary>Tier hinzufügen</summary>{form()}</details>
    <form className="pet-search" onSubmit={event => { event.preventDefault(); void reload(); }}><label>Tierprofile durchsuchen<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name, Tierart oder Rasse" /></label><button type="submit">Suchen</button></form>
    <div className="pet-grid">{pets.length === 0 ? <p className="empty">Noch keine Tiere gespeichert.</p> : pets.map(pet => {
      const linkedPeople = pet.person_links.map(link => ({ link, person: people.find(item => item.id === link.person_id) })).filter((item): item is { link: PetLink; person: Person } => Boolean(item.person));
      const linkedEvents = pet.event_ids.map(id => events.find(item => item.id === id)).filter((item): item is Event => Boolean(item));
      return <article className="pet-card" key={pet.id}>
        {editing === pet.id ? form(pet) : <>
          <div className="pet-card-heading"><div className="pet-avatar" aria-hidden="true">{pet.name.slice(0, 1).toLocaleUpperCase("de-DE")}</div><div><span className="eyebrow">{pet.species}</span><h3>{pet.name}</h3><p>{[pet.breed, pet.sex === "female" ? "Weiblich" : pet.sex === "male" ? "Männlich" : "Geschlecht unbekannt"].filter(Boolean).join(" · ")}</p></div></div>
          <dl className="pet-facts"><div><dt>Geburtstag</dt><dd>{pet.birthday ? new Intl.DateTimeFormat("de-DE", { dateStyle: "long" }).format(new Date(`${pet.birthday}T12:00:00`)) : "Nicht bekannt"}</dd></div><div><dt>Kastriert</dt><dd>{pet.is_neutered ? "Ja" : "Nein / unbekannt"}</dd></div></dl>
          {pet.notes && <p className="pet-notes-text">{pet.notes}</p>}
          {linkedPeople.length > 0 && <section className="pet-related"><h4>Menschen</h4><div>{linkedPeople.map(({ link, person }) => <a key={person.id} href={`/people/${person.id}`}>{person.first_name} {person.last_name}<small>{{ owner: "Besitzer:in", caretaker: "Betreut", lives_with: "Lebt zusammen" }[link.relationship_type]}</small></a>)}</div></section>}
          {linkedEvents.length > 0 && <section className="pet-related"><h4>Ereignisse</h4><div>{linkedEvents.map(item => <a href="/events" key={item.id}>{item.title}<small>{new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(item.starts_at))}</small></a>)}</div></section>}
          <div className="pet-card-actions"><button type="button" className="quiet" onClick={() => setEditing(pet.id)}>Bearbeiten</button><button type="button" className="quiet danger-text" onClick={() => void remove(pet)}>Löschen</button></div>
        </>}
      </article>;
    })}</div>
  </section>;
}
