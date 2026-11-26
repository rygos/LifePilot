"use client";
import {useEffect,useState,type FormEvent} from "react";
type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Person = {id:string;name:string};
type Mail = {uid:number;size:number;subject:string;sender:string;recipient:string;date:string;too_large:boolean;people:Person[];imported:boolean};
type Preview = {message:Mail;text:string;preview_hash:string;people:Person[]};
export function MailSettingsPanel({request}:{request:Request}) {
  const [enabled,setEnabled]=useState<boolean|null>(null);
  const [username,setUsername]=useState("");
  const [password,setPassword]=useState("");
  const [version,setVersion]=useState<number|null>(null);
  const [rows,setRows]=useState<Mail[]>([]);
  const [preview,setPreview]=useState<Preview|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  useEffect(()=>{let live=true;request<{enabled:boolean}>("/api/mail/status").then(s=>{if(live)setEnabled(s.enabled);}).catch(e=>{if(live)setError(String(e));});return()=>{live=false;};},[request]);
  const post=<T,>(path:string,data:object={})=>request<T>("/api/mail/"+path,{method:"POST",body:JSON.stringify({username,password,...data})});
  async function run(action:()=>Promise<void>) {setBusy(true);setError("");setNotice("");try{await action();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  function list(e:FormEvent<HTMLFormElement>){e.preventDefault();setPreview(null);setRows([]);setVersion(null);void run(async()=>{const result=await post<{uidvalidity:number;messages:Mail[]}>("messages");setVersion(result.uidvalidity);setRows(result.messages);});}
  function reset(){setPassword("");setRows([]);setVersion(null);setPreview(null);setNotice("");setError("");}
  return <section className="card panel profile-panel">
    <div className="panel-head"><div><span className="eyebrow">INTEGRATIONEN</span><h2>E-Mail – IMAP-Import</h2></div></div>
    <p>Die letzten 20 Nachrichten im Posteingang anzeigen und einzelne Textnachrichten nach Vorschau in LifePilot übernehmen. Es werden keine Nachrichten verändert, verschoben oder als gelesen markiert. Nur ausgewählte Inhalte gelangen zur KI-Prüfung.</p>
    {enabled===false&&<p className="muted">IMAP ist serverseitig noch nicht konfiguriert.</p>}
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {enabled&&<>
      <form className="person-form" onSubmit={list}>
        <label>IMAP-Benutzername<input value={username} onChange={e=>{reset();setUsername(e.target.value);}} disabled={busy} required maxLength={320} autoComplete="off"/></label>
        <label>IMAP-Passwort<input type="password" value={password} onChange={e=>{setRows([]);setPreview(null);setVersion(null);setPassword(e.target.value);}} disabled={busy} required autoComplete="off" maxLength={1024}/></label>
        <p className="muted">Zugangsdaten werden nicht in LifePilot gespeichert. Nutze HTTPS und möglichst ein separates App-Passwort.</p>
        <div className="commitment-actions"><button disabled={busy||!username||!password}>Posteingang laden</button><button type="button" className="quiet" disabled={busy} onClick={reset}>Zugangsdaten und Vorschau entfernen</button></div>
      </form>
      {version!==null&&<><h3>Posteingang</h3>{!rows.length&&<p className="muted">Keine Nachrichten gefunden.</p>}{rows.map(row=><div className="list-item" key={row.uid}><span>{row.subject||"(Ohne Betreff)"}<small>{row.sender} · {row.date}</small>{row.people.length>0&&<small>Mögliche Zuordnung: {row.people.map(p=>p.name).join(", ")} (Absender nicht verifiziert)</small>}{row.imported&&<small>Bereits übernommen</small>}{row.too_large&&<small>Zu groß für den Import</small>}</span><button type="button" disabled={busy||row.too_large||row.imported} onClick={()=>{setPreview(null);void run(async()=>setPreview(await post<Preview>("preview",{uid:row.uid,uidvalidity:version})));}}>Vorschau</button></div>)}</>}
      {preview&&<div className="inbox-item"><h3>Vorschau – noch nicht gespeichert</h3><p>Prüfe, ob der Inhalt einschließlich personenbezogener Daten an dein konfiguriertes Sprachmodell übergeben werden darf. Absenderangaben sind nicht verifiziert.</p><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{preview.text}</pre><div className="commitment-actions"><button type="button" disabled={busy} onClick={()=>void run(async()=>{const result=await post<{id:string;status:string}>("import",{uid:preview.message.uid,uidvalidity:version,preview_hash:preview.preview_hash});setRows(old=>old.map(row=>row.uid===preview.message.uid?{...row,imported:true}:row));setPreview(null);setNotice("E-Mail übernommen. Status: "+result.status+". Öffne den Eingang zur Prüfung.");})}>E-Mail zur KI-Prüfung übernehmen</button><button type="button" disabled={busy} className="quiet" onClick={()=>setPreview(null)}>Verwerfen</button></div><a href="/inbox">Zum Eingang</a></div>}
    </>}
  </section>;
}
