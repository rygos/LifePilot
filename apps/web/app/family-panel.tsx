"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Space={id:string;name:string;role:"owner"|"viewer"|"editor"};
type Invitation={id:string;name:string;invited_by:string;role:string};
type Member={user_id:string;username:string;role:string;state:string};
type Kind="note"|"task"|"event"|"inventory";
type ShareKind="memory"|"task"|"event"|"inventory";
type Item={id:string;kind:Kind;title:string;notes:string;starts_at:string|null;ends_at:string|null;location:string;status:"open"|"done";revision:number;created_at:string};
type Share={id:string;kind:ShareKind;snapshot:Record<string,string|null>;shared_by:string;can_revoke:boolean;created_at:string};
type Candidate={id:string;title:string};
const labels:Record<string,string>={owner:"Eigentümer",viewer:"Lesen",editor:"Bearbeiten",note:"Notiz",memory:"Erinnerung",task:"Aufgabe",event:"Termin / Ereignis",inventory:"Gegenstand",title:"Titel",notes:"Text",status:"Status",due_at:"Fälligkeit",starts_at:"Beginn",ends_at:"Ende",location:"Ort",record_type:"Art",category:"Kategorie",occurred_at:"Ereignisdatum",open:"Offen",done:"Erledigt",appointment:"Termin",experience:"Erlebnis"};
const format=(s:string)=>new Date(s).toLocaleString("de-DE",{dateStyle:"medium",timeStyle:"short"});
function showValue(k:string,v:string|null){if(v===null||v==="")return "Nicht angegeben";if(k.endsWith("_at"))return format(v);if(k==="status"||k==="record_type")return labels[v]??v;return v;}
function localInput(value:string|null|undefined){
  if(!value)return "";
  const d=new Date(value);
  return [d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-")+"T"+String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0");
}
function itemBody(item:Item){return {kind:item.kind,title:item.title,notes:item.notes,starts_at:item.starts_at,ends_at:item.ends_at,location:item.location,status:item.status,revision:item.revision};}
function Snapshot({snapshot}:{snapshot:Record<string,string|null>}){
  return <div className="family-snapshot">{Object.entries(snapshot).map(([k,v])=><div key={k}><strong>{labels[k]??k}</strong><p>{showValue(k,v)}</p></div>)}</div>;
}
function ItemForm({item,busy,onSave}:{item?:Item;busy:boolean;onSave:(data:object)=>Promise<void>}){
  const [kind,setKind]=useState<Kind>(item?.kind??"task");
  function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const f=new FormData(e.currentTarget);
    const date=(k:string)=>f.get(k)?new Date(String(f.get(k))).toISOString():null;
    void onSave({kind,title:f.get("title"),notes:f.get("notes"),starts_at:kind==="task"||kind==="event"?date("starts_at"):null,ends_at:kind==="event"?date("ends_at"):null,location:f.get("location"),status:kind==="task"?f.get("status"):"open",...(item?{revision:item.revision}:{})});
  }
  return <form className="person-form" onSubmit={submit}>
    <label>Art<select value={kind} onChange={e=>setKind(e.target.value as Kind)}>{(["note","task","event","inventory"] as Kind[]).map(k=><option value={k} key={k}>{labels[k]}</option>)}</select></label>
    <label>Titel<input name="title" required maxLength={240} defaultValue={item?.title}/></label>
    <label>Gemeinsame Notizen<textarea name="notes" maxLength={10000} defaultValue={item?.notes}/></label>
    {(kind==="task"||kind==="event")&&<label>{kind==="task"?"Fällig am":"Beginn"}<input name="starts_at" type="datetime-local" required={kind==="event"} defaultValue={localInput(item?.starts_at)}/></label>}
    {kind==="event"&&<label>Ende<input name="ends_at" type="datetime-local" defaultValue={localInput(item?.ends_at)}/></label>}
    <label>Ort / Lagerplatz<input name="location" maxLength={500} defaultValue={item?.location}/></label>
    {kind==="task"&&<label>Status<select name="status" defaultValue={item?.status??"open"}><option value="open">Offen</option><option value="done">Erledigt</option></select></label>}
    <p className="muted">Dieser Eintrag gehört dem Familienbereich und bleibt beim Verlassen des Bereichs erhalten. Alle Bearbeiter dürfen ihn ändern oder löschen.</p>
    <button disabled={busy}>Gemeinsamen Eintrag speichern</button>
  </form>;
}
function ShareForm({request,sid,candidates,busy,onSave}:{request:Request;sid:string;candidates:Record<Exclude<ShareKind,"inventory">,Candidate[]>;busy:boolean;onSave:()=>Promise<void>}){
  const [kind,setKind]=useState<ShareKind>("memory"),[resource,setResource]=useState(""),[notes,setNotes]=useState(false),[details,setDetails]=useState(false),[inventory,setInventory]=useState<Candidate[]>([]),[offset,setOffset]=useState(0),[preview,setPreview]=useState<{snapshot:Record<string,string|null>;digest:string}|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState("");
  useEffect(()=>{if(kind!=="inventory")return;let live=true;setLoading(true);request<{id:string;name:string}[]>("/api/inventory?limit=50&offset="+offset,{cache:"no-store"}).then(rows=>{if(live)setInventory(rows.map(r=>({id:r.id,title:r.name})));}).catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[kind,offset,request]);
  const rows=kind==="inventory"?inventory:candidates[kind];
  const body={kind,resource_id:resource,include_notes:notes,include_details:details};
  async function inspect(){setLoading(true);setPreview(null);setError("");try{setPreview(await request("/api/family/"+sid+"/shares/preview",{method:"POST",body:JSON.stringify(body),cache:"no-store"}));}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setLoading(false);}}
  async function save(){if(!preview)return;if(!window.confirm("Genau diese Momentaufnahme allen aktuellen und zukünftigen Mitgliedern dieses Bereichs freigeben?"))return;setLoading(true);setError("");try{await request("/api/family/"+sid+"/shares",{method:"POST",body:JSON.stringify({...body,digest:preview.digest}),cache:"no-store"});setPreview(null);setResource("");await onSave();}catch(e){setError(e instanceof Error?e.message:String(e));setPreview(null);}finally{setLoading(false);}}
  return <form className="person-form" onSubmit={e=>{e.preventDefault();void inspect();}}>
    <p>Nur ausgewählte Felder eines privaten Originals werden als unveränderliche Momentaufnahme geteilt. Die Freigabe ist separat zu widerrufen, auch wenn du das Original später änderst oder löschst. Keine privaten Personenbezüge, Anhänge, Seriennummern oder Quell-IDs werden mitgegeben.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <fieldset disabled={busy||loading} className="family-fields">
      <label>Datensatztyp<select value={kind} onChange={e=>{setKind(e.target.value as ShareKind);setResource("");setPreview(null);setOffset(0);}}>{(["memory","task","event","inventory"] as ShareKind[]).map(k=><option key={k} value={k}>{labels[k]}</option>)}</select></label>
      <label>Privater Datensatz<select required value={resource} onChange={e=>{setResource(e.target.value);setPreview(null);}}><option value="">Auswählen</option>{rows.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
      {kind==="inventory"&&<div className="commitment-actions"><button type="button" disabled={offset===0} onClick={()=>{setResource("");setPreview(null);setOffset(v=>Math.max(0,v-50));}}>Zurück</button><button type="button" disabled={rows.length<50} onClick={()=>{setResource("");setPreview(null);setOffset(v=>v+50);}}>Weitere Gegenstände</button></div>}
      <label><input type="checkbox" checked={notes} onChange={e=>{setNotes(e.target.checked);setPreview(null);}}/> Text / Notizen mitgeben</label>
      <label><input type="checkbox" checked={details} onChange={e=>{setDetails(e.target.checked);setPreview(null);}}/> Datums-, Status- oder Ortsdetails mitgeben</label>
      <button disabled={!resource}>Vorschau erstellen</button>
    </fieldset>
    {preview&&<article className="inbox-item"><h3>Exakt diese Felder werden geteilt</h3><Snapshot snapshot={preview.snapshot}/><button type="button" disabled={busy||loading} onClick={()=>void save()}>Freigabe bestätigen</button></article>}
  </form>;
}
function SpaceDetail({space,request,candidates,onChange}:{space:Space;request:Request;candidates:Record<Exclude<ShareKind,"inventory">,Candidate[]>;onChange:()=>Promise<void>}){
  const [members,setMembers]=useState<Member[]>([]),[items,setItems]=useState<Item[]>([]),[shares,setShares]=useState<Share[]>([]),[itemOffset,setItemOffset]=useState(0),[shareOffset,setShareOffset]=useState(0),[mode,setMode]=useState(""),[editing,setEditing]=useState<Item|undefined>(),[busy,setBusy]=useState(false),[error,setError]=useState(""),[loading,setLoading]=useState(true),[password,setPassword]=useState("");
  const base="/api/family/"+space.id;
  const writable=space.role!=="viewer";
  const load=useCallback(async()=>{const [m,i,s]=await Promise.all([request<Member[]>(base+"/members",{cache:"no-store"}),request<Item[]>(base+"/items?limit=30&offset="+itemOffset,{cache:"no-store"}),request<Share[]>(base+"/shares?limit=30&offset="+shareOffset,{cache:"no-store"})]);setMembers(m);setItems(i);setShares(s);},[request,base,itemOffset,shareOffset]);
  useEffect(()=>{let live=true;setLoading(true);setError("");Promise.all([request<Member[]>(base+"/members",{cache:"no-store"}),request<Item[]>(base+"/items?limit=30&offset="+itemOffset,{cache:"no-store"}),request<Share[]>(base+"/shares?limit=30&offset="+shareOffset,{cache:"no-store"})]).then(([m,i,s])=>{if(live){setMembers(m);setItems(i);setShares(s);}}).catch(e=>{if(live){setMembers([]);setItems([]);setShares([]);setError(String(e));}}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[request,base,itemOffset,shareOffset]);
  async function run(fn:()=>Promise<unknown>,reload=true){setBusy(true);setError("");try{await fn();setMode("");setEditing(undefined);setPassword("");if(reload)await load();await onChange();}catch(e){setError(e instanceof Error?e.message:String(e));setPassword("");}finally{setBusy(false);}}
  async function refresh(){setBusy(true);setError("");try{await load();await onChange();}catch(e){setMembers([]);setItems([]);setShares([]);setError(String(e));await onChange().catch(()=>{});}finally{setBusy(false);}}
  function mutate(path:string,method:string,body?:object,reload=true){void run(()=>request(base+path,{method,cache:"no-store",...(body?{body:JSON.stringify(body)}:{})}),reload);}
  return <article className="card panel family-detail">
    <div className="panel-head"><div><h2>{space.name}</h2><p className="muted">Deine Rolle: {labels[space.role]}</p></div><button type="button" className="quiet" disabled={busy} onClick={()=>void refresh()}>Aktualisieren</button></div>
    {error&&<p className="error" role="alert">{error}</p>}
    {loading?<p>Lade Familienbereich …</p>:<>
      <h3>Mitglieder</h3>{members.map(m=><div className="list-item" key={m.user_id}><span>{m.username}<small>{labels[m.role]}{m.state==="pending"?" · Einladung offen":""}</small></span>{space.role==="owner"&&m.role!=="owner"&&<div className="commitment-actions"><select aria-label={"Rolle für "+m.username} disabled={busy} value={m.role} onChange={e=>mutate("/members/"+m.user_id,"PATCH",{role:e.target.value})}><option value="viewer">Lesen</option><option value="editor">Bearbeiten</option></select><button type="button" disabled={busy} className="quiet danger-text" onClick={()=>{if(window.confirm("Zugriff und eigene Freigaben dieses Mitglieds entfernen? Gemeinschaftliche Einträge bleiben erhalten."))mutate("/members/"+m.user_id,"DELETE");}}>Entfernen</button></div>}</div>)}
      {space.role==="owner"?<form className="person-form" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);mutate("/invite","POST",{username:f.get("username"),role:f.get("role")});}}><label>Vorhandenes LifePilot-Konto einladen<input name="username" required maxLength={120} autoComplete="off"/></label><label>Berechtigung<select name="role"><option value="viewer">Lesen</option><option value="editor">Bearbeiten</option></select></label><button disabled={busy}>Einladung erstellen</button></form>:<button type="button" className="quiet" disabled={busy} onClick={()=>{if(window.confirm("Bereich verlassen? Eigene Freigaben werden widerrufen; gemeinschaftliche Einträge bleiben erhalten."))mutate("/leave","POST",undefined,false);}}>Familienbereich verlassen</button>}
      <h3>Gemeinsame Aufgaben, Termine, Gegenstände und Notizen</h3>
      {writable&&<button type="button" disabled={busy} onClick={()=>{setEditing(undefined);setMode(v=>v==="item"?"":"item");}}>Gemeinsamen Eintrag hinzufügen</button>}
      {mode==="item"&&writable&&<ItemForm key={editing?.id??"new"} item={editing} busy={busy} onSave={async data=>{await run(()=>request(base+"/items"+(editing?"/"+editing.id:""),{method:editing?"PUT":"POST",body:JSON.stringify(data),cache:"no-store"}));}}/>}
      {items.length===0?<p className="muted">Keine gemeinsamen Einträge.</p>:items.map(i=><div key={i.id} className="inbox-item"><h4>{i.title}</h4><small>{labels[i.kind]}{i.kind==="task"?" · "+labels[i.status]:""}</small>{i.notes&&<p>{i.notes}</p>}{i.starts_at&&<p>{i.kind==="task"?"Fällig: ":"Beginn: "}{format(i.starts_at)}{i.ends_at?" · Ende: "+format(i.ends_at):""}</p>}{i.location&&<p>Ort: {i.location}</p>}
        {writable&&<div className="commitment-actions">{i.kind==="task"&&<button type="button" disabled={busy} onClick={()=>mutate("/items/"+i.id,"PUT",{...itemBody(i),status:i.status==="open"?"done":"open"})}>{i.status==="open"?"Erledigt":"Wieder öffnen"}</button>}<button type="button" disabled={busy} className="quiet" onClick={()=>{setEditing(i);setMode("item");}}>Bearbeiten</button><button type="button" disabled={busy} className="quiet danger-text" onClick={()=>{if(window.confirm("Gemeinsamen Eintrag endgültig löschen? Er ist noch nicht im Papierkorb wiederherstellbar."))mutate("/items/"+i.id+"/delete","POST",{revision:i.revision});}}>Löschen</button></div>}</div>)}
      <div className="commitment-actions"><button type="button" disabled={busy||itemOffset===0} onClick={()=>setItemOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={busy||items.length<30} onClick={()=>setItemOffset(v=>v+30)}>Weitere Einträge</button></div>
      <h3>Freigegebene private Datensätze</h3><p className="muted">Diese Momentaufnahmen sind für alle Mitglieder sichtbar, aber nicht gemeinsam bearbeitbar.</p>
      {writable&&<button type="button" disabled={busy} onClick={()=>setMode(v=>v==="share"?"":"share")}>Privaten Datensatz freigeben</button>}
      {mode==="share"&&writable&&<ShareForm request={request} sid={space.id} candidates={candidates} busy={busy} onSave={async()=>{setMode("");await load();}}/>}
      {shares.map(s=><div className="inbox-item" key={s.id}><small>{labels[s.kind]} · Freigabe von {s.shared_by} · {format(s.created_at)}</small><Snapshot snapshot={s.snapshot}/>{s.can_revoke&&<button type="button" className="quiet danger-text" disabled={busy} onClick={()=>{if(window.confirm("Diese Momentaufnahme für alle Mitglieder widerrufen? Bereits gelesene oder kopierte Daten können nicht zurückgerufen werden."))mutate("/shares/"+s.id,"DELETE");}}>Freigabe widerrufen</button>}</div>)}
      {shares.length===0&&<p className="muted">Keine Freigaben.</p>}
      <div className="commitment-actions"><button type="button" disabled={busy||shareOffset===0} onClick={()=>setShareOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={busy||shares.length<30} onClick={()=>setShareOffset(v=>v+30)}>Weitere Freigaben</button></div>
      {space.role==="owner"&&<details><summary>Familienbereich endgültig löschen</summary><form className="person-form" onSubmit={e=>{e.preventDefault();if(window.confirm("Bereich, gemeinsame Einträge und Freigaben endgültig entfernen? Private Originale bleiben erhalten."))mutate("/delete","POST",{password},false);}}><label>Aktuelles Passwort<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required autoComplete="current-password" maxLength={1024}/></label><button disabled={busy||!password}>Familienbereich löschen</button></form></details>}
    </>}
  </article>;
}
export function FamilyPanel({request,memories,tasks,events}:{request:Request;memories:Candidate[];tasks:Candidate[];events:Candidate[]}){
  const [spaces,setSpaces]=useState<Space[]>([]),[invitations,setInvitations]=useState<Invitation[]>([]),[selected,setSelected]=useState(""),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState("");
  const load=useCallback(async()=>{const result=await request<{spaces:Space[];invitations:Invitation[]}>("/api/family",{cache:"no-store"});setSpaces(result.spaces);setInvitations(result.invitations);setSelected(old=>result.spaces.some(s=>s.id===old)?old:"");},[request]);
  useEffect(()=>{let live=true;setLoading(true);request<{spaces:Space[];invitations:Invitation[]}>("/api/family",{cache:"no-store"}).then(r=>{if(live){setSpaces(r.spaces);setInvitations(r.invitations);}}).catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[request]);
  async function run(fn:()=>Promise<unknown>){setBusy(true);setError("");try{await fn();await load();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  useEffect(()=>{const refresh=()=>{if(document.visibilityState==="visible")void load().catch(()=>{setSelected("");setSpaces([]);setInvitations([]);});};document.addEventListener("visibilitychange",refresh);return()=>document.removeEventListener("visibilitychange",refresh);},[load]);
  const space=spaces.find(s=>s.id===selected);
  return <section className="card panel family-panel">
    <div className="panel-head"><div><span className="eyebrow">GEMEINSAM ORGANISIEREN</span><h2>Familienbereiche</h2></div><button type="button" className="quiet" disabled={busy} onClick={()=>void run(load)}>Aktualisieren</button></div>
    <p>Private Daten bleiben privat. Familienbereiche sind getrennte Arbeitsräume mit ausdrücklichen Einladungen und Freigaben. Mitglieder können geteilte Informationen lesen und kopieren; bei ausdrücklich aktiviertem Familien-MCP-Lesezugriff auch über ein Sprachmodell abrufen.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    {invitations.length>0&&<><h3>Einladungen</h3>{invitations.map(i=><div className="list-item" key={i.id}><span>{i.name}<small>Von {i.invited_by} · {labels[i.role]}</small></span><button type="button" disabled={busy} onClick={()=>void run(()=>request("/api/family/"+i.id+"/accept",{method:"POST"}))}>Annehmen</button><button type="button" className="quiet" disabled={busy} onClick={()=>void run(()=>request("/api/family/"+i.id+"/decline",{method:"POST"}))}>Ablehnen</button></div>)}</>}
    <form className="person-form" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);void run(async()=>{const row=await request<Space>("/api/family",{method:"POST",body:JSON.stringify({name:f.get("name")})});setSelected(row.id);});}}><label>Neuer Familienbereich<input name="name" required maxLength={120} placeholder="z. B. Unser Haushalt"/></label><button disabled={busy}>Bereich anlegen</button></form>
    {loading?<p>Lade Bereiche …</p>:spaces.length===0?<p>Keine Familienbereiche vorhanden.</p>:<label>Bereich auswählen<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Auswählen</option>{spaces.map(s=><option key={s.id} value={s.id}>{s.name} · {labels[s.role]}</option>)}</select></label>}
    {space&&<SpaceDetail key={space.id+":"+space.role} space={space} request={request} candidates={{memory:memories,task:tasks,event:events}} onChange={load}/>}
  </section>;
}
