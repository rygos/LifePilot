"use client";

import { useState, type FormEvent } from "react";

export type Profile = {
  readonly username: string;
  readonly full_name: string;
  readonly nickname?: string | null;
  readonly birthday?: string | null;
  readonly email?: string | null;
  readonly phone?: string | null;
  readonly address: string;
  readonly timezone_name: string;
  readonly quiet_hours_start?: string | null;
  readonly quiet_hours_end?: string | null;
};

type Props = {
  readonly profile: Profile;
  readonly request: <T>(path: string, init?: RequestInit) => Promise<T>;
  readonly onClose: () => void;
  readonly onMessage: (message: string) => void;
  readonly onProfileSaved: (profile: Profile) => void;
};

export function AccountSettingsPanel({ profile, request, onClose, onMessage, onProfileSaved }: Props) {
  const [passwordError, setPasswordError] = useState("");

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const saved = await request<Profile>("/api/profile", { method: "PATCH", body: JSON.stringify({ full_name: form.get("full_name"), nickname: form.get("nickname") || null, birthday: form.get("birthday") || null, email: form.get("email") || null, phone: form.get("phone") || null, address: form.get("address") || "", timezone_name: form.get("timezone_name"), quiet_hours_start: form.get("quiet_hours_start") || null, quiet_hours_end: form.get("quiet_hours_end") || null }) });
      onProfileSaved(saved);
      onMessage("Dein Profil wurde gespeichert");
    } catch (error) {
      onMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const currentPassword = String(form.get("current_password") ?? "");
    const newPassword = String(form.get("new_password") ?? "");
    if (newPassword !== String(form.get("confirm_password") ?? "")) {
      setPasswordError("Die neuen Passwörter stimmen nicht überein.");
      return;
    }

    setPasswordError("");
    try {
      await request("/api/auth/password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) });
      formElement.reset();
      onMessage("Dein Passwort wurde geändert.");
    } catch (error) {
      setPasswordError(error instanceof Error ? error.message : String(error));
    }
  }

  return <>
    <section className="card panel profile-panel"><div className="panel-head"><div><span className="eyebrow">PERSÖNLICHER BEREICH</span><h2>Mein Profil</h2></div><button type="button" className="quiet" onClick={onClose}>Schließen</button></div><form className="person-form" onSubmit={saveProfile}><label>Vollständiger Name<input name="full_name" defaultValue={profile.full_name} /></label><label>Spitzname<input name="nickname" defaultValue={profile.nickname ?? ""} /></label><label>Geburtstag<input name="birthday" type="date" defaultValue={profile.birthday ?? ""} /></label><label>E-Mail<input name="email" type="email" defaultValue={profile.email ?? ""} /></label><label>Telefon<input name="phone" type="tel" defaultValue={profile.phone ?? ""} /></label><label>Adresse<textarea name="address" defaultValue={profile.address} /></label><label>Zeitzone<input name="timezone_name" defaultValue={profile.timezone_name} required /></label><label>Ruhezeit von<input name="quiet_hours_start" type="time" defaultValue={profile.quiet_hours_start ?? ""} /></label><label>Ruhezeit bis<input name="quiet_hours_end" type="time" defaultValue={profile.quiet_hours_end ?? ""} /></label><p className="form-hint">Während der Ruhezeit werden In-App-Benachrichtigungen ausgeblendet. Beide Zeiten leer lassen, um die Ruhezeit auszuschalten.</p><button type="submit">Profil speichern</button></form></section>
    <section className="card panel profile-panel"><div className="panel-head"><div><span className="eyebrow">KONTO</span><h2>Passwort ändern</h2></div></div><form className="person-form" onSubmit={changePassword}><label>Aktuelles Passwort<input name="current_password" type="password" autoComplete="current-password" required /></label><label>Neues Passwort<input name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label><label>Neues Passwort wiederholen<input name="confirm_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label><p className="form-hint">Das neue Passwort muss mindestens 12 Zeichen lang sein.</p>{passwordError && <p className="error" role="alert">{passwordError}</p>}<button type="submit">Passwort speichern</button></form></section>
  </>;
}
