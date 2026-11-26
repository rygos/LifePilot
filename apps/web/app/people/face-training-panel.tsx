"use client";
import {useCallback,useEffect,useState} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Person = {id:string;first_name:string;last_name:string;photo_key?:string|null;is_self?:boolean};
type Card = {id:string;person_id:string;name:string;nickname:string|null;context:string;active:boolean;available:boolean;photo_changed:boolean;level:number;review_count:number;revision:number;due_at:string;last_review_at:string|null;due:boolean};
const ratings=[["again","Nicht gewusst","10 Minuten"],["hard","Schwer","1 Tag"],["good","Gewusst","Nächste Stufe"],["easy","Sehr leicht","Zwei Stufen weiter"]];
const format=(value:string)=>new Date(value).toLocaleString("de-DE",{dateStyle:"medium",timeStyle:"short"});

function TrainingPhoto({card,api,token,onReady}:{card:Card;api:string;token:string;onReady:(ready:boolean)=>void}){
  const [url,setUrl]=useState("");
  const [error,setError]=useState(false);
  useEffect(()=>{
    let live=true;let objectUrl="";
    const controller=new AbortController();
    onReady(false);setUrl("");setError(false);
    fetch(api+"/api/training/faces/"+card.id+"/photo?revision="+card.revision,{headers:{Authorization:"Bearer "+token},cache:"no-store",signal:controller.signal})
      .then(r=>{if(!r.ok)throw new Error("Foto nicht verfügbar");return r.blob();})
      .then(blob=>{if(live){objectUrl=URL.createObjectURL(blob);setUrl(objectUrl);}})
      .catch(()=>{if(live)setError(true);});
    return()=>{live=false;controller.abort();if(objectUrl)URL.revokeObjectURL(objectUrl);};
  },[api,token,card.id,card.person_id,card.revision,onReady]);
  return error?<p className="error">Foto nicht verfügbar. Du kannst diese Karte überspringen.</p>:url?<img className="training-photo" src={url} alt="Kontaktfoto für die Namensabfrage" onLoad={()=>onReady(true)} onError={()=>{setError(true);onReady(false);}}/>:<p className="muted">Foto wird geladen …</p>;
}

export function FaceTrainingPanel({request,people,api,token}:{request:Request;people:Person[];api:string;token:string}){
  const [cards,setCards]=useState<Card[]>([]);
  const [personId,setPersonId]=useState("");
  const [open,setOpen]=useState(false);
  const [training,setTraining]=useState(false);
  const [skipped,setSkipped]=useState<string[]>([]);
  const [answer,setAnswer]=useState("");
  const [revealedKey,setRevealedKey]=useState("");
  const [readyKey,setReadyKey]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [loading,setLoading]=useState(false);
  const load=useCallback(async()=>setCards(await request<Card[]>("/api/training/faces?limit=500")),[request]);
  useEffect(()=>{if(!open)return;let live=true;setLoading(true);load().catch(e=>{if(live)setError(String(e));}).finally(()=>{if(live)setLoading(false);});return()=>{live=false;};},[open,load]);
  const due=cards.filter(c=>c.due);
  const current=training?due.find(c=>!skipped.includes(c.id)):undefined;
  const currentKey=current?current.id+":"+current.revision:"";
  const revealed=!!currentKey&&revealedKey===currentKey;
  const ready=!!currentKey&&readyKey===currentKey;
  const setReady=useCallback((value:boolean)=>setReadyKey(value?currentKey:""),[currentKey]);
  useEffect(()=>{setAnswer("");setRevealedKey("");setReadyKey("");},[currentKey]);
  async function run(action:()=>Promise<unknown>,notice:string){
    setBusy(true);setError("");setMessage("");
    try{await action();await load();setMessage(notice);}catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  function enroll(id:string,active:boolean){
    void run(()=>request("/api/training/faces/enroll",{method:"POST",body:JSON.stringify({person_id:id,active})}),active?"Lernkarte aktiviert.":"Lernkarte pausiert.");
  }
  const candidates=people.filter(p=>p.photo_key&&!p.is_self&&!cards.some(c=>c.person_id===p.id));
  return <section className="card panel face-training-panel">
    <div className="panel-head"><div><span className="eyebrow">FREIWILLIGES GEDÄCHTNISTRAINING</span><h2>Gesichter &amp; Namen</h2></div><button type="button" className="quiet" onClick={()=>{setOpen(v=>!v);setTraining(false);}}>{open?"Schließen":"Training öffnen"}</button></div>
    <p className="muted">Übe mit bewusst ausgewählten Kontaktfotos. Keine Gesichtserkennung, kein Vergleich von Bildern durch KI. Bewerte nach dem Aufdecken selbst, wie gut du dich erinnert hast.</p>
    {open&&<>
      {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
      <p>{due.length} fällig · {cards.filter(c=>c.active&&c.available).length} aktiv · {cards.reduce((n,c)=>n+c.review_count,0)} Bewertungen</p>
      <div className="commitment-actions"><button type="button" disabled={busy||loading||!due.length} onClick={()=>{setSkipped([]);setTraining(true);setAnswer("");setRevealedKey("");}}>Training starten</button><button type="button" className="quiet" disabled={busy||loading} onClick={()=>void run(load,"Aktualisiert.")}>Aktualisieren</button>{training&&<button type="button" className="quiet" onClick={()=>setTraining(false)}>Training beenden</button>}</div>
      {training&&(current?<div className="inbox-item" key={current.id+":"+current.revision}>
        <h3>Wie heißt diese Person?</h3>
        <TrainingPhoto card={current} api={api} token={token} onReady={setReady}/>
        {!revealed?<form className="person-form" onSubmit={e=>{e.preventDefault();if(ready)setRevealedKey(currentKey);}}><label>Deine Antwort (optional, wird nicht gespeichert)<input value={answer} onChange={e=>setAnswer(e.target.value)} autoComplete="off" maxLength={240}/></label><button disabled={!ready}>Namen aufdecken</button></form>:<>
          <h3>{current.name}</h3>{current.nickname&&<p>Spitzname: {current.nickname}</p>}{current.context&&<p>{current.context}</p>}{answer&&<p>Deine Antwort: {answer}</p>}
          <p>Wie leicht fiel dir die Erinnerung?</p><div className="training-ratings">{ratings.map(([rating,label,interval])=><button key={rating} type="button" disabled={busy} onClick={()=>void run(()=>request("/api/training/faces/"+current.id+"/review",{method:"POST",body:JSON.stringify({rating,revision:current.revision})}),"Bewertung gespeichert.")}>{label}<small>{interval}</small></button>)}</div>
          <a href={"/people/"+current.person_id}>Personenprofil ansehen</a></>}
        <button type="button" className="quiet" disabled={busy} onClick={()=>setSkipped(old=>[...old,current.id])}>Überspringen (ohne Bewertung)</button>
      </div>:<p>Keine weiteren fälligen Karten in dieser Runde. Übersprungene Karten bleiben fällig.</p>)}
      {!training&&<><h3>Lernkarten verwalten</h3><form className="person-form" onSubmit={e=>{e.preventDefault();if(personId){enroll(personId,true);setPersonId("");}}}><label>Person mit Kontaktfoto<select value={personId} onChange={e=>setPersonId(e.target.value)}><option value="">Auswählen</option>{candidates.map(p=><option value={p.id} key={p.id}>{p.first_name} {p.last_name}</option>)}</select></label><button disabled={busy||loading||!personId}>Zum Training hinzufügen</button></form>
      {cards.map(c=><div className="list-item" key={c.id}><span>{c.name}<small>{!c.available?(c.photo_changed?"Foto geändert – erneute Freigabe setzt Fortschritt zurück":"Kein Foto verfügbar"):!c.active?"Pausiert":c.due?"Fällig":"Nächste Wiederholung: "+format(c.due_at)} · Stufe {c.level} · {c.review_count} Bewertungen</small></span><div className="commitment-actions">{c.active&&<button type="button" className="quiet" disabled={busy} onClick={()=>enroll(c.person_id,false)}>Pausieren</button>}{(!c.active&&c.available||c.photo_changed)&&<button type="button" className="quiet" disabled={busy} onClick={()=>{if(!c.photo_changed||window.confirm("Neues Foto freigeben und Lernfortschritt zurücksetzen?"))enroll(c.person_id,true);}}>{c.photo_changed?"Neues Foto freigeben":"Fortsetzen"}</button>}</div></div>)}
      </>}
    </>}
  </section>;
}
