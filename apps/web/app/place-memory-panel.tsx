"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";
type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Person={id:string;first_name:string;last_name:string};
type Resource={id:string;title:string};
type Place={id:string;name:string;category:string;address:string;latitude:number|null;longitude:number|null;notes:string;archived:boolean};
type Entry={id:string;place_id:string;kind:string;title:string;notes:string;occurred_on:string|null;person_id:string|null;event_id:string|null;conversation_id:string|null;memory_id:string|null};
const labels:Record<string,string>={visit:"Besuch",meeting:"Begegnung",recommendation:"Empfehlung",memory:"Erinnerung",reference:"Sonstiger Ortsbezug"};
const dateLabel=(day:string)=>new Date(day+"T12:00:00Z").toLocaleDateString("de-DE",{timeZone:"UTC"});
function PlaceForm({place,busy,onSave}:{place?:Place;busy:boolean;onSave:(data:object)=>Promise<void>}){
  return <form className="person-form" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);const coord=(k:string)=>f.get(k)===""?null:Number(f.get(k));void onSave({name:f.get("name"),category:f.get("category"),address:f.get("address"),latitude:coord("latitude"),longitude:coord("longitude"),notes:f.get("notes")});}}>
    <label>Name<input name="name" maxLength={240} required defaultValue={place?.name}/></label>
    <label>Kategorie<input name="category" maxLength={120} defaultValue={place?.category} placeholder="z. B. Restaurant, Arbeitsplatz, Urlaub"/></label>
    <label>Adresse<textarea name="address" maxLength={500} defaultValue={place?.address}/></label>
    <details open={place?.latitude!=null?true:undefined}><summary>Koordinaten (optional)</summary><p className="muted">Nur selbst eingetragene Koordinaten. Kein GPS-Abruf oder externer Kartendienst.</p><label>Breitengrad<input type="number" name="latitude" min="-90" max="90" step="any" defaultValue={place?.latitude??""}/></label><label>Längengrad<input type="number" name="longitude" min="-180" max="180" step="any" defaultValue={place?.longitude??""}/></label></details>
    <label>Notizen und persönliche Bedeutung<textarea name="notes" maxLength={10000} defaultValue={place?.notes}/></label><button disabled={busy}>Ort speichern</button>
  </form>;
}
function EntryForm({people,events,conversations,memories,busy,onSave}:{people:Person[];events:Resource[];conversations:Resource[];memories:Resource[];busy:boolean;onSave:(data:object)=>Promise<void>}){
  function submit(e:FormEvent<HTMLFormElement>){e.preventDefault();const f=new FormData(e.currentTarget);void onSave({kind:f.get("kind"),title:f.get("title"),notes:f.get("notes"),occurred_on:f.get("occurred_on")||null,person_id:f.get("person_id")||null,event_id:f.get("event_id")||null,conversation_id:f.get("conversation_id")||null,memory_id:f.get("memory_id")||null});}
  return <form className="person-form" onSubmit={submit}>
    <label>Art<select name="kind">{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
    <label>Titel<input name="title" maxLength={240} required/></label>
    <label>Datum (falls bekannt)<input type="date" name="occurred_on"/></label>
    <label>Notizen<textarea name="notes" maxLength={10000}/></label>
    <details><summary>Bestehende Inhalte verknüpfen</summary><label>Person<select name="person_id"><option value="">Keine</option>{people.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>
    {([["event_id","Ereignis / Termin",events],["conversation_id","Gespräch",conversations],["memory_id","Erinnerung",memories]] as const).map(([name,label,rows])=><label key={name}>{label}<select name={name}><option value="">Kein Bezug</option>{rows.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select></label>)}</details>
    <button disabled={busy}>Ortseintrag speichern</button>
  </form>;
}
export function PlaceMemoryPanel({request,people,events,conversations,memories}:{request:Request;people:Person[];events:Resource[];conversations:Resource[];memories:Resource[]}){
  const [open,setOpen]=useState(false),[rows,setRows]=useState<Place[]>([]),[q,setQ]=useState(""),[term,setTerm]=useState(""),[person,setPerson]=useState(""),[archived,setArchived]=useState(false),[offset,setOffset]=useState(0),[selected,setSelected]=useState<Place|null>(null),[entries,setEntries]=useState<Entry[]>([]),[entryOffset,setEntryOffset]=useState(0),[creating,setCreating]=useState(false),[editing,setEditing]=useState(false),[adding,setAdding]=useState(false),[busy,setBusy]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState("");
  const query=useCallback(()=>{const p=new URLSearchParams({archived:String(archived),limit:"30",offset:String(offset)});if(term)p.set("q",term);if(person)p.set("person_id",person);return p.toString();},[term,person,archived,offset]);
  const load=useCallback(async()=>setRows(await request<Place[]>("/api/places?"+query())),[request,query]);
  useEffect(()=>{if(!open)return;let live=true;setLoading(true);request<Place[]>("/api/places?"+query()).then(v=>{if(live)setRows(v);}).catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[open,request,query]);
  async function run(fn:()=>Promise<void>){setBusy(true);setError("");try{await fn();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  async function show(id:string,at=0){const [place,list]=await Promise.all([request<Place>("/api/places/"+id),request<Entry[]>("/api/places/"+id+"/entries?limit=30&offset="+at)]);setSelected(place);setEntries(list);setEntryOffset(at);}
  async function save(data:object){await run(async()=>{const result=await request<Place>("/api/places"+(editing&&selected?"/"+selected.id:""),{method:editing?"PUT":"POST",body:JSON.stringify(data)});setCreating(false);setEditing(false);await show(result.id);await load();});}
  async function add(data:object){if(!selected)return;await run(async()=>{await request("/api/places/"+selected.id+"/entries",{method:"POST",body:JSON.stringify(data)});setAdding(false);await show(selected.id);await load();});}
  const personName=(id:string)=>{const p=people.find(p=>p.id===id);return p?p.first_name+" "+p.last_name:"Verknüpfte Person";};
  return <section className="card panel place-memory-panel" id="place-memory">
    <div className="panel-head"><div><span className="eyebrow">ORTE &amp; ERINNERUNGEN</span><h2>Ortsgedächtnis</h2></div><button type="button" className="quiet" onClick={()=>setOpen(v=>!v)}>{open?"Schließen":"Orte öffnen"}</button></div>
    <p className="muted">Manuell gepflegte Orte, Besuche, Begegnungen und Empfehlungen. Kein automatischer Standortverlauf.</p>
    {open&&<>{error&&<p className="error" role="alert">{error}</p>}<button type="button" disabled={busy} onClick={()=>{setEditing(false);setAdding(false);setCreating(v=>!v);}}>{creating?"Formular schließen":"Ort hinzufügen"}</button>
    {creating&&<PlaceForm busy={busy} onSave={save}/>}
    <form className="person-form" onSubmit={e=>{e.preventDefault();setTerm(q.trim());setOffset(0);}}><label>Orte und Notizen suchen<input value={q} maxLength={200} onChange={e=>setQ(e.target.value)}/></label><button disabled={busy}>Suchen</button></form>
    <div className="person-form"><label>Person<select value={person} onChange={e=>{setPerson(e.target.value);setOffset(0);}}><option value="">Alle</option>{people.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label><label><input type="checkbox" checked={archived} onChange={e=>{setArchived(e.target.checked);setOffset(0);}}/> Archivierte Orte anzeigen</label></div>
    {loading?<p>Lade Orte …</p>:rows.length===0?<p>Keine passenden Orte.</p>:rows.map(place=><div className="list-item" key={place.id}><span>{place.name}<small>{[place.category,place.address].filter(Boolean).join(" · ")}</small></span><button type="button" className="quiet" disabled={busy} onClick={()=>void run(async()=>{setEditing(false);setAdding(false);setCreating(false);await show(place.id);})}>Öffnen</button></div>)}
    <div className="commitment-actions"><button type="button" disabled={offset===0||busy||loading} onClick={()=>setOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={rows.length<30||busy||loading} onClick={()=>setOffset(v=>v+30)}>Weiter</button></div>
    {selected&&<article className="inbox-item place-detail"><h3>{selected.name}{selected.archived?" (archiviert)":""}</h3><p>{selected.category}</p><p>{selected.address}</p>{selected.latitude!==null&&<p>Koordinaten: {selected.latitude}, {selected.longitude}</p>}<p>{selected.notes}</p>
      <div className="commitment-actions"><button type="button" disabled={busy} onClick={()=>{setCreating(false);setEditing(v=>!v);}}>Bearbeiten</button><button type="button" disabled={busy} onClick={()=>void run(async()=>{await request("/api/places/"+selected.id+"/archive",{method:"PATCH",body:JSON.stringify({archived:!selected.archived})});setAdding(false);await show(selected.id);await load();})}>{selected.archived?"Reaktivieren":"Archivieren"}</button>
      <button type="button" className="quiet" disabled={busy} onClick={()=>{if(window.confirm("Ort und seine Ortseinträge in den Papierkorb verschieben? Verknüpfte Personen und Ereignisse bleiben erhalten."))void run(async()=>{await request("/api/places/"+selected.id,{method:"DELETE"});setSelected(null);setEditing(false);setAdding(false);await load();});}}>In den Papierkorb</button></div>
      {editing&&<PlaceForm key={selected.id} place={selected} busy={busy} onSave={save}/>}
      <h4>Ortseinträge</h4>{!selected.archived&&<button type="button" disabled={busy} onClick={()=>setAdding(v=>!v)}>{adding?"Schließen":"Eintrag hinzufügen"}</button>}{adding&&!selected.archived&&<EntryForm people={people} events={events} conversations={conversations} memories={memories} busy={busy} onSave={add}/>}
      {entries.length===0?<p>Keine Ortseinträge.</p>:entries.map(e=><div className="inbox-item" key={e.id}><strong>{e.title}</strong><p className="muted">{labels[e.kind]} · {e.occurred_on?dateLabel(e.occurred_on):"Datum unbekannt"}</p><p>{e.notes}</p>{e.person_id&&<p><a href={"/people/"+e.person_id}>{personName(e.person_id)}</a></p>}
      {e.event_id&&<p>Ereignis: {events.find(r=>r.id===e.event_id)?.title??e.event_id}</p>}{e.conversation_id&&<p>Gespräch: {conversations.find(r=>r.id===e.conversation_id)?.title??e.conversation_id}</p>}{e.memory_id&&<p>Erinnerung: {memories.find(r=>r.id===e.memory_id)?.title??e.memory_id}</p>}
      <button type="button" className="quiet" disabled={busy} onClick={()=>{if(window.confirm("Diesen Ortseintrag in den Papierkorb verschieben?"))void run(async()=>{await request("/api/places/"+selected.id+"/entries/"+e.id,{method:"DELETE"});await show(selected.id);await load();});}}>Eintrag löschen</button></div>)}
      <div className="commitment-actions"><button type="button" disabled={busy||entryOffset===0} onClick={()=>void run(()=>show(selected.id,Math.max(0,entryOffset-30)))}>Zurück</button><button type="button" disabled={busy||entries.length<30} onClick={()=>void run(()=>show(selected.id,entryOffset+30))}>Weitere Einträge</button><button type="button" onClick={()=>{setSelected(null);setAdding(false);setEditing(false);}}>Details schließen</button></div>
    </article>}
    </>}
  </section>;
}
