"use client";

import { useState } from "react";
import type { Person } from "../page";

export function PersonPicker({ id, people, initialIds = [], name = "participant_ids" }: { id: string; people: Person[]; initialIds?: readonly string[]; name?: string }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([...initialIds]);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [open, setOpen] = useState(false);
  const selected = selectedIds.map(personId => people.find(person => person.id === personId)).filter((person): person is Person => Boolean(person));
  const normalizedQuery = query.trim().toLocaleLowerCase("de-DE");
  const suggestions = people
    .filter(person => !selectedIds.includes(person.id))
    .filter(person => !normalizedQuery || `${person.first_name} ${person.last_name} ${person.nickname ?? ""}`.toLocaleLowerCase("de-DE").includes(normalizedQuery))
    .slice(0, 8);

  function addPerson(person: Person) {
    setSelectedIds(current => current.includes(person.id) ? current : [...current, person.id]);
    setQuery("");
    setActiveIndex(-1);
    setOpen(false);
  }

  return <div className="person-picker" onBlur={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <div className="person-picker-control">
      <div className="person-picker-chips" aria-live="polite">
        {selected.map(person => <span className="person-picker-chip" key={person.id}>
          <span>{person.first_name} {person.last_name}</span>
          <button type="button" aria-label={`${person.first_name} ${person.last_name} entfernen`} onClick={() => setSelectedIds(current => current.filter(personId => personId !== person.id))}>×</button>
          <input type="hidden" name={name} value={person.id} />
        </span>)}
      </div>
      <input id={id} type="text" role="combobox" aria-autocomplete="list" aria-expanded={open && suggestions.length > 0} aria-controls={`${id}-suggestions`} aria-activedescendant={open && activeIndex >= 0 && suggestions[activeIndex] ? `${id}-option-${suggestions[activeIndex].id}` : undefined} autoComplete="off" value={query} placeholder={selected.length ? "Weitere Person suchen …" : "Person suchen …"} onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setActiveIndex(-1); setOpen(true); }} onKeyDown={event => {
        if (event.key === "ArrowDown" && suggestions.length) { event.preventDefault(); setOpen(true); setActiveIndex(current => current < 0 ? 0 : (current + 1) % suggestions.length); }
        if (event.key === "ArrowUp" && suggestions.length) { event.preventDefault(); setOpen(true); setActiveIndex(current => current < 0 ? suggestions.length - 1 : (current - 1 + suggestions.length) % suggestions.length); }
        if (event.key === "Enter" && open && suggestions.length) { event.preventDefault(); addPerson(suggestions[activeIndex] ?? suggestions[0]); }
        if (event.key === "Escape") setOpen(false);
      }} />
    </div>
    {open && suggestions.length > 0 && <ul className="person-picker-suggestions" id={`${id}-suggestions`} role="listbox" aria-label="Personen">
      {suggestions.map((person, index) => <li key={person.id}><button id={`${id}-option-${person.id}`} type="button" role="option" aria-selected={index === activeIndex} onMouseDown={event => event.preventDefault()} onMouseEnter={() => setActiveIndex(index)} onClick={() => addPerson(person)}>{person.first_name} {person.last_name}{person.nickname && <small>{person.nickname}</small>}</button></li>)}
    </ul>}
    {open && normalizedQuery && suggestions.length === 0 && <p className="person-picker-empty">Keine passende Person gefunden.</p>}
  </div>;
}
