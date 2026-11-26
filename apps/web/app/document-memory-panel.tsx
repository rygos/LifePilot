"use client";
import {useCallback,useEffect,useState} from "react";

type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
type Doc={id:string;file_name:string;resource_type:string;resource_id:string;supported:boolean;indexed:boolean;digest:string|null;partial:boolean|null;total_pages:number|null};
type Page={page:number;text:string;method:string;truncated:boolean};
type Detail=Doc&{pages:Page[]};
type Hit=Doc&{page:number;snippet:string;method:string};
export function DocumentMemoryPanel({request}:{request:Request}){
  const [open,setOpen]=useState(false);
  const [rows,setRows]=useState<Doc[]>([]);
  const [offset,setOffset]=useState(0);
  const [query,setQuery]=useState("");
  const [searched,setSearched]=useState("");
  const [hits,setHits]=useState<Hit[]>([]);
  const [hitOffset,setHitOffset]=useState(0);
  const [detail,setDetail]=useState<Detail|null>(null);
  const [page,setPage]=useState(1);
  const [quote,setQuote]=useState("");
  const [ocr,setOcr]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const load=useCallback(async()=>setRows(await request<Doc[]>("/api/documents?limit=30&offset="+offset)),[request,offset]);
  useEffect(()=>{if(open)load().catch(e=>setError(String(e)));},[open,load]);
  async function run(fn:()=>Promise<void>){setBusy(true);setError("");setMessage("");try{await fn();}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  function selectPage(d:Detail,n:number){setDetail(d);setPage(n);setQuote(d.pages.find(p=>p.page===n)?.text??"");}
  function show(id:string,n=1){void run(async()=>selectPage(await request<Detail>("/api/documents/"+id),n));}
  function search(term:string,at=0){void run(async()=>{const result=await request<Hit[]>("/api/documents/search?"+new URLSearchParams({q:term,limit:"30",offset:String(at)}));setHits(result);setSearched(term);setHitOffset(at);});}
  const current=detail?.pages.find(p=>p.page===page);
  return <section className="card panel document-memory-panel">
    <div className="panel-head"><div><span className="eyebrow">DOKUMENTENGEDÄCHTNIS</span><h2>Dokumente &amp; OCR</h2></div><button type="button" className="quiet" onClick={()=>setOpen(v=>!v)}>{open?"Schließen":"Dokumente öffnen"}</button></div>
    <p className="muted">Vorhandene Anhänge lokal indexieren und durchsuchen. PDF, UTF-8-Text und Bilder; maximal zehn PDF-Seiten, davon bis zu drei per OCR. Originale bleiben unverändert.</p>
    {open&&<>
    {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    <form className="person-form" onSubmit={e=>{e.preventDefault();if(query.trim())search(query.trim());}}><label>Dokumenttext durchsuchen<input value={query} onChange={e=>setQuery(e.target.value)} maxLength={200} required/></label><button disabled={busy||!query.trim()}>Suchen</button></form>
    {searched&&<><h3>Suchtreffer für „{searched}“</h3>{hits.length===0?<p>Keine Treffer.</p>:hits.map(h=><div className="list-item" key={h.id+":"+h.page}><span>{h.file_name}<small>Seite {h.page} · {h.method}</small><small>{h.snippet}</small></span><button disabled={busy} type="button" onClick={()=>show(h.id,h.page)}>Öffnen</button></div>)}<div className="commitment-actions"><button disabled={busy||hitOffset===0} type="button" onClick={()=>search(searched,Math.max(0,hitOffset-30))}>Zurück</button><button disabled={busy||hits.length<30} type="button" onClick={()=>search(searched,hitOffset+30)}>Weitere Treffer</button></div></>}
    <h3>Vorhandene Anhänge</h3>{rows.length===0&&<p className="muted">Keine Anhänge in dieser Auswahl. Lade Dateien in einem Personen-, Projekt- oder Gedächtniseintrag hoch.</p>}{rows.map(d=><div className="list-item" key={d.id}><span>{d.file_name}<small>{d.resource_type} · {d.indexed?(d.partial?"Teilweise indexiert":"Indexiert"):d.supported?"Noch nicht indexiert":"Format nicht unterstützt"}</small></span><button type="button" disabled={busy||!d.supported} onClick={()=>show(d.id)}>Details</button></div>)}
    <div className="commitment-actions"><button type="button" disabled={busy||offset===0} onClick={()=>setOffset(v=>Math.max(0,v-30))}>Zurück</button><button type="button" disabled={busy||rows.length<30} onClick={()=>setOffset(v=>v+30)}>Weitere Anhänge</button></div>
    {detail&&<article className="inbox-item"><h3>{detail.file_name}</h3><p>{detail.resource_type} · {detail.resource_id}</p><label><input type="checkbox" checked={ocr} onChange={e=>setOcr(e.target.checked)}/> OCR für Bilder und PDF-Seiten ohne Text (Deutsch/Englisch)</label>
    <div className="commitment-actions"><button type="button" disabled={busy} onClick={()=>void run(async()=>{const d=await request<Detail>("/api/documents/"+detail.id+"/extract",{method:"POST",body:JSON.stringify({ocr})});selectPage(d,1);await load();setMessage("Textindex gespeichert.");})}>{detail.indexed?"Erneut extrahieren":"Lokal extrahieren"}</button>{detail.indexed&&<button className="quiet" type="button" disabled={busy} onClick={()=>{if(window.confirm("Nur den extrahierten Textindex entfernen? Bereits importierte Auszüge bleiben erhalten."))void run(async()=>{await request("/api/documents/"+detail.id+"/index",{method:"DELETE"});setDetail(null);await load();setHits([]);setSearched("");});}}>Textindex entfernen</button>}</div>
    {detail.partial&&<p className="muted">Nur ein Teil des Dokuments konnte indexiert werden. Leere oder gekürzte Seiten sind keine vollständige Quelle.</p>}
    {detail.pages.length>0&&<><label>Seite<select value={page} onChange={e=>selectPage(detail,Number(e.target.value))}>{detail.pages.map(p=><option key={p.page} value={p.page}>{p.page} / {detail.total_pages} · {p.method}{p.truncated?" (gekürzt)":""}</option>)}</select></label>
    <pre className="document-excerpt">{current?.text||"Kein Text gefunden."}</pre>
    <label>Wörtlicher Auszug zur KI-Prüfung<textarea value={quote} onChange={e=>setQuote(e.target.value)} maxLength={10000}/></label><p className="muted">Prüfe den Text am Original, insbesondere OCR-Fehler und personenbezogene Inhalte. Nur der ausgewählte Auszug wird nach Freigabe an die konfigurierte KI übergeben.</p><button type="button" disabled={busy||!quote.trim()||!current?.text.includes(quote)} onClick={()=>{if(window.confirm("Diesen Auszug ausdrücklich zur KI-Prüfung übernehmen?"))void run(async()=>{await request("/api/documents/"+detail.id+"/capture",{method:"POST",body:JSON.stringify({page,digest:detail.digest,quote})});setMessage("Auszug im Eingang gespeichert.");});}}>Zur KI-Prüfung übernehmen</button> <a href="/inbox">Zum Eingang</a></>}
    </article>}
    </>}
  </section>;
}
