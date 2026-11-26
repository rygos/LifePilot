"use client";
import {useCallback,useEffect,useState,type FormEvent} from "react";

type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Person={id:string;first_name:string;last_name:string};
type Project={id:string;name:string};
type Memory={id:string;title:string};
type Doc={id:string;file_name:string};
type Alternative={title:string;pros:string;cons:string};
type Entry={id:string;title:string;decided_on:string;choice:string;rationale:string;alternatives:Alternative[];expected_outcome:string;review_on:string|null;status:"open"|"closed";revision:number;person_id:string|null;project_id:string|null;memory_id:string|null;attachment_id:string|null};
type Review={id:string;reviewed_on:string;assessment:string;outcome:string;lessons:string;next_review_on:string|null;closed:boolean;revision:number};
const assessments:Record<string,string>={better:"Besser als erwartet",as_expected:"Wie erwartet",worse:"Schlechter als erwartet",unclear:"Noch unklar"};
const dateLabel=(d:string)=>new Date(d+"T12:00:00Z").toLocaleDateString("de-DE",{timeZone:"UTC"});
const today=()=>{const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-");};
function DecisionForm({people,projects,memories,docs,request,busy,onSave}:{people:Person[];projects:Project[];memories:Memory[];docs:Doc[];request:Request;busy:boolean;onSave:(data:object)=>Promise<void>}){
  const [alternatives,setAlternatives]=useState<Alternative[]>([]);
  const [docId,setDocId]=useState("");
  const [docOffset,setDocOffset]=useState(0);
  const [docPage,setDocPage]=useState(docs);
  const [docError,setDocError]=useState("");
  function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const f=new FormData(e.currentTarget);
    void onSave({title:f.get("title"),decided_on:f.get("decided_on"),choice:f.get("choice"),rationale:f.get("rationale"),expected_outcome:f.get("expected_outcome"),review_on:f.get("review_on")||null,person_id:f.get("person_id")||null,project_id:f.get("project_id")||null,memory_id:f.get("memory_id")||null,attachment_id:docId||null,alternatives});
  }
  async function loadDocs(offset:number){try{setDocPage(await request<Doc[]>("/api/documents?limit=50&offset="+offset));setDocOffset(offset);setDocError("");}catch(e){setDocError(String(e));}}
  return <form className="person-form" onSubmit={submit}>
    <label>Titel<input name="title" required maxLength={240}/></label><label>Entschieden am<input name="decided_on" type="date" defaultValue={today()} required/></label>
    <label>Was hast du entschieden?<textarea name="choice" required maxLength={5000}/></label>
    <label>Warum?<textarea name="rationale" required maxLength={10000}/></label>
    <label>Was erwartest du als Ergebnis?<textarea name="expected_outcome" maxLength={5000}/></label>
    <h3>Betrachtete Alternativen</h3>{alternatives.map((a,i)=><fieldset key={i}><legend>Alternative {i+1}</legend>{(["title","pros","cons"] as const).map(k=><label key={k}>{k==="title"?"Bezeichnung":k==="pros"?"Vorteile":"Nachteile"}<textarea required={k==="title"} maxLength={k==="title"?240:2000} value={a[k]} onChange={e=>setAlternatives(old=>old.map((v,j)=>j===i?{...v,[k]:e.target.value}:v))}/></label>)}<button type="button" className="quiet" onClick={()=>setAlternatives(old=>old.filter((_,j)=>j!==i))}>Entfernen</button></fieldset>)}
    <button type="button" className="quiet" disabled={alternatives.length>=10} onClick={()=>setAlternatives(old=>[...old,{title:"",pros:"",cons:""}])}>Alternative hinzufügen</button>
    <label>Wiedervorlage (optional)<input name="review_on" type="date"/></label>
    <details><summary>Gedächtnisinhalte verknüpfen</summary>
    <label>Person<select name="person_id"><option value="">Keine</option>{people.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>
    <label>Projekt<select name="project_id"><option value="">Keines</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <label>Erinnerung<select name="memory_id"><option value="">Keine</option>{memories.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}</select></label>
    <label>Dokument<select value={docId} onChange={e=>setDocId(e.target.value)}><option value="">Keines</option>{docId&&!docPage.some(d=>d.id===docId)&&<option value={docId}>Ausgewähltes Dokument ({docId})</option>}{docPage.map(d=><option key={d.id} value={d.id}>{d.file_name}</option>)}</select></label>
    {docError&&<p className="error">{docError}</p>}<div className="commitment-actions"><button type="button" disabled={docOffset===0} onClick={()=>void loadDocs(Math.max(0,docOffset-50))}>Vorherige Dokumente</button><button type="button" disabled={docPage.length<50} onClick={()=>void loadDocs(docOffset+50)}>Weitere Dokumente</button></div>
    </details><p className="muted">Die ursprüngliche Begründung bleibt nach dem Speichern unverändert. Spätere Erkenntnisse werden als Bewertungen ergänzt.</p><button disabled={busy}>Entscheidung speichern</button>
  </form>;
}
function ReviewForm({entry,busy,onSave}:{entry:Entry;busy:boolean;onSave:(data:object)=>Promise<void>}){
  const [closed,setClosed]=useState(false);
  return <form className="person-form" onSubmit={e=>{e.preventDefault();const f=new FormData(e.currentTarget);void onSave({revision:entry.revision,assessment:f.get("assessment"),outcome:f.get("outcome"),lessons:f.get("lessons"),next_review_on:closed?null:f.get("next_review_on")||null,closed});}}>
    <label>Bewertung<select name="assessment" required defaultValue="unclear">{Object.entries(assessments).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
    <label>Was ist tatsächlich passiert?<textarea name="outcome" required maxLength={10000}/></label>
    <label>Was hast du daraus gelernt?<textarea name="lessons" maxLength={10000}/></label>
    <label><input type="checkbox" checked={closed} onChange={e=>setClosed(e.target.checked)}/> Entscheidung abschließen</label>
    {!closed&&<label>Nächste Wiedervorlage (optional)<input name="next_review_on" type="date"/></label>}
    <button disabled={busy}>Bewertung speichern</button>
  </form>;
}
export function DecisionJournalPanel({request,people,projects,memories,onChange}:{request:Request;people:Person[];projects:Project[];memories:Memory[];onChange:()=>Promise<void>}){
  const [rows,setRows]=useState<Entry[]>([]);
  const [docs,setDocs]=useState<Doc[]>([]);
  const [filter,setFilter]=useState("all");
  const [person,setPerson]=useState("");
  const [project,setProject]=useState("");
  const [offset,setOffset]=useState(0);
  const [creating,setCreating]=useState(false);
  const [selected,setSelected]=useState<Entry|null>(null);
  const [reviews,setReviews]=useState<Review[]>([]);
  const [reviewOffset,setReviewOffset]=useState(0);
  const [reviewing,setReviewing]=useState(false);
  const [busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const query=useCallback(()=>{const q=new URLSearchParams({limit:"30",offset:String(offset)});if(filter==="due")q.set("due_only","true");else if(filter!=="all")q.set("status",filter);if(person)q.set("person_id",person);if(project)q.set("project_id",project);return q.toString();},[filter,offset,person,project]);
  const load=useCallback(async()=>setRows(await request<Entry[]>("/api/decisions?"+query())),[query,request]);
  useEffect(()=>{let live=true;setLoading(true);setError("");request<Entry[]>("/api/decisions?"+query()).then(v=>{if(live)setRows(v);}).catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[request,query]);
  async function run(fn:()=>Promise<void>){setBusy(true);setError("");setNotice("");try{await fn();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  async function show(id:string,at=0){const [entry,history]=await Promise.all([request<Entry>("/api/decisions/"+id),request<Review[]>("/api/decisions/"+id+"/reviews?limit=30&offset="+at)]);setSelected(entry);setReviews(history);setReviewOffset(at);}
  async function create(data:object){await run(async()=>{const entry=await request<Entry>("/api/decisions",{method:"POST",body:JSON.stringify(data)});setCreating(false);setFilter("all");setOffset(0);setPerson("");setProject("");await show(entry.id);await load();setNotice("Entscheidung gespeichert.");await onChange();});}
  async function review(data:object){if(!selected)return;await run(async()=>{await request("/api/decisions/"+selected.id+"/reviews",{method:"POST",body:JSON.stringify(data)});setReviewing(false);await show(selected.id);await load();setNotice("Bewertung gespeichert.");await onChange();});}
  return <section id="decision-journal" className="card panel decision-journal-panel">
    <div className="panel-head"><div><span className="eyebrow">ENTSCHEIDUNGEN &amp; ERKENNTNISSE</span><h2>Entscheidungsjournal</h2></div><button type="button" disabled={busy} onClick={()=>{if(creating)setCreating(false);else void run(async()=>{setDocs(await request<Doc[]>("/api/documents?limit=50"));setCreating(true);});}}>{creating?"Schließen":"Entscheidung festhalten"}</button></div>
    <p className="muted">Halte fest, warum du eine Entscheidung getroffen hast. Vergleiche deine Erwartungen später mit dem tatsächlichen Ergebnis.</p>
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {creating&&<DecisionForm people={people} projects={projects} memories={memories} docs={docs} request={request} busy={busy} onSave={create}/>}
    <div className="person-form"><label>Ansicht<select value={filter} onChange={e=>{setFilter(e.target.value);setOffset(0);}}><option value="all">Alle</option><option value="due">Fällige Wiedervorlagen</option><option value="open">Offen</option><option value="closed">Abgeschlossen</option></select></label>
    <label>Person<select value={person} onChange={e=>{setPerson(e.target.value);setOffset(0);}}><option value="">Alle</option>{people.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>
    <label>Projekt<select value={project} onChange={e=>{setProject(e.target.value);setOffset(0);}}><option value="">Alle</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div>
    {loading?<p>Lade Entscheidungen …</p>:rows.length===0?<p>Keine passenden Entscheidungen.</p>:rows.map(row=><div className="list-item" key={row.id}><span>{row.title}<small>{dateLabel(row.decided_on)} · {row.status==="closed"?"Abgeschlossen":"Offen"}{row.review_on?" · Wiedervorlage "+dateLabel(row.review_on):""}</small></span><button type="button" className="quiet" disabled={busy} onClick={()=>void run(async()=>{setReviewing(false);await show(row.id);})}>Öffnen</button></div>)}
    <div className="commitment-actions"><button type="button" disabled={busy||loading||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={busy||loading||rows.length<30} onClick={()=>setOffset(v=>v+30)}>Weiter</button></div>
    {selected&&<article className="inbox-item decision-detail"><h3>{selected.title}</h3><p>{dateLabel(selected.decided_on)} · {selected.status==="open"?"Offen":"Abgeschlossen"}</p>
    <h4>Entscheidung</h4><p>{selected.choice}</p><h4>Ursprüngliche Begründung</h4><p>{selected.rationale}</p><h4>Erwartetes Ergebnis</h4><p>{selected.expected_outcome||"Nicht angegeben"}</p>
    {selected.alternatives.length>0&&<><h4>Alternativen</h4>{selected.alternatives.map((a,i)=><div className="inbox-item" key={i}><strong>{a.title}</strong><p>Vorteile: {a.pros||"–"}</p><p>Nachteile: {a.cons||"–"}</p></div>)}</>}
    <details><summary>Verknüpfungen</summary>{selected.person_id&&<p><a href={"/people/"+selected.person_id}>Person: {people.find(p=>p.id===selected.person_id)?.first_name??selected.person_id} {people.find(p=>p.id===selected.person_id)?.last_name}</a></p>}{selected.project_id&&<p>Projekt: {projects.find(p=>p.id===selected.project_id)?.name??selected.project_id}</p>}{selected.memory_id&&<p>Erinnerung: {memories.find(m=>m.id===selected.memory_id)?.title??selected.memory_id}</p>}{selected.attachment_id&&<p>Dokument-ID: {selected.attachment_id}</p>}</details>
    <p>Wiedervorlage: {selected.review_on?dateLabel(selected.review_on):"Keine"}</p><button type="button" disabled={busy} onClick={()=>setReviewing(v=>!v)}>{reviewing?"Bewertung schließen":"Ergebnis bewerten"}</button>
    {reviewing&&<ReviewForm key={selected.id+":"+selected.revision} entry={selected} busy={busy} onSave={review}/>}
    <h4>Bewertungsverlauf</h4>{reviews.length===0?<p>Noch keine Bewertungen.</p>:reviews.map(r=><div className="inbox-item" key={r.id}><strong>{dateLabel(r.reviewed_on)} · {assessments[r.assessment]}</strong><p>{r.outcome}</p>{r.lessons&&<p>Erkenntnisse: {r.lessons}</p>}<small>{r.closed?"Abgeschlossen":r.next_review_on?"Wiedervorlage "+dateLabel(r.next_review_on):"Keine Wiedervorlage"}</small></div>)}
    <div className="commitment-actions"><button type="button" disabled={busy||reviewOffset===0} onClick={()=>void run(()=>show(selected.id,Math.max(0,reviewOffset-30)))}>Zurück</button><button type="button" disabled={busy||reviews.length<30} onClick={()=>void run(()=>show(selected.id,reviewOffset+30))}>Weitere Bewertungen</button><button type="button" className="quiet" onClick={()=>{setSelected(null);setReviewing(false);}}>Details schließen</button></div></article>}
  </section>;
}
