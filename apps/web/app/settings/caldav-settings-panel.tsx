"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Key = {id:string;label:string;scope:string;created_at:string;expires_at:string;revoked_at:string|null;active:boolean};
type Created = Key & {username:string;password:string;calendar_path:string|null;addressbook_path:string|null};
const base=(process.env.NEXT_PUBLIC_API_URL??"http://localhost:8000").replace(/\/$/,"");

export function CaldavSettingsPanel({request}:{request:Request}) {
  const [rows,setRows]=useState<Key[]>([]);
  const [scope,setScope]=useState("calendar:read");
  const [created,setCreated]=useState<Created|null>(null);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const load=useCallback(async()=>setRows(await request<Key[]>("/api/dav/keys")),[request]);
  useEffect(()=>{let live=true;load().catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[load]);
  async function create(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;const fields=new FormData(form);
    setBusy(true);setError("");setNotice("");
    try{
      const key=await request<Created>("/api/dav/keys",{method:"POST",body:JSON.stringify({label:fields.get("label"),expires_in_days:Number(fields.get("days")),current_password:fields.get("password"),scope})});
      setCreated(key);form.reset();await load();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function revoke(key:Key){
    if(!window.confirm("DAV-Zugang „"+key.label+"“ widerrufen?"))return;
    setBusy(true);setError("");
    try{await request("/api/dav/keys/"+key.id,{method:"DELETE"});if(created?.id===key.id)setCreated(null);await load();setNotice("Zugang widerrufen.");}
    catch(e){setError(String(e));}finally{setBusy(false);}
  }
  async function copy(value:string){
    try{await navigator.clipboard.writeText(value);setNotice("Kopiert.");}catch{setError("Kopieren nicht möglich. Bitte manuell markieren.");}
  }
  return <section className="card panel profile-panel">
    <div className="panel-head"><div><span className="eyebrow">INTEGRATIONEN</span><h2>CalDAV &amp; CardDAV</h2></div></div>
    <p>Termine und Kontakte in externen Kalendern und Adressbüchern anzeigen. Änderungen erfolgen weiterhin in LifePilot. Kalender und Kontakte benötigen jeweils einen eigenen Zugang. Externe Apps können exportierte Daten lokal speichern. Private Notizen, Beziehungen und Erlebnisse werden nicht exportiert.</p>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <form className="person-form" onSubmit={create}>
      <label>Integration<select value={scope} onChange={e=>setScope(e.target.value)} disabled={busy||!!created}><option value="calendar:read">CalDAV – Kalender</option><option value="contacts:read">CardDAV – Kontakte</option></select></label><label>Bezeichnung<input name="label" required maxLength={120} placeholder="Mein Kalender"/></label>
      <label>Gültigkeit<select name="days" defaultValue="90">{[7,30,90,180,365].map(d=><option key={d} value={d}>{d} Tage</option>)}</select></label>
      <label>Aktuelles Passwort<input name="password" type="password" required autoComplete="current-password"/></label>
      <button disabled={busy||loading||!!created}>DAV-Zugang erstellen</button>
    </form>
    {created&&<div className="inbox-item"><h3>Einmalige Zugangsdaten</h3><p>Verwende diese Zugangsdaten statt deines Kontopassworts. Nur über HTTPS übertragen.</p>
      {[[ "Server",base+(created.scope==="contacts:read"?"/carddav/":"/dav/") ],[created.scope==="contacts:read"?"Adressbuch-URL":"Kalender-URL",base+(created.addressbook_path??created.calendar_path??"")],["Benutzername",created.username],["App-Passwort",created.password]].map(([label,value])=><div key={label}><label>{label}<input readOnly value={value} onFocus={e=>e.currentTarget.select()} autoComplete="off"/></label><button type="button" className="quiet" onClick={()=>void copy(value)}>Kopieren</button></div>)}
      <button type="button" className="quiet" onClick={()=>setCreated(null)}>Anzeige schließen</button></div>}
    <h3>DAV-Zugänge verwalten</h3>
    {loading?<p className="muted">Zugänge werden geladen …</p>:rows.length===0?<p className="muted">Keine Zugänge vorhanden.</p>:rows.map(row=><div key={row.id} className="list-item"><span>{row.label}<small>{row.scope==="contacts:read"?"CardDAV":"CalDAV"} · {row.active?"Aktiv":row.revoked_at?"Widerrufen":"Inaktiv"} · Ablauf {new Date(row.expires_at).toLocaleDateString("de-DE")}</small></span>{row.active&&<button type="button" className="quiet" disabled={busy} onClick={()=>void revoke(row)}>Widerrufen</button>}</div>)}
    <details><summary>Kalender oder Adressbuch einrichten</summary><p>Füge in deiner Kalender-App ein CalDAV-Konto oder im Adressbuch ein CardDAV-Konto hinzu. Nutze die Server-URL, die Konto-ID als Benutzernamen und das generierte App-Passwort. Falls die automatische Erkennung nicht funktioniert, verwende die vollständige Kalender- bzw. Adressbuch-URL. Beim Passwortwechsel werden bisherige App-Passwörter ungültig.</p><p>Die Schnittstellen sind lesende Teilimplementierungen. CardDAV exportiert Namen, übliche Kontaktdaten, exakte Geburtstage und frei gepflegte berufliche Angaben, aber kein eigenes Profil, keine Fotos und keine privaten Notizen. Client-Kompatibilität muss praktisch geprüft werden.</p></details>
  </section>;
}
