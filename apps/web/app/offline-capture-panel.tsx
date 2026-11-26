"use client";
import {useCallback,useEffect,useRef,useState,type FormEvent} from "react";
import {enqueueCapture,pendingCaptures,readDraft,writeDraft,removeCapture,syncCaptures,type LocalCapture} from "../public/offline-store.mjs";
import {VoiceTextarea} from "./voice-textarea";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
const events=["storage","lifepilot-offline-change"];
export function OfflineCaptureForm({api,owner,request,onQueued,id,autoFocus=false}:{api:string;owner:string;request:Request;onQueued?:()=>void;id:string;autoFocus?:boolean}) {
  const [text,setText]=useState("");
  const [error,setError]=useState("");
  const [ready,setReady]=useState(false);
  const unsaved=useRef(false);
  useEffect(()=>{
    function load(){try{if(!unsaved.current)setText(readDraft(api,owner));setReady(true);}catch(e){setError(String(e));}}
    load();events.forEach(e=>window.addEventListener(e,load));
    return()=>events.forEach(e=>window.removeEventListener(e,load));
  },[api,owner]);
  function change(value:string){
    setText(value);
    try{unsaved.current=false;writeDraft(api,owner,value);setError("");}catch(e){unsaved.current=true;setError("Entwurf nicht lokal gespeichert: "+String(e));}
  }
  function submit(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    try{
      enqueueCapture(api,owner,text);
      setText("");unsaved.current=false;
      try{writeDraft(api,owner,"");}catch{setError("Erfassung gespeichert, alter Entwurf konnte nicht entfernt werden.");return;}
      e.currentTarget.reset();setError("");onQueued?.();
    }catch(e){setError(String(e));}
  }
  return <form onSubmit={submit}>
    <label htmlFor={id}>Gedanke oder Gespräch</label>
    <VoiceTextarea request={request} id={id} name="content" value={text} onChange={e=>change(e.target.value)} onVoiceAppend={change} maxLength={20000} autoFocus={autoFocus} required disabled={!ready} placeholder="Schreib einfach los. Ein Gespräch, eine Idee, etwas zum Erinnern …"/>
    <p className="muted">Entwürfe und noch nicht übertragene Texte bleiben unverschlüsselt in diesem Browser. Nur auf vertrauenswürdigen Geräten nutzen.</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <button disabled={!ready||!text.trim()}>Gedanken speichern</button>
  </form>;
}
export function OfflineCaptureQueue({api,owner,request,onSynced}:{api:string;owner:string;request:Request;onSynced:()=>Promise<void>}) {
  const [rows,setRows]=useState<LocalCapture[]>([]);
  const [busy,setBusy]=useState(false);
  const [online,setOnline]=useState(true);
  const [error,setError]=useState("");
  const [status,setStatus]=useState("");
  const running=useRef(false);
  const controller=useRef<AbortController|null>(null);
  const onSyncedRef=useRef(onSynced);
  useEffect(()=>{onSyncedRef.current=onSynced;},[onSynced]);
  const load=useCallback(()=>{try{setRows(pendingCaptures(api,owner));}catch(e){setError(String(e));}},[api,owner]);
  const flush=useCallback(async()=>{
    setOnline(navigator.onLine);
    if(!navigator.onLine||running.current)return;
    try{if(!pendingCaptures(api,owner).length)return;}catch(e){setError(String(e));return;}
    running.current=true;setBusy(true);setError("");
    const ctrl=new AbortController();controller.current=ctrl;
    try{
      const sent=await syncCaptures(api,owner,async(data,signal)=>{
        const timeout=new AbortController();const cancel=()=>timeout.abort();
        signal?.addEventListener("abort",cancel,{once:true});if(signal?.aborted)cancel();
        const timer=window.setTimeout(cancel,30000);
        try{return await request<{id:string;original_text:string}>("/api/captures",{method:"POST",body:JSON.stringify(data),signal:timeout.signal});}
        finally{window.clearTimeout(timer);signal?.removeEventListener("abort",cancel);}
      },ctrl.signal);
      if(!ctrl.signal.aborted&&sent){setStatus(sent===1?"Originaltext gespeichert.":sent+" Erfassungen gespeichert.");await onSyncedRef.current();}
    }catch(e){if(!ctrl.signal.aborted)setError("Synchronisierung ausstehend: "+String(e));}
    finally{if(controller.current===ctrl){controller.current=null;running.current=false;setBusy(false);load();}}
  },[api,owner,request,load]);
  useEffect(()=>{
    load();void flush();
    const changed=()=>{load();void flush();};
    const visible=()=>{if(document.visibilityState==="visible")changed();};
    const offline=()=>setOnline(false);
    events.forEach(e=>window.addEventListener(e,changed));
    window.addEventListener("online",changed);window.addEventListener("offline",offline);
    document.addEventListener("visibilitychange",visible);
    const timer=window.setInterval(visible,30000);
    return()=>{controller.current?.abort();controller.current=null;running.current=false;events.forEach(e=>window.removeEventListener(e,changed));window.removeEventListener("online",changed);window.removeEventListener("offline",offline);document.removeEventListener("visibilitychange",visible);window.clearInterval(timer);};
  },[load,flush]);
  if(!rows.length&&!error&&!status&&online)return null;
  return <section className="notice offline-queue">
    <div><strong>{online?"Lokale Schnellerfassung":"Offline – Eingaben bleiben auf diesem Gerät"}</strong><p>{rows.length} ausstehende Erfassung(en){busy?" · Übertragung läuft …":""}</p></div>
    {error&&<p className="error" role="alert">{error}</p>}{status&&<p role="status">{status}</p>}
    {rows.map(row=><details key={row.id}><summary>{row.text.slice(0,80)} · {new Date(row.captured_at).toLocaleString("de-DE")}</summary><p style={{whiteSpace:"pre-wrap"}}>{row.text}</p><button type="button" className="quiet" disabled={busy} onClick={()=>{if(window.confirm("Lokal verwerfen? Die Erfassung könnte bereits auf dem Server angekommen sein.")){try{removeCapture(api,owner,row.id);load();}catch(e){setError(String(e));}}}}>Lokal verwerfen</button></details>)}
    {rows.length>0&&<button type="button" disabled={busy||!online} onClick={()=>void flush()}>Jetzt synchronisieren</button>}
    <a href="/offline.html">Offline-Ansicht</a>
  </section>;
}
