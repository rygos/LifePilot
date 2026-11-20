"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiRequestError } from "../use-life-pilot-session";

type AdminUser = {
  id: string;
  username: string;
  full_name: string;
  role: "user" | "admin";
  created_at: string;
  deleted_at: string | null;
};

type UpdateStatus = {
  configured: boolean;
  source: string;
  available: boolean;
  update_available: boolean;
  current_commit: string | null;
  latest_commit: string | null;
  ahead_by: number;
  pending_update: boolean;
  pending_commit: string | null;
  commits: { sha: string; message: string; date: string | null }[];
};
type UpdateResponse = { status: string; message: string; target_commit: string };
type AdminRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

type AdminPanelProps = {
  request: AdminRequest;
  currentUserId: string;
};

export function AdminPanel({ request, currentUserId }: AdminPanelProps) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [updateConfigured, setUpdateConfigured] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [updateLoading, setUpdateLoading] = useState(true);
  const [workingUserId, setWorkingUserId] = useState("");
  const [updating, setUpdating] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);
  const [deleteMode, setDeleteMode] = useState<"soft" | "permanent">("soft");

  const load = useCallback(() => {
    setLoading(true);
    setUpdateLoading(true);
    setError("");
    void request<AdminUser[]>("/api/admin/users").then(setUsers).catch(caught => {
      setError(caught instanceof Error ? caught.message : String(caught));
    }).finally(() => setLoading(false));
    void request<UpdateStatus>("/api/admin/app-update").then(update => {
      setUpdateConfigured(update.configured);
      setUpdateStatus(update);
    }).catch(caught => {
      setError(caught instanceof Error ? caught.message : String(caught));
    }).finally(() => setUpdateLoading(false));
  }, [request]);

  useEffect(() => { void load(); }, [load]);

  async function changeRole(user: AdminUser) {
    const role = user.role === "admin" ? "user" : "admin";
    if (role === "user" && !window.confirm(`Administratorrechte für ${user.username} entziehen?`)) return;
    setWorkingUserId(user.id);
    setError("");
    setMessage("");
    try {
      const updated = await request<AdminUser>(`/api/admin/users/${user.id}/role`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      setUsers(rows => rows.map(row => row.id === updated.id ? updated : row));
      setMessage(`${updated.username}: ${role === "admin" ? "Administratorrechte vergeben." : "Administratorrechte entzogen."}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorkingUserId("");
    }
  }

  async function deleteUser(user: AdminUser) {
    const normalized = deleteMode;
    setWorkingUserId(user.id);
    setError("");
    setMessage("");
    try {
      if (normalized === "soft") {
        const updated = await request<AdminUser>(`/api/admin/users/${user.id}`, { method: "DELETE" });
        setUsers(rows => rows.map(row => row.id === updated.id ? updated : row));
        setMessage(`${updated.username} wurde deaktiviert und kann wiederhergestellt werden.`);
      } else {
        await request<void>(`/api/admin/users/${user.id}/permanent`, { method: "DELETE" });
        setUsers(rows => rows.filter(row => row.id !== user.id));
        setMessage(`${user.username} und alle zugehörigen Daten wurden endgültig gelöscht.`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorkingUserId("");
      setDeleteTarget(null);
    }
  }

  async function restoreUser(user: AdminUser) {
    setWorkingUserId(user.id);
    setError("");
    setMessage("");
    try {
      const updated = await request<AdminUser>(`/api/admin/users/${user.id}/restore`, { method: "POST" });
      setUsers(rows => rows.map(row => row.id === updated.id ? updated : row));
      setMessage(`${updated.username} wurde wiederhergestellt.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setWorkingUserId("");
    }
  }

  async function updateApp() {
    if (!window.confirm("LifePilot aktualisiert sich aus dem Git-Hauptbranch. Die App startet danach neu und führt ausstehende Datenbankmigrationen aus. Jetzt aktualisieren?")) return;
    setUpdating(true);
    setError("");
    setMessage("");
    let targetCommit = updateStatus?.latest_commit ?? "";
    try {
      const result = await request<UpdateResponse>("/api/admin/app-update", { method: "POST" });
      targetCommit = result.target_commit;
      setMessage(`${result.message} Zielversion: ${targetCommit}.`);
    } catch (caught) {
      if (caught instanceof ApiRequestError && (caught.hasServerDetail || [401, 403].includes(caught.status))) {
        setError(caught instanceof Error ? caught.message : String(caught));
        setUpdating(false);
        return;
      }
      if (caught instanceof TypeError || caught instanceof SyntaxError || caught instanceof ApiRequestError) {
        setMessage("Die Antwort auf die Updateanfrage ist unklar. LifePilot prüft, ob der Neustart begonnen hat …");
      } else {
        setError(caught instanceof Error ? caught.message : String(caught));
        setUpdating(false);
        return;
      }
    }
    const deadline = Date.now() + 5 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise(resolve => window.setTimeout(resolve, 5000));
      try {
        const progress = await request<UpdateStatus>("/api/admin/app-update?progress_only=true");
        if (!targetCommit && progress.pending_commit) targetCommit = progress.pending_commit;
        setUpdateStatus(previous => previous ? { ...previous, current_commit: progress.current_commit, pending_update: progress.pending_update, pending_commit: progress.pending_commit } : progress);
        setUpdateConfigured(progress.configured);
        if (!progress.pending_update && progress.current_commit === targetCommit) {
          setUpdateStatus(previous => ({
            ...(previous ?? progress),
            current_commit: targetCommit,
            latest_commit: targetCommit,
            update_available: false,
            ahead_by: 0,
            commits: [],
            pending_update: false,
            pending_commit: null,
          }));
          setMessage(`LifePilot wurde erfolgreich auf ${targetCommit} aktualisiert.`);
          setUpdating(false);
          return;
        }
        if (!progress.pending_update && progress.current_commit !== targetCommit) {
          setError("Portainer hat den Updateauftrag angenommen, aber die Zielversion wurde nicht gestartet. Prüfe die Portainer-Stackprotokolle und versuche es erneut.");
          setUpdating(false);
          return;
        }
      } catch (caught) {
        if (!(caught instanceof TypeError || caught instanceof SyntaxError || caught instanceof ApiRequestError)) {
          setError(caught instanceof Error ? caught.message : String(caught));
          setUpdating(false);
          return;
        }
        if (caught instanceof ApiRequestError && [401, 403].includes(caught.status)) {
          setError(caught.message);
          setUpdating(false);
          return;
        }
        setMessage("LifePilot startet gerade neu. Die Verbindung wird weiter geprüft …");
      }
    }
    setError("Das Update wurde von Portainer angenommen, aber LifePilot hat den erfolgreichen Neustart nicht innerhalb von fünf Minuten bestätigt. Prüfe die Portainer-Stackprotokolle.");
    setUpdating(false);
  }

  return <div className="admin-page">
    <section className="card panel admin-update-panel">
      <div className="panel-head"><div><span className="eyebrow">WARTUNG</span><h2>LifePilot aktualisieren</h2></div><span className={`role-badge ${updateConfigured ? "role-admin" : "role-user"}`}>{updateConfigured ? "Verbunden" : "Nicht eingerichtet"}</span></div>
      <p>Portainer lädt den aktuellen Stand des Git-Hauptbranches, baut die Dienste neu und startet LifePilot. Datenbankmigrationen laufen kontrolliert vor dem API-Start.</p>
      {updateLoading ? <p className="form-hint">Git-Version wird geprüft …</p> : updateStatus?.available ? <div className="update-version-status" role="status"><strong>{updateStatus.update_available ? `${updateStatus.ahead_by} ${updateStatus.ahead_by === 1 ? "Änderung" : "Änderungen"} verfügbar` : "LifePilot ist aktuell"}</strong><span>Installiert: {updateStatus.current_commit ?? "unbekannt"} · Ziel: {updateStatus.latest_commit ?? "unbekannt"}</span>{updateStatus.update_available && updateStatus.commits.length > 0 && <ul className="update-commit-list">{updateStatus.commits.map(commit => <li key={commit.sha}><code>{commit.sha}</code><span>{commit.message}</span></li>)}</ul>}{updateStatus.ahead_by > updateStatus.commits.length && <small>Es werden die letzten {updateStatus.commits.length} von {updateStatus.ahead_by} Änderungen angezeigt.</small>}</div> : <p className="form-hint">{updateStatus?.current_commit ? "GitHub ist momentan nicht erreichbar; der Versionsvergleich ist nicht verfügbar." : "Die laufende Versionsnummer konnte nicht ermittelt werden."}</p>}
      {!updateConfigured && <p className="form-hint">Der Git-Webhook ist nicht konfiguriert. Der Updateknopf wird nach der Portainer-Einrichtung verfügbar.</p>}
      {updateStatus?.pending_update && !updating && <p className="admin-update-progress" role="status">Ein Update auf {updateStatus.pending_commit} wurde angefordert. LifePilot wartet auf den Neustart.</p>}
      {updating && <p className="admin-update-progress" role="status">Updateanfrage läuft. Der Abschluss wird automatisch geprüft.</p>}
      <button type="button" onClick={() => void updateApp()} disabled={!updateConfigured || updating}>{updating ? "Update angefordert" : "Jetzt aktualisieren"}</button>
    </section>

    <section className="card panel admin-users-panel">
      <div className="panel-head"><div><span className="eyebrow">ZUGRIFF</span><h2>Benutzer und Rollen</h2></div><span className="count">{users.length}</span></div>
      <p className="muted">Administratoren können Nutzer und Systemfunktionen verwalten. Mindestens ein Administratorkonto bleibt immer aktiv.</p>
      {loading ? <p className="empty">Benutzer werden geladen …</p> : users.length === 0 ? <p className="empty">Keine Benutzer vorhanden.</p> : <div className="admin-user-list">{users.map(user => {
        const isSelf = user.id === currentUserId;
        return <article className="admin-user-row" key={user.id}>
          <div className="admin-user-identity"><strong>{user.full_name || user.username}</strong><small>{user.username}{isSelf ? " · dein Konto" : ""}</small></div>
          <span className={`role-badge ${user.deleted_at ? "role-user" : user.role === "admin" ? "role-admin" : "role-user"}`}>{user.deleted_at ? "Gelöscht" : user.role === "admin" ? "Administrator" : "Nutzer"}</span>
          {user.deleted_at ? <button type="button" disabled={workingUserId === user.id} onClick={() => void restoreUser(user)}>{workingUserId === user.id ? "Speichert …" : "Wiederherstellen"}</button> : <>
            <button type="button" className={user.role === "admin" ? "quiet" : ""} disabled={isSelf || workingUserId === user.id} onClick={() => void changeRole(user)}>{workingUserId === user.id ? "Speichert …" : user.role === "admin" ? "Adminrechte entziehen" : "Zum Admin machen"}</button>
            <button type="button" className="quiet" disabled={isSelf || workingUserId === user.id} onClick={() => { setDeleteTarget(user); setDeleteMode("soft"); }}>{workingUserId === user.id ? "Speichert …" : "Löschen …"}</button>
          </>}
        </article>;
      })}</div>}
    </section>
    {message && <p className="admin-message" role="status">{message}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {deleteTarget && <div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) setDeleteTarget(null); }}>
      <section className="card delete-user-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-user-title">
        <div className="panel-head"><div><span className="eyebrow">BENUTZER ENTFERNEN</span><h2 id="delete-user-title">{deleteTarget.full_name || deleteTarget.username} löschen?</h2></div><button type="button" className="quiet" aria-label="Dialog schließen" onClick={() => setDeleteTarget(null)}>×</button></div>
        <label className="delete-choice"><input type="radio" name="delete-mode" checked={deleteMode === "soft"} onChange={() => setDeleteMode("soft")} /><span><strong>Wiederherstellbar deaktivieren</strong><small>Der Zugang wird gesperrt. Das Konto bleibt in der Benutzerverwaltung und kann später wiederhergestellt werden.</small></span></label>
        <label className="delete-choice"><input type="radio" name="delete-mode" checked={deleteMode === "permanent"} onChange={() => setDeleteMode("permanent")} /><span><strong>Dauerhaft löschen</strong><small>Das Konto und alle diesem Benutzer zugeordneten Daten werden unwiderruflich entfernt.</small></span></label>
        {deleteMode === "permanent" && <p className="error" role="alert">Diese Aktion kann nicht rückgängig gemacht werden.</p>}
        <div className="dialog-actions"><button type="button" className="quiet" onClick={() => setDeleteTarget(null)}>Abbrechen</button><button type="button" className={deleteMode === "permanent" ? "danger" : ""} disabled={workingUserId === deleteTarget.id} onClick={() => void deleteUser(deleteTarget)}>{workingUserId === deleteTarget.id ? "Wird gelöscht …" : deleteMode === "permanent" ? "Dauerhaft löschen" : "Deaktivieren"}</button></div>
      </section>
    </div>}
  </div>;
}
