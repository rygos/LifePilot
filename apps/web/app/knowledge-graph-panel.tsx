"use client";
import {useEffect,useMemo,useState} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Person = {id:string;first_name:string;last_name:string;is_self?:boolean};
type Kind = "person"|"organization"|"conversation"|"project"|"event"|"memory"|"commitment"|"fact"|"task"|"place"|"place_entry";
type Node = {id:string;kind:Kind;resource_id:string;label:string;status:string|null};
type Edge = {id:string;source:string;target:string;label:string;resource_type:string;resource_id:string;valid_from:string|null;valid_until:string|null;confirmed:boolean|null};
type Graph = {root:string;nodes:Node[];edges:Edge[];truncated:boolean};
const types:Record<Kind,string>={person:"Personen",organization:"Organisationen",conversation:"Gespräche",project:"Projekte",event:"Ereignisse",memory:"Erinnerungen",commitment:"Verpflichtungen",fact:"Zeitliche Fakten",task:"Aufgaben",place:"Orte",place_entry:"Ortseinträge"};
const colors:Record<Kind,string>={person:"#2563eb",organization:"#7c3aed",conversation:"#0f766e",project:"#b45309",event:"#be185d",memory:"#475569",commitment:"#a16207",fact:"#0369a1",task:"#15803d",place:"#a21caf",place_entry:"#0e7490"};
const allKinds=Object.keys(types) as Kind[];
const short=(label:string,n=18)=>label.length>n?label.slice(0,n-1)+"…":label;

function layout(graph:Graph){
  const distances=new Map<string,number>([[graph.root,0]]);
  const adjacency=new Map<string,string[]>();
  for(const edge of graph.edges){
    adjacency.set(edge.source,[...(adjacency.get(edge.source)??[]),edge.target]);
    adjacency.set(edge.target,[...(adjacency.get(edge.target)??[]),edge.source]);
  }
  const queue=[graph.root];
  for(let i=0;i<queue.length;i++){
    const id=queue[i];
    for(const next of adjacency.get(id)??[])if(!distances.has(next)){distances.set(next,(distances.get(id)??0)+1);queue.push(next);}
  }
  const rings=[graph.nodes.filter(n=>distances.get(n.id)===1),graph.nodes.filter(n=>(distances.get(n.id)??2)>=2)];
  const outer=Math.max(250,rings[1].length*29/(2*Math.PI),rings[0].length*42/(2*Math.PI)+115);
  const inner=Math.max(110,rings[0].length*42/(2*Math.PI));
  const size=2*(outer+100);
  const positions=new Map<string,{x:number;y:number}>([[graph.root,{x:size/2,y:size/2}]]);
  rings.forEach((ring,i)=>ring.forEach((node,j)=>{
    const angle=2*Math.PI*j/Math.max(1,ring.length)-Math.PI/2;
    const radius=i===0?inner:outer;
    positions.set(node.id,{x:size/2+radius*Math.cos(angle),y:size/2+radius*Math.sin(angle)});
  }));
  return {size,positions};
}

export function KnowledgeGraphPanel({request,people,personId}:{request:Request;people:Person[];personId?:string}){
  const [root,setRoot]=useState<{kind:Kind;id:string}|null>(null);
  const [depth,setDepth]=useState(1);
  const [limit,setLimit]=useState(30);
  const [kinds,setKinds]=useState<Kind[]>(allKinds);
  const [unconfirmed,setUnconfirmed]=useState(false);
  const [data,setData]=useState<Graph|null>(null);
  const [selected,setSelected]=useState("");
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [refresh,setRefresh]=useState(0);
  const [zoom,setZoom]=useState(100);
  useEffect(()=>{
    if(!root){
      const person=people.find(p=>p.id===personId)??people.find(p=>p.is_self)??people[0];
      if(person)setRoot({kind:"person",id:person.id});
    }
  },[people,personId,root]);
  useEffect(()=>{
    if(!root)return;
    let live=true;
    setLoading(true);setError("");setData(null);setSelected("");
    const q=new URLSearchParams({root_kind:root.kind,root_id:root.id,depth:String(depth),limit:String(limit),include_unconfirmed:String(unconfirmed)});
    for(const kind of new Set([...kinds,root.kind]))q.append("kinds",kind);
    request<Graph>("/api/graph?"+q).then(result=>{if(live){setData(result);setSelected(result.root);}}).catch(e=>{if(live)setError(e instanceof Error?e.message:String(e));}).finally(()=>{if(live)setLoading(false);});
    return()=>{live=false;};
  },[request,root,depth,limit,kinds,unconfirmed,refresh]);
  const geometry=useMemo(()=>data?layout(data):null,[data]);
  const current=data?.nodes.find(n=>n.id===selected);
  const links=data?.edges.filter(e=>e.source===selected||e.target===selected)??[];
  const byId=useMemo(()=>new Map(data?.nodes.map(n=>[n.id,n])??[]),[data]);
  return <section className="card panel knowledge-graph-panel">
    <div className="panel-head"><div><span className="eyebrow">ZUSAMMENHÄNGE</span><h2>Wissensgraph</h2></div><button type="button" className="quiet" disabled={!root||loading} onClick={()=>setRefresh(v=>v+1)}>Aktualisieren</button></div>
    <p className="muted">Nur gespeicherte Verknüpfungen. Historische Beziehungen können enthalten sein; gestrichelte Linien kennzeichnen unbestätigte Angaben. Wähle einen Knoten, um seine Verbindungen zu untersuchen.</p>
    <div className="person-form">
      <label>Person als Ausgangspunkt<select value={root?.kind==="person"?root.id:""} onChange={e=>{if(e.target.value)setRoot({kind:"person",id:e.target.value});}}><option value="">Person auswählen</option>{people.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}{p.is_self?" (Ich)":""}</option>)}</select></label>
      <label>Umgebung<select value={depth} onChange={e=>setDepth(Number(e.target.value))}><option value={1}>Direkte Verbindungen</option><option value={2}>Zwei Verbindungsschritte</option></select></label>
      <label>Maximale Knoten<select value={limit} onChange={e=>setLimit(Number(e.target.value))}>{[30,60,100].map(n=><option key={n} value={n}>{n}</option>)}</select></label>
      <label><input type="checkbox" checked={unconfirmed} onChange={e=>setUnconfirmed(e.target.checked)}/> Unbestätigte Angaben einbeziehen</label>
    </div>
    <details><summary>Inhaltstypen filtern</summary><div className="graph-filters">{allKinds.map(kind=><label key={kind}><input type="checkbox" checked={kinds.includes(kind)||root?.kind===kind} disabled={root?.kind===kind} onChange={e=>setKinds(old=>e.target.checked?[...old,kind]:old.filter(k=>k!==kind))}/>{types[kind]}</label>)}</div></details>
    {error&&<p className="error" role="alert">{error}</p>}
    {loading&&<p className="muted">Verbindungen werden geladen …</p>}
    {!root&&!loading&&<p className="muted">Lege zuerst eine Person an.</p>}
    {data&&geometry&&<>
      <p>{data.nodes.length} Knoten · {data.edges.length} Verbindungen{data.truncated?" · Begrenzte Auswahl – Filter ändern oder einen kleineren Ausschnitt fokussieren.":""}</p>
      <label>Zoom: {zoom}%<input type="range" min="75" max="175" step="25" value={zoom} onChange={e=>setZoom(Number(e.target.value))}/></label>
      <div className="graph-scroll"><svg role="img" aria-label="Wissensgraph; alle Knoten und Verbindungen sind auch als Text auswählbar" viewBox={`0 0 ${geometry.size} ${geometry.size}`} style={{width:`${zoom}%`,minWidth:geometry.size*0.75}}>
        {data.edges.map(e=>{const a=geometry.positions.get(e.source),b=geometry.positions.get(e.target);return a&&b?<line key={e.id} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="currentColor" strokeOpacity={e.source===selected||e.target===selected?0.8:0.22} strokeWidth={e.source===selected||e.target===selected?2:1} strokeDasharray={e.confirmed===false?"5 4":undefined}><title>{e.label}</title></line>:null;})}
        {data.nodes.map(n=>{const pos=geometry.positions.get(n.id);if(!pos)return null;return <g key={n.id} role="button" tabIndex={0} aria-label={n.label} aria-pressed={selected===n.id} onClick={()=>setSelected(n.id)} onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();setSelected(n.id);}}} style={{cursor:"pointer"}}><title>{n.label} ({types[n.kind]})</title><circle cx={pos.x} cy={pos.y} r={n.id===data.root?25:15} fill={colors[n.kind]} fillOpacity={selected===n.id?1:0.75} stroke={selected===n.id?"currentColor":colors[n.kind]} strokeWidth={selected===n.id?3:1}/><text x={pos.x} y={pos.y+(n.id===data.root?40:29)} fill="currentColor" textAnchor="middle" fontSize="11">{short(n.label)}</text></g>;})}
      </svg></div>
      <div className="graph-legend">{allKinds.filter(k=>data.nodes.some(n=>n.kind===k)).map(k=><span key={k}><i style={{background:colors[k]}}/>{types[k]}</span>)}</div>
      <label>Knoten auswählen<select value={selected} onChange={e=>setSelected(e.target.value)}>{data.nodes.map(n=><option key={n.id} value={n.id}>{n.label} · {types[n.kind]}</option>)}</select></label>
      {current&&<div className="inbox-item"><h3>{current.label}</h3><p className="muted">{types[current.kind]}{current.status?" · "+current.status:""}</p><div className="commitment-actions"><button type="button" disabled={current.id===data.root} onClick={()=>setRoot({kind:current.kind,id:current.resource_id})}>Als Mittelpunkt öffnen</button>{current.kind==="person"&&<a href={"/people/"+current.resource_id}>Personenprofil öffnen</a>}</div>
      <h4>Verknüpfungen in diesem Ausschnitt</h4>{links.length===0?<p className="muted">Keine sichtbaren Verbindungen.</p>:links.map(e=>{const outbound=e.source===current.id;const other=byId.get(outbound?e.target:e.source);return <div className="list-item" key={e.id}><span>{outbound?"→":"←"} {e.label}<small>{e.confirmed===false?"Unbestätigt · ":""}{e.valid_from||e.valid_until?(e.valid_from??"Beginn unbekannt")+" – "+(e.valid_until??"Ende offen/unbekannt"):""}</small></span>{other&&<button type="button" className="quiet" onClick={()=>setSelected(other.id)}>{other.label}</button>}</div>;})}</div>}
    </>}
  </section>;
}
