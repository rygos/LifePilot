"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

export type AttachmentResourceType = "person" | "memory" | "conversation" | "event" | "project";
type Attachment = { id: string; resource_type: AttachmentResourceType; resource_id: string; file_name: string; content_type: string; size_bytes: number; created_at: string };
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;

const labels: Record<AttachmentResourceType, string> = { person: "Profil", memory: "Erinnerung", conversation: "Gespräch", event: "Ereignis", project: "Projekt" };

function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Byte`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB`;
}

export function ResourceAttachments({ resourceType, resourceId, token, api, request }: { resourceType: AttachmentResourceType; resourceId: string; token: string; api: string; request: Request }) {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    setAttachments(await request<Attachment[]>(`/api/attachments?resource_type=${resourceType}&resource_id=${encodeURIComponent(resourceId)}`));
  }, [request, resourceId, resourceType]);

  useEffect(() => { void reload().catch(caught => setError(String(caught))); }, [reload]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const form = event.currentTarget;
      const response = await fetch(`${api}/api/attachments`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body: new FormData(form) });
      if (!response.ok) {
        const body: unknown = await response.json();
        const message = typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string" ? body.detail : `Upload fehlgeschlagen (${response.status})`;
        throw new Error(message);
      }
      form.reset();
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function download(attachment: Attachment) {
    setError("");
    try {
      const response = await fetch(`${api}/api/attachments/${attachment.id}/download`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error(`Download fehlgeschlagen (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = attachment.file_name;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function remove(attachment: Attachment) {
    setError("");
    try {
      await request(`/api/attachments/${attachment.id}`, { method: "DELETE" });
      setAttachments(items => items.filter(item => item.id !== attachment.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  return <section className="resource-attachments" aria-label={`Dateianhänge zum ${labels[resourceType]}`}>
    <div className="resource-attachments-heading"><h3>Dateien</h3><span className="count">{attachments.length}</span></div>
    <form className="resource-attachment-form" onSubmit={event => void upload(event)}>
      <input type="hidden" name="resource_type" value={resourceType} />
      <input type="hidden" name="resource_id" value={resourceId} />
      <label>Datei hinzufügen (max. 20 MB)<input type="file" name="file" accept=".pdf,.txt,.md,.csv,.jpg,.jpeg,.png,.webp,.docx,.xlsx,.pptx,.odt,.ods,.odp" required /></label>
      <button type="submit" disabled={busy}>{busy ? "Wird hochgeladen …" : "Hochladen"}</button>
    </form>
    {error && <p className="resource-attachment-error" role="alert">{error}</p>}
    {attachments.length ? <ul className="resource-attachment-list">{attachments.map(attachment => <li key={attachment.id}>
      <div><strong>{attachment.file_name}</strong><small>{fileSize(attachment.size_bytes)} · {new Intl.DateTimeFormat("de-DE", { dateStyle: "medium" }).format(new Date(attachment.created_at))}</small></div>
      <button type="button" className="quiet" onClick={() => void download(attachment)}>Herunterladen</button>
      <button type="button" className="quiet danger-text" onClick={() => void remove(attachment)} aria-label={`${attachment.file_name} löschen`}>Löschen</button>
    </li>)}</ul> : <p className="empty">Noch keine Dateien angehängt.</p>}
  </section>;
}
