"use client";
import {useState,type FormEvent} from "react";

type Request=<T>(path:string,init?:RequestInit)=>Promise<T>;
const groups=[
  {key:"capture",name:"Erfassung",read:"Vorhandene Erfassungen samt KI-Vorschlägen lesen",write:"Neue Rohtexte einreichen (nur Empfangsbestätigung)"},
  {key:"tasks",name:"Aufgaben",read:"Aufgaben, Historie, Schritte und Empfehlungen lesen",write:"Aufgaben erstellen, bearbeiten, abschließen und Schritte verwalten"},
  {key:"notes",name:"Notizen und Erinnerungen",read:"Notizen und gespeicherte Erinnerungen lesen",write:"Notizen und Erinnerungen erstellen und bearbeiten"},
  {key:"people",name:"Personen und Kontakte",read:"Personen, Kontaktdaten, Anrufe und Beziehungen lesen",write:"Personen, Kontakte, Anrufe und Beziehungen erfassen oder bearbeiten"},
  {key:"projects",name:"Projekte",read:"Projekte lesen",write:"Projekte erstellen und bearbeiten"},
  {key:"calendar",name:"Kalender und Erlebnisse",read:"Termine und Erlebnisse lesen",write:"Termine und Erlebnisse erstellen und bearbeiten"},
  {key:"documents",name:"Dokumente",read:"Dokumentmetadaten und extrahierte Texte lesen"},
  {key:"family",name:"Familie",read:"Gemeinsame Inhalte und freigegebene Momentaufnahmen lesen"},
] as const;
const presets:Record<string,string[]>={"Erfassung ohne Lesezugriff":["capture:write"],"Aufgaben lesen":["tasks:read"],"Aufgaben verwalten":["tasks:read","tasks:write"],"Gedächtnis lesen":["notes:read","people:read"],"Kalender verwalten":["calendar:read","calendar:write"],"Familie lesen":["family:read"]};
export function McpSettingsPanel({request,username}:{request:Request;username:string}){
  const [scopes,setScopes]=useState<string[]>(["capture:write"]);
  const [token,setToken]=useState(""),[issuedScopes,setIssuedScopes]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  function choose(next:string[]){setScopes(next);setToken("");setNotice("");setError("");}
  function toggle(key:string,mode:"read"|"write",checked:boolean){
    const next=new Set(scopes),scope=key+":"+mode;
    if(checked){next.add(scope);if(mode==="write"&&key!=="capture")next.add(key+":read");}
    else{next.delete(scope);if(mode==="read"&&key!=="capture")next.delete(key+":write");}
    choose([...next]);
  }
  async function create(e:FormEvent<HTMLFormElement>){
    e.preventDefault();const form=e.currentTarget;
    const password=String(new FormData(form).get("password")??"");
    if(!scopes.length||!password)return;
    setBusy(true);setError("");setToken("");setNotice("");
    try{
      const selected=[...scopes];
      const result=await request<{access_token:string}>("/api/auth/mcp-token",{method:"POST",cache:"no-store",body:JSON.stringify({username,password,access:"scoped",scopes:selected})});
      setToken(result.access_token);setIssuedScopes(selected);
    }catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{form.reset();setBusy(false);}
  }
  async function copy(){try{await navigator.clipboard.writeText(token);setNotice("Token kopiert.");}catch{setError("Kopieren nicht möglich. Bitte Token manuell markieren.");}}
  return <section className="card panel profile-panel"><div className="panel-head"><div><span className="eyebrow">SPRACHMODELLE</span><h2>MCP-Zugriff erstellen</h2></div></div>
    <p>Erstelle für jeden Assistenten einen eigenen, eingeschränkten Token. Ohne ausgewählten Bereich ist der Zugriff gesperrt. Diese Tokens erlauben keine Löschanfragen, Personenzusammenführung, Bestätigung von KI-Vorschlägen oder globale Suche.</p>
    <form className="person-form" onSubmit={create}>
      <label>Vorlage<select value="" disabled={busy} onChange={e=>{if(e.target.value)choose(presets[e.target.value]);}}><option value="">Vorlage auswählen …</option>{Object.keys(presets).map(name=><option key={name} value={name}>{name}</option>)}</select></label>
      {groups.map(g=><fieldset className="family-fields" key={g.key} disabled={busy}><legend>{g.name}</legend><label><input type="checkbox" checked={scopes.includes(g.key+":read")} onChange={e=>toggle(g.key,"read",e.target.checked)}/>{g.read}</label>{"write" in g&&<label><input type="checkbox" checked={scopes.includes(g.key+":write")} onChange={e=>toggle(g.key,"write",e.target.checked)}/>{g.write}</label>}</fieldset>)}
      <p className="form-hint">Schreibrechte enthalten das zugehörige Leserecht, außer bei reiner Erfassung. Verknüpfungen mit anderen Bereichen benötigen zusätzliche Leserechte. Freigegebene Texte können trotzdem private Informationen enthalten. Familienmitglieder können gemeinsame Daten mit eigenen Familien-Tokens lesen.</p>
      <label>Aktuelles Passwort<input name="password" type="password" autoComplete="current-password" required maxLength={1024} disabled={busy}/></label>
      <button disabled={busy||!scopes.length}>{busy?"Token wird erstellt …":"Eingeschränkten MCP-Token erstellen"}</button>
    </form>
    {error&&<p className="error" role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {token&&<article className="inbox-item"><h3>Token (12 Stunden gültig)</h3><p>{issuedScopes.join(", ")}</p><label>Bearer-Token<textarea readOnly value={token} rows={5} autoComplete="off" spellCheck={false}/></label><div className="commitment-actions"><button type="button" onClick={()=>void copy()}>Token kopieren</button><button type="button" className="quiet" onClick={()=>{setToken("");setNotice("");}}>Ausblenden</button></div><p className="muted">Wie ein Passwort behandeln. Der Token wird nicht dauerhaft in der Oberfläche gespeichert. Ausblenden widerruft ihn nicht. Passwortwechsel invalidiert alle bisherigen Zugangstokens; ein Einzelwiderruf ist noch nicht verfügbar.</p></article>}
  </section>;
}
