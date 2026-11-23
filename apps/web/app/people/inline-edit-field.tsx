"use client";

import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { BirthdayFields } from "./birthday-fields";

type SelectOption = { readonly value: string; readonly label: string };
type Props = {
  label: string;
  value: string;
  display?: ReactNode;
  type?: "text" | "email" | "tel" | "url" | "textarea" | "select";
  options?: readonly SelectOption[];
  placeholder?: string;
  onSave: (value: string) => Promise<boolean>;
};

type BirthdayPerson = {
  readonly birthday_precision: "exact" | "month_day" | "approximate" | "unknown";
  readonly birthday?: string | null;
  readonly birthday_month?: number | null;
  readonly birthday_day?: number | null;
  readonly birthday_approximate_age?: number | null;
};

type BirthdayProps = {
  readonly person: BirthdayPerson;
  readonly display: string;
  readonly onSave: (form: FormData) => Promise<boolean>;
};

function PencilIcon() {
  return <svg aria-hidden="true" viewBox="0 0 16 16" width="16" height="16" fill="none"><path d="m10.8 2.3 2.9 2.9M2 14l3.1-.7 8.3-8.3a1.4 1.4 0 0 0-2-2L3.1 11.3 2 14Z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

export function InlineEditField({ label, value, display, type = "text", options = [], placeholder, onSave }: Props) {
  const id = useId();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [editing, value]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    const saved = await onSave(draft);
    setSaving(false);
    if (saved) setEditing(false);
  }

  return <div className="inline-edit-field">
    <dt>{label}</dt>
    <dd>
      {editing ? <form className="inline-edit-form" onSubmit={event => void submit(event)}>
        {type === "textarea" ? <textarea id={id} aria-label={label} value={draft} placeholder={placeholder} autoFocus onChange={event => setDraft(event.target.value)} /> : type === "select" ? <select id={id} aria-label={label} value={draft} autoFocus onChange={event => setDraft(event.target.value)}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input id={id} aria-label={label} type={type} value={draft} placeholder={placeholder} autoFocus onChange={event => setDraft(event.target.value)} />}
        <span className="inline-edit-actions"><button type="submit" disabled={saving}>{saving ? "Speichern …" : "Speichern"}</button><button type="button" className="quiet" disabled={saving} onClick={() => setEditing(false)}>Abbrechen</button></span>
      </form> : <span className="inline-edit-value">{display ?? value ?? "Nicht angegeben"}<button type="button" className="inline-edit-trigger" aria-label={`${label} bearbeiten`} title={`${label} bearbeiten`} onClick={() => { setDraft(value); setEditing(true); }}><PencilIcon /></button></span>}
    </dd>
  </div>;
}

export function InlineBirthdayField({ person, display, onSave }: BirthdayProps) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    const saved = await onSave(new FormData(event.currentTarget));
    setSaving(false);
    if (saved) setEditing(false);
  }

  return <div className="inline-edit-field">
    <dt>Geburtstag</dt>
    <dd>
      {editing ? <form className="inline-edit-form inline-birthday-form" onSubmit={event => void submit(event)}>
        <BirthdayFields precision={person.birthday_precision} birthday={person.birthday} month={person.birthday_month} day={person.birthday_day} approximateAge={person.birthday_approximate_age} />
        <span className="inline-edit-actions"><button type="submit" disabled={saving}>{saving ? "Speichern …" : "Speichern"}</button><button type="button" className="quiet" disabled={saving} onClick={() => setEditing(false)}>Abbrechen</button></span>
      </form> : <span className="inline-edit-value">{display}<button type="button" className="inline-edit-trigger" aria-label="Geburtstag bearbeiten" title="Geburtstag bearbeiten" onClick={() => setEditing(true)}><PencilIcon /></button></span>}
    </dd>
  </div>;
}
