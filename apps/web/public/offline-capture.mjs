import {offlineIdentity,readDraft,writeDraft,pendingCaptures,enqueueCapture,removeCapture,syncCaptures} from "./offline-store.mjs";
const status=document.getElementById("status"),workspace=document.getElementById("workspace"),thought=document.getElementById("thought"),pending=document.getElementById("pending"),sync=document.getElementById("sync"),save=document.getElementById("save");
let identity=null,busy=false,active=true;
const message=value=>{status.textContent=value;};
function render(){
  if(!identity)return;
  try{
    const rows=pendingCaptures(identity.api,identity.owner);pending.replaceChildren();
    if(!rows.length)pending.textContent="Keine ausstehenden Eingaben.";
    for(const row of rows){
      const item=document.createElement("article"),text=document.createElement("p"),date=document.createElement("small"),remove=document.createElement("button");
      date.textContent=new Date(row.captured_at).toLocaleString("de-DE");text.textContent=row.text;
      remove.textContent="Lokal verwerfen";remove.type="button";remove.disabled=busy;
      remove.onclick=()=>{if(!busy&&confirm("Diese noch nicht bestätigte Erfassung lokal entfernen? Sie könnte bereits auf dem Server angekommen sein.")){try{removeCapture(identity.api,identity.owner,row.id);render();}catch(e){message(e.message);}}};
      item.append(date,text,remove);pending.append(item);
    }
  }catch(e){message(e.message);}
}
async function validIdentity(){
  const current=await offlineIdentity();
  return current&&identity&&current.owner===identity.owner&&current.api===identity.api&&current.token===identity.token;
}
async function send(path,init={}){
  if(!active||!await validIdentity())throw new Error("Konto geändert. Bitte erneut anmelden.");
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);
  try{
    const response=await fetch(identity.api+path,{...init,headers:{"Authorization":"Bearer "+identity.token,"Content-Type":"application/json"},signal:controller.signal,cache:"no-store"});
    if(!response.ok)throw new Error(response.status===401||response.status===403?"Bitte erneut in LifePilot anmelden. Lokale Eingaben bleiben erhalten.":"Serveranfrage fehlgeschlagen ("+response.status+"). Eingaben bleiben lokal.");
    return await response.json();
  }finally{clearTimeout(timer);}
}
async function flush(){
  if(!identity||busy||!navigator.onLine||!active)return;
  busy=true;sync.disabled=true;render();
  try{
    if(!pendingCaptures(identity.api,identity.owner).length)return;
    const user=await send("/api/auth/me");
    if(user.id!==identity.owner)throw new Error("Konto stimmt nicht überein. Keine Übertragung.");
    const sent=await syncCaptures(identity.api,identity.owner,payload=>send("/api/captures",{method:"POST",body:JSON.stringify(payload)}));
    message(sent?sent+" Erfassung(en) synchronisiert.":"Keine ausstehenden Erfassungen.");
  }catch(e){message(e instanceof Error?e.message:String(e));}
  finally{busy=false;sync.disabled=false;render();}
}
async function init(){
  identity=await offlineIdentity();
  if(!identity){message("Kein zuvor bestätigtes Konto auf diesem Gerät. Melde dich online an, bevor du offline erfasst.");return;}
  try{thought.value=readDraft(identity.api,identity.owner);render();workspace.hidden=false;message("Lokale Erfassung für dein zuletzt bestätigtes Konto bereit.");}
  catch(e){message(e.message);return;}
  thought.addEventListener("input",()=>{try{writeDraft(identity.api,identity.owner,thought.value);}catch(e){message("Entwurf nicht gespeichert: "+e.message);}});
  document.getElementById("capture").addEventListener("submit",async e=>{
    e.preventDefault();save.disabled=true;
    try{
      if(!await validIdentity())throw new Error("Konto geändert. Bitte erneut anmelden.");
      enqueueCapture(identity.api,identity.owner,thought.value);
      thought.value="";
      try{writeDraft(identity.api,identity.owner,"");}catch{message("Erfassung gespeichert, alter Entwurf konnte nicht entfernt werden.");render();return;}
      message("Lokal gespeichert. Synchronisierung erfolgt bei Verbindung.");render();void flush();
    }catch(e){message(e.message);}finally{save.disabled=false;}
  });
  sync.onclick=()=>{if(!navigator.onLine)message("Keine Internetverbindung. Eingaben bleiben lokal.");else void flush();};
  window.addEventListener("online",flush);
  window.addEventListener("storage",async e=>{
    if(!await validIdentity()){active=false;workspace.hidden=true;thought.value="";pending.replaceChildren();message("Konto geändert. Bitte erneut anmelden.");return;}
    if(e.key?.includes(":draft"))thought.value=readDraft(identity.api,identity.owner);
    render();
  });
  document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")void flush();});
  setInterval(()=>{if(document.visibilityState==="visible")void flush();},30000);
  void flush();
}
void init();
