"use client";

import { useEffect, useRef, useState, type TextareaHTMLAttributes } from "react";

type Request = <T>(path: string, init?: RequestInit) => Promise<T>;
type VoiceStatus = {enabled: boolean; max_audio_bytes: number};
const MAX_RECORDING_SECONDS = 300;
const TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4", "audio/webm"];
const FILE_TYPES: Record<string,string> = {webm:"audio/webm",ogg:"audio/ogg",oga:"audio/ogg",m4a:"audio/mp4",mp4:"audio/mp4",mp3:"audio/mpeg",wav:"audio/wav",flac:"audio/flac"};

export function VoiceTextarea({request, onVoiceAppend, ...props}: TextareaHTMLAttributes<HTMLTextAreaElement> & {request: Request; onVoiceAppend?: (text:string)=>void}) {
  const target = useRef<HTMLTextAreaElement>(null);
  const [open,setOpen] = useState(false);
  const [status,setStatus] = useState<VoiceStatus|null>(null);
  const [audio,setAudio] = useState<Blob|null>(null);
  const [preview,setPreview] = useState("");
  const [audioUrl,setAudioUrl] = useState("");
  const [error,setError] = useState("");
  const [recording,setRecording] = useState(false);
  const [starting,setStarting] = useState(false);
  const [busy,setBusy] = useState(false);
  const [elapsed,setElapsed] = useState(0);
  const recorder = useRef<MediaRecorder|null>(null);
  const stream = useRef<MediaStream|null>(null);
  const timer = useRef<number|null>(null);
  const generation = useRef(0);
  const abort = useRef<AbortController|null>(null);
  const live = useRef(true);
  const captureStart = useRef(0);
  const clearTimer = () => {if(timer.current!==null)window.clearInterval(timer.current);timer.current=null;};
  const stopTracks = () => {stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;};
  function cleanup() {
    generation.current++;
    abort.current?.abort();abort.current=null;
    const active=recorder.current;recorder.current=null;
    if(active){active.onstop=null;active.ondataavailable=null;active.onerror=null;if(active.state!=="inactive")active.stop();}
    clearTimer();stopTracks();
  }
  useEffect(()=>{live.current=true;const form=target.current?.form;const reset=()=>{cleanup();setOpen(false);setRecording(false);setStarting(false);setBusy(false);setAudio(null);setPreview("");setError("");};form?.addEventListener("reset",reset);return()=>{live.current=false;form?.removeEventListener("reset",reset);cleanup();};},[]);
  useEffect(()=>{
    if(!audio){setAudioUrl("");return;}
    const url=URL.createObjectURL(audio);setAudioUrl(url);
    return()=>URL.revokeObjectURL(url);
  },[audio]);
  async function show() {
    if(open){cleanup();setOpen(false);setRecording(false);setStarting(false);setBusy(false);setAudio(null);setPreview("");setError("");return;}
    setOpen(true);setError("");setStatus(null);
    const version=++generation.current;
    try {const value=await request<VoiceStatus>("/api/voice/status");if(live.current&&version===generation.current)setStatus(value);}
    catch(e){if(live.current&&version===generation.current)setError(e instanceof Error?e.message:String(e));}
  }
  async function start() {
    if(!status?.enabled||starting||recording||busy)return;
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==="undefined"){setError("Mikrofonaufnahme benötigt einen unterstützten Browser und HTTPS oder localhost. Du kannst eine Audiodatei auswählen.");return;}
    setStarting(true);setError("");
    const version=++generation.current;
    try {
      const input=await navigator.mediaDevices.getUserMedia({audio:true});
      if(!live.current||version!==generation.current){input.getTracks().forEach(t=>t.stop());return;}
      stream.current=input;
      const type=TYPES.find(t=>MediaRecorder.isTypeSupported(t));
      const active=type?new MediaRecorder(input,{mimeType:type}):new MediaRecorder(input);
      recorder.current=active;
      const chunks:Blob[]=[];let size=0;let rejected=false;
      active.ondataavailable=e=>{
        if(!live.current||version!==generation.current||rejected||!e.data.size)return;
        size+=e.data.size;
        if(size>status.max_audio_bytes){rejected=true;chunks.length=0;setError("Aufnahme ist zu groß. Bitte kürzer aufnehmen.");if(active.state!=="inactive")active.stop();return;}
        chunks.push(e.data);
      };
      active.onerror=()=>{rejected=true;chunks.length=0;if(live.current&&version===generation.current)setError("Mikrofonaufnahme fehlgeschlagen.");if(active.state!=="inactive")active.stop();};
      active.onstop=()=>{
        if(!live.current||version!==generation.current)return;
        clearTimer();stopTracks();recorder.current=null;
        setRecording(false);setStarting(false);
        if(!rejected&&chunks.length)setAudio(new Blob(chunks,{type:active.mimeType||chunks[0].type}));
        else if(!rejected)setError("Keine Aufnahme vorhanden.");
      };
      active.start(1000);
      setAudio(null);setPreview("");setElapsed(0);setRecording(true);captureStart.current=Date.now();
      timer.current=window.setInterval(()=>{
        const seconds=Math.floor((Date.now()-captureStart.current)/1000);setElapsed(seconds);
        if(seconds>=MAX_RECORDING_SECONDS&&active.state!=="inactive")active.stop();
      },250);
    } catch(e) {
      if(version===generation.current){stopTracks();recorder.current=null;clearTimer();setRecording(false);setError(e instanceof Error?e.message:"Mikrofon konnte nicht geöffnet werden.");}
    } finally {if(live.current&&version===generation.current)setStarting(false);}
  }
  async function transcribe() {
    if(!audio||!status?.enabled||busy||recording)return;
    setBusy(true);setError("");
    const controller=new AbortController();abort.current=controller;
    const version=generation.current;
    try{
      const result=await request<{text:string}>("/api/voice/transcribe",{method:"POST",headers:{"Content-Type":audio.type||"application/octet-stream"},body:audio,signal:controller.signal});
      if(live.current&&version===generation.current)setPreview(result.text);
    }catch(e){if(live.current&&version===generation.current&&!controller.signal.aborted)setError(e instanceof Error?e.message:String(e));}
    finally{if(live.current&&version===generation.current)setBusy(false);if(abort.current===controller)abort.current=null;}
  }
  function append() {
    const field=target.current;if(!field)return;
    const addition=preview.trim();if(!addition)return;
    const value=field.value.trimEnd()+(field.value.trimEnd()?"\n":"")+addition;
    if(props.maxLength!==undefined&&value.length>props.maxLength){setError("Der Text ist für dieses Eingabefeld zu lang. Bitte kürze die Transkription oder nutze die Schnellerfassung.");return;}
    if(onVoiceAppend)onVoiceAppend(value);else field.value=value;setPreview("");setAudio(null);setError("");setOpen(false);field.focus();
  }
  return <div className="voice-textarea">
    <textarea {...props} ref={target}/>
    <button type="button" className="quiet" onClick={()=>void show()} disabled={props.disabled}>{open?"Spracheingabe schließen":"🎙 Spracheingabe"}</button>
    {open&&<div className="voice-controls">
      <p className="muted">Audio wird erst beim Transkribieren an den konfigurierten Sprachdienst gesendet. LifePilot speichert nur Text, den du anschließend bewusst absendest.</p>
      {error&&<p className="error" role="alert">{error}</p>}
      {!status&&!error&&<p role="status" className="muted">Sprachdienst wird geprüft …</p>}
      {status&&!status.enabled&&<p className="muted">Spracherkennung ist noch nicht konfiguriert.</p>}
      {status?.enabled&&<>
        <div className="commitment-actions">
          {recording?<button type="button" onClick={()=>{const current=recorder.current;if(current&&current.state!=="inactive")current.stop();}}>Aufnahme beenden ({elapsed} s)</button>:<button type="button" disabled={starting||busy||props.disabled} onClick={()=>void start()}>{starting?"Mikrofon wird geöffnet …":"Aufnahme starten"}</button>}
          <label>Oder Audiodatei auswählen<input type="file" accept="audio/*,.webm,.m4a,.mp4,.ogg,.wav,.mp3,.flac" disabled={starting||recording||busy||props.disabled} onChange={e=>{const file=e.target.files?.[0];e.target.value="";if(!file)return;setError("");if(file.size>status.max_audio_bytes){setError("Audio darf höchstens 10 MiB groß sein.");return;}const type=FILE_TYPES[file.name.split(".").pop()?.toLowerCase()??""]||file.type;if(!type){setError("Unbekanntes Audioformat.");return;}setAudio(new Blob([file],{type}));setPreview("");}}/></label>
        </div>
        {audio&&!recording&&<><audio controls src={audioUrl}/><div className="commitment-actions"><button type="button" disabled={busy||props.disabled} onClick={()=>void transcribe()}>{busy?"Wird transkribiert …":"Transkribieren"}</button><button type="button" className="quiet" disabled={busy} onClick={()=>{setAudio(null);setPreview("");setError("");}}>Aufnahme verwerfen</button></div></>}
        {preview&&<><label>Transkription prüfen und korrigieren<textarea rows={5} value={preview} maxLength={20000} disabled={busy} onChange={e=>setPreview(e.target.value)}/></label><button type="button" disabled={busy||props.disabled||!preview.trim()} onClick={append}>Text zur Eingabe hinzufügen</button></>}
      </>}
    </div>}
  </div>;
}
