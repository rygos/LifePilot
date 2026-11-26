const PREFIX = "lifepilot-offline:v1:";
const IDENTITY = PREFIX + "identity";
const TOKEN = "lifepilot-token";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const scope = (api, owner) => PREFIX + encodeURIComponent(api) + ":" + owner + ":";
const key = (api, owner, id) => scope(api, owner) + "q:" + id;
const notify = () => { if (typeof window !== "undefined") window.dispatchEvent(new Event("lifepilot-offline-change")); };
const storage = () => globalThis.localStorage;

async function fingerprint(token) {
  if (!globalThis.crypto?.subtle || !token) return null;
  const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, "0")).join("");
}

export async function rememberIdentity(api, owner, token) {
  const digest = await fingerprint(token);
  if (!digest || !UUID.test(owner) || storage().getItem(TOKEN) !== token) return;
  storage().setItem(IDENTITY, JSON.stringify({api,owner,digest}));
}
export function forgetIdentity() { storage().removeItem(IDENTITY); }
export async function offlineIdentity() {
  try {
    const token = storage().getItem(TOKEN);
    const saved = JSON.parse(storage().getItem(IDENTITY) || "null");
    if (!saved || !token || !UUID.test(saved.owner) || typeof saved.api !== "string") return null;
    const digest = await fingerprint(token);
    return digest && digest === saved.digest && storage().getItem(TOKEN) === token ? {api:saved.api,owner:saved.owner,token} : null;
  } catch { return null; }
}
export function readDraft(api, owner) { return storage().getItem(scope(api,owner)+"draft") || ""; }
export function writeDraft(api, owner, text) {
  if (text.length > 20000) throw new Error("Maximal 20.000 Zeichen");
  const k=scope(api,owner)+"draft";
  if(text) storage().setItem(k,text); else storage().removeItem(k);
  notify();
}
export function pendingCaptures(api, owner) {
  const prefix=scope(api,owner)+"q:";
  const rows=[];
  for(let i=0;i<storage().length;i++){
    const k=storage().key(i);
    if(!k?.startsWith(prefix))continue;
    const raw=storage().getItem(k);
    if(raw===null)continue;
    const row=JSON.parse(raw);
    if(!row || !UUID.test(row.id) || k!==key(api,owner,row.id) || typeof row.text!=="string" || !row.text.trim() || row.text.length>20000 || typeof row.captured_at!=="string" || !Number.isFinite(Date.parse(row.captured_at))) throw new Error("Ein lokaler Eintrag ist beschädigt. Bitte den Browserspeicher nicht löschen.");
    rows.push(row);
  }
  return rows.sort((a,b)=>a.captured_at.localeCompare(b.captured_at)||a.id.localeCompare(b.id));
}
function newId() {
  if(globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const h=Array.from(bytes,b=>b.toString(16).padStart(2,"0")).join("");
  return [h.slice(0,8),h.slice(8,12),h.slice(12,16),h.slice(16,20),h.slice(20)].join("-");
}
export function enqueueCapture(api, owner, text) {
  text=text.trim();
  if(!text||text.length>20000)throw new Error("Bitte 1 bis 20.000 Zeichen eingeben.");
  if(pendingCaptures(api,owner).length>=100)throw new Error("Maximal 100 ausstehende Erfassungen. Bitte zuerst synchronisieren.");
  const row={id:newId(),text,captured_at:new Date().toISOString()};
  storage().setItem(key(api,owner,row.id),JSON.stringify(row));
  notify();
  return row;
}
export function removeCapture(api,owner,id) { storage().removeItem(key(api,owner,id));notify(); }
export async function syncCaptures(api,owner,send,signal) {
  let sent=0;
  for(const row of pendingCaptures(api,owner)){
    if(signal?.aborted)break;
    // Another tab may already have sent or removed this entry.
    if(!storage().getItem(key(api,owner,row.id)))continue;
    const result=await send({original_text:row.text,source:"capture",client_request_id:row.id,captured_at:row.captured_at,expected_owner_id:owner},signal);
    if(!result || !UUID.test(result.id) || result.original_text!==row.text)throw new Error("Server hat die Erfassung nicht eindeutig bestätigt.");
    removeCapture(api,owner,row.id);
    sent++;
  }
  return sent;
}
