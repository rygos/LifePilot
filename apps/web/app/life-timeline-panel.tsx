"use client";
import {useEffect,useState} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Person = {id:string;first_name:string;last_name:string};
type Kind = "conversation"|"event"|"memory"|"journal"|"life_event"|"call"|"fact"|"loan"|"place_entry";
type Item = {id:string;kind:Kind;resource_id:string;title:string;occurrence:string;day:string|null;occurred_at:string|null;date_precision:string;status:string|null;people:{id:string;name:string}[];people_truncated:boolean};
type Result = {items:Item[];next_offset:number|null;window_limited:boolean;timezone:string};
const labels:Record<Kind,string>={conversation:"Gespräch",event:"Ereignis",memory:"Erinnerung",journal:"Tagebuch",life_event:"Biografie",call:"Telefonat",fact:"Zeitlicher Fakt",loan:"Leihgabe",place_entry:"Ortseintrag"};
const icons:Record<Kind,string>={conversation:"💬",event:"📅",memory:"📝",journal:"📖",life_event:"◆",call:"☎",fact:"●",loan:"↔",place_entry:"⌖"};
const occurrence:Record<string,string>={start:"Beginn",end:"Ende der Gültigkeit (exklusiv)",lent:"Ausgeliehen",returned:"Zurückgegeben",unknown:"Gültigkeitszeitraum unbekannt"};
const precision:Record<string,string>={unknown:"Datum unbekannt",approximate:"Ungefährer Zeitpunkt",month:"Monatsangabe",year:"Jahresangabe",day:"Tag bekannt",exact:"Zeitpunkt bekannt"};
const dateLabel=(day:string)=>new Intl.DateTimeFormat("de-DE",{dateStyle:"long",timeZone:"UTC"}).format(new Date(day+"T00:00:00Z"));

export function LifeTimelinePanel({request,people,personId}:{request:Request;people:Person[];personId?:string}){
  const [subject,setSubject]=useState(personId??"");
  const [kind,setKind]=useState("");
  const [mode,setMode]=useState<"dated"|"undated">("dated");
  const [start,setStart]=useState("");
  const [end,setEnd]=useState("");
  const [unconfirmed,setUnconfirmed]=useState(false);
  const [offset,setOffset]=useState(0);
  const [data,setData]=useState<Result|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState("");
  const [refresh,setRefresh]=useState(0);
  useEffect(()=>{
    let live=true;
    setLoading(true);setError("");setData(null);
    if(mode==="dated"&&start&&end&&start>end){setError("Beginn darf nicht nach Ende liegen.");setLoading(false);return;}
    const q=new URLSearchParams({mode,offset:String(offset),limit:"30",include_unconfirmed:String(unconfirmed)});
    if(subject)q.set("person_id",subject);
    if(kind)q.append("kinds",kind);
    if(mode==="dated"){if(start)q.set("start",start);if(end)q.set("end",end);}
    request<Result>("/api/timeline?"+q).then(result=>{if(live)setData(result);}).catch(e=>{if(live)setError(e instanceof Error?e.message:String(e));}).finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[request,subject,kind,mode,start,end,unconfirmed,offset,refresh]);
  return <section className="card panel life-timeline-panel">
    <div className="panel-head"><div><span className="eyebrow">ERINNERUNGEN IM ZEITVERLAUF</span><h2>{personId?"Chronik der Person":"Lebenschronik"}</h2></div><button type="button" className="quiet" disabled={loading} onClick={()=>setRefresh(v=>v+1)}>Aktualisieren</button></div>
    <p className="muted">Gespeicherte Ereigniszeitpunkte und Gültigkeitsgrenzen, nicht das Erfassungsdatum. Kalendertermine können geplant sein. Die Chronik enthält auch ausdrücklich verknüpfte Ereignisse anderer Personen.</p>
    <div className="person-form">
      {!personId&&<label>Person<select value={subject} onChange={e=>{setSubject(e.target.value);setOffset(0);}}><option value="">Alle Personen</option>{people.map(p=><option value={p.id} key={p.id}>{p.first_name} {p.last_name}</option>)}</select></label>}
      <label>Inhaltstyp<select value={kind} onChange={e=>{setKind(e.target.value);setOffset(0);}}><option value="">Alle Typen</option>{Object.entries(labels).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label>Zeitliche Ansicht<select value={mode} onChange={e=>{setMode(e.target.value as "dated"|"undated");setOffset(0);}}><option value="dated">Datierte Einträge</option><option value="undated">Ohne konkretes Datum</option></select></label>
      {mode==="dated"&&<><label>Von (inklusive)<input type="date" value={start} onChange={e=>{setStart(e.target.value);setOffset(0);}}/></label><label>Bis (inklusive)<input type="date" value={end} onChange={e=>{setEnd(e.target.value);setOffset(0);}}/></label></>}
      <label><input type="checkbox" checked={unconfirmed} onChange={e=>{setUnconfirmed(e.target.checked);setOffset(0);}}/> Unbestätigte Fakten und Lebensereignisse einbeziehen</label>
    </div>
    {error&&<p className="error" role="alert">{error}</p>}
    {loading&&<p className="muted">Chronik wird geladen …</p>}
    {data&&<>
      <p className="muted">{data.items.length} Einträge · Zeitzone: {data.timezone}</p>
      {data.items.length===0?<p>Keine passenden Einträge.</p>:<div className="life-timeline-list">{data.items.map((item,i)=>{
        const newDay=i===0||data.items[i-1].day!==item.day;
        const clock=item.occurred_at?new Intl.DateTimeFormat("de-DE",{hour:"2-digit",minute:"2-digit",timeZone:data.timezone}).format(new Date(item.occurred_at)):null;
        const type=item.kind==="event"?(item.status==="appointment"?"Kalendertermin":item.status==="experience"?"Erlebnis":labels.event):item.kind==="place_entry"?({visit:"Besuch",meeting:"Begegnung",recommendation:"Empfehlung",memory:"Ortserinnerung",reference:"Ortsbezug"} as Record<string,string>)[item.status??""]??labels[item.kind]:labels[item.kind];
        return <div key={item.id}>{newDay&&<h3 className="timeline-day">{item.day?dateLabel(item.day):"Ohne konkretes Datum"}</h3>}<article className="timeline-entry"><span className="timeline-icon" aria-hidden="true">{icons[item.kind]}</span><div>
          <p className="muted">{type}{clock?" · "+clock:""}{occurrence[item.occurrence]?" · "+occurrence[item.occurrence]:""}{item.status==="proposed"?" · Unbestätigt":""}</p>
          <h4>{item.title}</h4>
          {!item.day&&<p className="muted">{precision[item.date_precision]??"Datum nicht genau bekannt"}</p>}
          {item.people.length>0&&<div className="timeline-people">{item.people.map(person=><a key={person.id} href={"/people/"+person.id}>{person.name}</a>)}{item.people_truncated&&<small>Weitere Beteiligte</small>}</div>}
          <details><summary>Quellverweis</summary><small>{item.kind} · {item.resource_id}</small></details>
        </div></article></div>;
      })}</div>}
      {data.window_limited&&<p className="muted">Weitere Einträge vorhanden. Bitte den Zeitraum oder Inhaltstyp eingrenzen.</p>}
      <div className="commitment-actions"><button type="button" className="quiet" disabled={offset===0} onClick={()=>setOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" className="quiet" disabled={data.next_offset===null} onClick={()=>{if(data.next_offset!==null)setOffset(data.next_offset);}}>Ältere / weitere Einträge</button></div>
    </>}
  </section>;
}
