"use client";
import {useCallback,useEffect,useState} from "react";
type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Entry={id:string;resource_type:string;resource_id:string;label:string;deleted_at:string;expires_at:string;related_records:number};
type Result={retention_days:number;items:Entry[]};
const labels:Record<string,string>={tasks:"Aufgabe",journal_entries:"Tagebuch",loans:"Leihgabe",gifts:"Geschenkidee",places:"Ort",place_entries:"Ortseintrag"};
const format=(value:string)=>new Date(value).toLocaleString("de-DE",{dateStyle:"medium",timeStyle:"short"});
export function TrashPanel({request,onChange}:{request:Request;onChange:()=>Promise<void>}){
  const [open,setOpen]=useState(false),[data,setData]=useState<Result|null>(null),[offset,setOffset]=useState(0),[purge,setPurge]=useState<string|null>(null),[password,setPassword]=useState(""),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const load=useCallback(async()=>setData(await request<Result>("/api/trash?limit=30&offset="+offset)),[request,offset]);
  useEffect(()=>{if(!open)return;let live=true;setLoading(true);request<Result>("/api/trash?limit=30&offset="+offset).then(v=>{if(live)setData(v);}).catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[open,request,offset]);
  async function run(fn:()=>Promise<void>,message:string){setBusy(true);setError("");setNotice("");try{await fn();setPurge(null);setPassword("");await load();await onChange();setNotice(message);}catch(e){setError(e instanceof Error?e.message:String(e));setPassword("");}finally{setBusy(false);}}
  return <section className="card panel trash-panel" id="trash">
    <div className="panel-head"><div><span className="eyebrow">DATENVERLUST VERMEIDEN</span><h2>Papierkorb</h2></div><button type="button" className="quiet" disabled={busy} onClick={()=>{setOpen(v=>!v);setPurge(null);setPassword("");setError("");}}>{open?"Schließen":"Papierkorb öffnen"}</button></div>
    <p className="muted">Unterstützt Aufgaben, Tagebuch, Leihgaben, Geschenkideen, Orte und Ortseinträge. Andere Datensatztypen und Dateien werden noch endgültig gelöscht. Der Papierkorb ersetzt kein Backup.</p>
    {open&&<>{data&&<p>Aufbewahrung bei neuen Löschungen: {data.retention_days} Tage. Bereits gespeicherte Ablaufdaten bleiben unverändert.</p>}
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {loading?<p>Lade Papierkorb …</p>:data?.items.length===0?<p>Keine wiederherstellbaren Einträge.</p>:data?.items.map(item=><article key={item.id} className="inbox-item"><h3>{item.label}</h3><p>{labels[item.resource_type]??item.resource_type} · {item.related_records} abhängige Datensätze/Verknüpfungen</p><p className="muted">Gelöscht: {format(item.deleted_at)} · Wiederherstellbar bis: {format(item.expires_at)}</p>
      <div className="commitment-actions"><button disabled={busy} type="button" onClick={()=>{if(window.confirm("Eintrag mit ursprünglichen IDs und Verknüpfungen wiederherstellen?"))void run(async()=>{await request("/api/trash/"+item.id+"/restore",{method:"POST"});},"Eintrag wiederhergestellt.");}}>Wiederherstellen</button><button type="button" className="quiet danger-text" disabled={busy} onClick={()=>{setPurge(item.id);setPassword("");}}>Endgültig löschen</button></div>
      {purge===item.id&&<form className="person-form" onSubmit={e=>{e.preventDefault();if(password)void run(async()=>{await request("/api/trash/"+item.id+"/purge",{method:"POST",body:JSON.stringify({password})});},"Eintrag endgültig entfernt.");}}><p>Diese Sicherung wird unwiderruflich entfernt. Vorhandene Backups oder Revisionsprotokolle bleiben davon unberührt.</p><label>Aktuelles Passwort<input type="password" value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required maxLength={1024}/></label><button disabled={busy||!password}>Endgültige Löschung bestätigen</button><button type="button" className="quiet" disabled={busy} onClick={()=>{setPurge(null);setPassword("");}}>Abbrechen</button></form>}
    </article>)}
    <p className="muted">Wenn eine verknüpfte Ressource fehlt oder sich eine Verknüpfung geändert hat, wird nichts wiederhergestellt. Prüfe zuerst die fehlende Ressource.</p>
    <div className="commitment-actions"><button type="button" disabled={busy||loading||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={busy||loading||!data||data.items.length<30} onClick={()=>setOffset(v=>v+30)}>Weiter</button><button type="button" className="quiet" disabled={busy||loading} onClick={()=>void run(load,"Aktualisiert.")}>Aktualisieren</button></div></>}
  </section>;
}
