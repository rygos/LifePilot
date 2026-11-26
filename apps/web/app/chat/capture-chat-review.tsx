"use client";

import type { Capture, CaptureSuggestion, Person, Project } from "../page";

type Props = {
  capture: Capture;
  people: Person[];
  projects: Project[];
  selectedIndices: number[];
  busy: boolean;
  onToggle: (index: number, checked: boolean) => void;
  onApply: () => void;
};

function suggestionLabel(suggestion: CaptureSuggestion): string {
  if (suggestion.kind === "commitment") return (suggestion.commitment_direction === "incoming" ? "Ausstehende Rückmeldung: " : "Mein Versprechen: ") + suggestion.title;
  if (suggestion.kind === "relationship") {
    return `${suggestion.person_name} · ${suggestion.relationship_type} · ${suggestion.related_person_name}`;
  }
  return suggestion.title;
}

function genderName(gender: "female" | "male" | "diverse"): string {
  return { female: "weiblich", male: "männlich", diverse: "divers" }[gender];
}

export function CaptureChatReview({ capture, people, projects, selectedIndices, busy, onToggle, onApply }: Props) {
  return <section className="capture-chat-result">
    <strong>Vorschläge aus deiner Eingabe</strong>
    {capture.status === "pending" && <p>Die Analyse läuft. Die Vorschläge erscheinen gleich hier.</p>}
    {capture.status !== "pending" && capture.status !== "ready" && <p>{capture.processing_error || (capture.status === "reviewed" ? "Alle Vorschläge wurden umgesetzt." : "Der Originaltext bleibt gespeichert.")}</p>}
    {capture.status === "ready" && capture.suggestions.length > 0 && <>
      <p className="chat-review-hint">Hake ab, was ich übernehmen soll. Offene Punkte bleiben für deine nächste Nachricht im Gespräch.</p>
      <ul className="chat-suggestion-list">{capture.suggestions.map((suggestion, index) => <li className="chat-suggestion" key={`${capture.id}-${index}`}>
        <label className="suggestion"><input type="checkbox" checked={selectedIndices.includes(index)} onChange={event => onToggle(index, event.target.checked)} /><span><strong>{suggestionLabel(suggestion)}</strong><small>{suggestion.content}</small>{suggestion.kind === "commitment" && <small>Quelle: „{suggestion.commitment_evidence}“{suggestion.due_at ? " · Fällig: " + new Date(suggestion.due_at).toLocaleString("de-DE") : ""}</small>}{suggestion.kind === "conversation" && suggestion.participant_names.length > 0 && <small>Teilnehmende: {suggestion.participant_names.join(", ")}</small>}{suggestion.kind === "conversation" && (suggestion.location || suggestion.location_address) && <small>Ort: {[suggestion.location, suggestion.location_address].filter(Boolean).join(" · ")}</small>}{suggestion.person_gender && <small>Geschlecht für {suggestion.person_name}: {genderName(suggestion.person_gender)}{suggestion.person_gender_basis === "name_inference" ? " (aus dem Namen vermutet)" : ""}</small>}{suggestion.related_person_gender && <small>Geschlecht für {suggestion.related_person_name}: {genderName(suggestion.related_person_gender)}{suggestion.related_person_gender_basis === "name_inference" ? " (aus dem Namen vermutet)" : ""}</small>}</span></label>
        {suggestion.person_name && (suggestion.person_candidates.length !== 1 || !suggestion.person_id) && <label>Person zuordnen<select name={`capture-person-${capture.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.person_name}</option>{people.map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label>}
        {suggestion.person_name && !suggestion.person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-person-${capture.id}-${index}`} /> Als neue Person anlegen</label>}
        {suggestion.kind === "relationship" && suggestion.related_person_name && (suggestion.related_person_candidates.length !== 1 || !suggestion.related_person_id) && <label>Zweite Person zuordnen<select name={`capture-related-person-${capture.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.related_person_name}</option>{people.map(person => <option key={person.id} value={person.id}>{person.first_name} {person.last_name}</option>)}</select></label>}
        {suggestion.kind === "relationship" && suggestion.related_person_name && !suggestion.related_person_id && <label className="suggestion-confirm"><input type="checkbox" name={`capture-create-related-${capture.id}-${index}`} /> Zweite Person neu anlegen</label>}
        {suggestion.project_name && (suggestion.project_candidates.length !== 1 || !suggestion.project_id) && <label>Projekt zuordnen<select name={`capture-project-${capture.id}-${index}`} defaultValue=""><option value="">Bitte zuordnen: {suggestion.project_name}</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}
        {(suggestion.confirmation_required || suggestion.kind === "commitment") && <label className="suggestion-confirm"><input type="checkbox" name={`capture-confirm-${capture.id}-${index}`} /> {suggestion.person_gender_basis === "name_inference" || suggestion.related_person_gender_basis === "name_inference" ? "Geschlechtsvermutung aus dem Namen ausdrücklich bestätigen" : suggestion.kind === "commitment" ? "Verpflichtung ausdrücklich bestätigen" : "Unsichere Zuordnung ausdrücklich bestätigen"}</label>}
      </li>)}</ul>
      <button type="button" disabled={busy || selectedIndices.length === 0} onClick={onApply}>{busy ? "Wird übernommen …" : `Auswahl übernehmen (${selectedIndices.length})`}</button>
    </>}
    {capture.status === "ready" && capture.suggestions.length === 0 && <p>{capture.processing_error || "Keine neuen Vorschläge offen."}</p>}
  </section>;
}
