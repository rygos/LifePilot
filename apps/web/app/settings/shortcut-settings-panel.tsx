"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Key = {scope:"capture:write"|"ha:status";id:string;label:string;created_at:string;expires_at:string;revoked_at:string|null;last_used_at:string|null;active:boolean};
type Created = Key & {token:string};
const base=(process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000").replace(/\/$/,"");
const statusEndpoint=base+"/api/home-assistant/status";
const endpoint=(process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000").replace(/\/$/,"")+"/api/shortcuts/capture";

export function ShortcutSettingsPanel({request}:{request:Request}) {
  const [scope,setScope]=useState("capture:write");
  const [keys,setKeys]=useState<Key[]>([]);
  const [created,setCreated]=useState<Created|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [loading,setLoading]=useState(true);
  const load=useCallback(async()=>{setKeys(await request<Key[]>("/api/shortcuts/keys"));},[request]);
  useEffect(()=>{let live=true;load().catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[load]);
  async function create(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;const fields=new FormData(form);
    setBusy(true);setError("");setNotice("");setCreated(null);
    try{
      const result=await request<Created>("/api/shortcuts/keys",{method:"POST",body:JSON.stringify({label:String(fields.get("label")??""),expires_in_days:Number(fields.get("days")),current_password:String(fields.get("password")??""),scope})});
      setCreated(result);form.reset();await load();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function revoke(key:Key){
    if(!window.confirm("Schlüssel „"+key.label+"“ widerrufen? Zugehörige Integrationen verlieren den Zugriff."))return;
    setBusy(true);setError("");setNotice("");
    try{await request("/api/shortcuts/keys/"+key.id,{method:"DELETE"});if(created?.id===key.id)setCreated(null);await load();}
    catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}
  }
  async function copy(value:string){
    try{await navigator.clipboard.writeText(value);setNotice("Kopiert. Behandle den Schlüssel wie ein Passwort.");}
    catch{setError("Kopieren nicht möglich. Bitte den Text manuell markieren.");}
  }
  return <section className="card panel profile-panel">
    <div className="panel-head"><div><span className="eyebrow">INTEGRATIONEN</span><h2>Kurzbefehle &amp; Home Assistant</h2></div></div>
    <p className="muted">Erfassungsschlüssel dürfen ausschließlich neue Texte im Eingang ablegen. Home-Assistant-Statusschlüssel dürfen nur aggregierte Erinnerungs-, Routinen- und Fokuszustände lesen. Keine Integration erhält Zugriff auf Personen, Texte oder sonstige Gedächtnisinhalte. Jeder Schlüssel ist einzeln widerrufbar und hat ein Ablaufdatum. Ein Passwortwechsel macht alle bisherigen Schlüssel ungültig.</p>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <form className="person-form" onSubmit={create}>
      <label>Berechtigung<select value={scope} onChange={e=>setScope(e.target.value)} disabled={busy||!!created}><option value="capture:write">Externe Erfassung (iOS / Home Assistant)</option><option value="ha:status">Home Assistant – Status lesen</option></select></label><label>Bezeichnung<input name="label" placeholder="z. B. Mein iPhone" required maxLength={120}/></label>
      <label>Gültigkeit<select name="days" defaultValue="90">{[7,30,90,180,365].map(d=><option key={d} value={d}>{d} Tage</option>)}</select></label>
      <label>Aktuelles Passwort<input type="password" name="password" autoComplete="current-password" required/></label>
      <button type="submit" disabled={busy||loading||!!created}>Integrationsschlüssel erstellen</button>
    </form>
    {created&&<div className="inbox-item"><h3>Neuer Schlüssel – einmalige Anzeige</h3><p>Speichere ihn sicher in deinem Kurzbefehl oder in Home Assistant. Verwende getrennte Schlüssel für Status und Erfassung und teile sie nicht.</p><input aria-label="Neuer Erfassungsschlüssel" readOnly value={created.token} onFocus={e=>e.currentTarget.select()} autoComplete="off"/><div className="commitment-actions"><button type="button" onClick={()=>void copy(created.token)}>Schlüssel kopieren</button><button type="button" className="quiet" onClick={()=>{setCreated(null);setNotice("");}}>Anzeige schließen</button></div></div>}
    <h3>Schlüssel verwalten</h3>
    {loading?<p className="muted">Schlüssel werden geladen …</p>:keys.length===0?<p className="muted">Noch keine Schlüssel erstellt.</p>:keys.map(key=><div className="list-item" key={key.id}><span>{key.label}<small>{key.scope==="ha:status"?"Status lesen":"Erfassung"} · {key.active?"Aktiv":key.revoked_at?"Widerrufen":"Inaktiv"} · Ablauf {new Date(key.expires_at).toLocaleDateString("de-DE")}{key.last_used_at?" · Zuletzt genutzt: "+new Date(key.last_used_at).toLocaleString("de-DE"):" · Noch nicht genutzt"}</small></span>{key.active&&<button type="button" className="quiet" disabled={busy} onClick={()=>void revoke(key)}>Widerrufen</button>}</div>)}
    <details><summary>Kurzbefehl auf dem iPhone einrichten</summary><p>Erstelle in der App „Kurzbefehle“ einen neuen Kurzbefehl, z. B. „LifePilot festhalten“. Verwende eine Texteingabe oder Diktat als Eingabe. Für das Teilen-Menü aktiviere die Anzeige im Teilen-Menü und verwende den übergebenen Text.</p><p>Füge die Aktion zum Abrufen von URL-Inhalten hinzu. Verwende folgende Einstellungen:</p>
      <label>URL<input readOnly value={endpoint} onFocus={e=>e.currentTarget.select()}/></label><button type="button" className="quiet" onClick={()=>void copy(endpoint)}>URL kopieren</button>
      <p>Methode: POST · Header: Authorization = Bearer DEIN_SCHLÜSSEL · Inhalt: JSON</p><p>JSON-Feld <code>original_text</code> = Eingabe/Diktat. Optional kann eine eindeutige UUID als <code>client_request_id</code> übergeben werden, um Wiederholungen derselben Übertragung zu erkennen.</p><p>Die API antwortet bei Erfolg mit einer Erfassungs-ID und status „saved“. Der Text liegt anschließend im Eingang zur KI-Prüfung. Starte den Kurzbefehl per Siri über seinen Namen. Verwende HTTPS, sofern es sich nicht um einen lokalen Test handelt.</p></details>
    <details><summary>Home Assistant einrichten</summary><p>Lege einen Statusschlüssel und bei Bedarf einen separaten Erfassungsschlüssel an. Für einen REST-Sensor verwende GET mit dem Statusschlüssel im Authorization-Header (Bearer). Empfohlenes Abfrageintervall: 60 Sekunden. Der Status enthält keine Namen oder Texte.</p><label>Status-URL<input readOnly value={statusEndpoint} onFocus={e=>e.currentTarget.select()}/></label><button type="button" className="quiet" onClick={()=>void copy(statusEndpoint)}>Status-URL kopieren</button><p>Der Wert notification_pending berücksichtigt Ruhezeiten und kann eine eigene Benachrichtigungsautomation auslösen. focus_active und routine_steps_open können für eigene Anzeigen genutzt werden. Zur gezielten Ereigniserfassung verwende POST an die oben genannte Erfassungs-URL mit dem separaten Erfassungsschlüssel. Keine Geräte werden durch LifePilot direkt gesteuert. YAML-Beispiele stehen in der README.</p></details>
  </section>;
}
