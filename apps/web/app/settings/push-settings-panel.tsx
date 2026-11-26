"use client";
import {useCallback,useEffect,useState} from "react";

type Request = <T>(path:string,init?:RequestInit)=>Promise<T>;
type Status = {enabled:boolean;public_key:string|null};
type Device = {id:string;label:string;created_at:string;last_sent_at:string|null;active:boolean};
const LOCAL_DEVICE = "lifepilot-push-device";
function bytes(value:string): Uint8Array<ArrayBuffer> {
  const decoded=atob(value.replace(/-/g,"+").replace(/_/g,"/").padEnd(Math.ceil(value.length/4)*4,"="));
  return Uint8Array.from(decoded,c=>c.charCodeAt(0));
}
function supportsPush() {
  return typeof window!=="undefined"&&window.isSecureContext&&"serviceWorker" in navigator&&"PushManager" in window&&"Notification" in window;
}
async function registration() {
  const reg=await navigator.serviceWorker.getRegistration();
  if(!reg||!reg.active)throw new Error("Der Service Worker ist noch nicht aktiv. Lade LifePilot erneut.");
  return reg;
}
export function PushSettingsPanel({request}:{request:Request}) {
  const [supported,setSupported]=useState(false);
  const [status,setStatus]=useState<Status|null>(null);
  const [devices,setDevices]=useState<Device[]>([]);
  const [local,setLocal]=useState("");
  const [label,setLabel]=useState("Dieses Gerät");
  const [permission,setPermission]=useState<NotificationPermission>("default");
  const [browserSubscribed,setBrowserSubscribed]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const load=useCallback(async()=>{
    const [config,rows]=await Promise.all([request<Status>("/api/push/status"),request<Device[]>("/api/push/devices")]);
    setStatus(config);setDevices(rows);
    if(supportsPush()){
      setPermission(Notification.permission);
      const reg=await navigator.serviceWorker.getRegistration();
      setBrowserSubscribed(!!(await reg?.pushManager.getSubscription()));
      try{setLocal(localStorage.getItem(LOCAL_DEVICE)||"");}catch{}
    }
  },[request]);
  useEffect(()=>{setSupported(supportsPush());void load().catch(e=>setError(String(e)));},[load]);
  async function enable(){
    if(!status?.public_key||busy||!label.trim())return;
    setBusy(true);setError("");setMessage("");
    try{
      // Permission request must start in a direct user gesture, especially on iOS.
      const granted=await Notification.requestPermission();setPermission(granted);
      if(granted!=="granted")throw new Error("Benachrichtigungen wurden nicht erlaubt. Prüfe deine Browsereinstellungen.");
      const reg=await registration();
      const key=bytes(status.public_key);
      let sub=await reg.pushManager.getSubscription();
      if(sub){
        const existing=sub.options.applicationServerKey;
        if(!existing||new Uint8Array(existing).length!==key.length||new Uint8Array(existing).some((v,i)=>v!==key[i])){
          await sub.unsubscribe();sub=null;
        }
      }
      let created=false;
      if(!sub){sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:key});created=true;}
      try{
        const serialized=sub.toJSON();
        const device=await request<Device>("/api/push/devices",{method:"POST",body:JSON.stringify({endpoint:sub.endpoint,keys:serialized.keys,label:label.trim()})});
        try{localStorage.setItem(LOCAL_DEVICE,device.id);}catch{}
        setLocal(device.id);setBrowserSubscribed(true);
      }catch(e){if(created)await sub.unsubscribe().catch(()=>{});throw e;}
      setMessage("Gerät angemeldet. Benachrichtigungen werden bei fälligen Erinnerungen gesendet.");
      await load();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function revoke(device:Device){
    if(!window.confirm("Push für „"+device.label+"“ deaktivieren?"))return;
    setBusy(true);setError("");setMessage("");
    try{
      await request("/api/push/devices/"+device.id,{method:"DELETE"});
      if(local===device.id){
        try{
          if(supportsPush()){const reg=await navigator.serviceWorker.getRegistration();const sub=await reg?.pushManager.getSubscription();if(sub)await sub.unsubscribe();}
        }finally{try{localStorage.removeItem(LOCAL_DEVICE);}catch{}setLocal("");}
      }
      setMessage("Gerät serverseitig entfernt.");await load();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function clearBrowser(){
    if(!window.confirm("Lokales Browser-Abonnement entfernen? Ein ggf. zugehöriges Servergerät sollte ebenfalls in seinem Konto entfernt werden."))return;
    setBusy(true);setError("");
    try{
      const reg=await navigator.serviceWorker.getRegistration();
      const sub=await reg?.pushManager.getSubscription();
      if(sub)await sub.unsubscribe();
      try{localStorage.removeItem(LOCAL_DEVICE);}catch{}
      setLocal("");await load();setMessage("Lokales Browser-Abonnement entfernt.");
    }catch(e){setError(String(e));}finally{setBusy(false);}
  }
  const current=devices.find(d=>d.id===local&&d.active);
  return <section className="card panel profile-panel">
    <div className="panel-head"><div><span className="eyebrow">BENACHRICHTIGUNGEN</span><h2>Push-Benachrichtigungen</h2></div></div>
    <p className="muted">Erhalte diskrete Hinweise bei fälligen Erinnerungen, Verpflichtungen und Routinen mit Zeitfenster. Keine Namen, Aufgaben oder persönlichen Details erscheinen in Push-Nachrichten. Deine Ruhezeiten werden beim Senden berücksichtigt.</p>
    {error&&<p className="error" role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    {status===null?<p className="muted">Push-Konfiguration wird geprüft …</p>:!status.enabled?<p>Web Push ist serverseitig noch nicht konfiguriert.</p>:!supported?<p>Dieser Browser unterstützt hier kein Web Push. Auf iPhone/iPad muss LifePilot als Web-App zum Home-Bildschirm hinzugefügt und von dort geöffnet werden. HTTPS ist erforderlich.</p>:<>
      <p>Browserberechtigung: {permission==="granted"?"Erlaubt":permission==="denied"?"Blockiert":"Noch nicht erteilt"} · {current&&browserSubscribed?"Dieses Gerät ist angemeldet.":"Dieses Gerät ist nicht eindeutig angemeldet."}</p>
      <label>Gerätename<input value={label} onChange={e=>setLabel(e.target.value)} maxLength={120}/></label>
      <div className="commitment-actions"><button type="button" disabled={busy||!label.trim()||permission==="denied"} onClick={()=>void enable()}>{current&&browserSubscribed?"Gerät aktualisieren":"Push auf diesem Gerät aktivieren"}</button>{browserSubscribed&&<button type="button" className="quiet" disabled={busy} onClick={()=>void clearBrowser()}>Browser-Abonnement entfernen</button>}</div>
    </>}
    <h3>Angemeldete Geräte</h3>
    {devices.length===0?<p className="muted">Keine Geräte angemeldet.</p>:devices.map(device=><div className="list-item" key={device.id}><span>{device.label}{device.id===local?" (dieser Browser)":""}<small>{device.active?"Aktiv":"Inaktiv – erneut anmelden"} · {device.last_sent_at?"Letzter Versand: "+new Date(device.last_sent_at).toLocaleString("de-DE"):"Noch kein Versand"}</small></span><button type="button" className="quiet" disabled={busy} onClick={()=>void revoke(device)}>Deaktivieren</button></div>)}
    <p className="form-hint">Push bleibt auch nach dem Abmelden aktiv, bis das Gerät entfernt oder dein Passwort geändert wird. Nutze Push nur auf vertrauenswürdigen Geräten. Die Zustellung hängt vom Browser und Betriebssystem ab.</p>
  </section>;
}
