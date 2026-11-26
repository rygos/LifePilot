import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto, randomUUID} from "node:crypto";
import {rememberIdentity,forgetIdentity,offlineIdentity,readDraft,writeDraft,pendingCaptures,enqueueCapture,removeCapture,syncCaptures} from "./public/offline-store.mjs";

const items=new Map();
Object.defineProperty(globalThis,"localStorage",{configurable:true,value:{
  get length(){return items.size;},key(i){return [...items.keys()][i]??null;},getItem(k){return items.get(k)??null;},setItem(k,v){items.set(k,String(v));},removeItem(k){items.delete(k);}
}});
Object.defineProperty(globalThis,"crypto",{configurable:true,value:webcrypto});
const api="https://test.invalid", owner=randomUUID(), other=randomUUID();
test("identity tied to last verified token; queue and draft remain account scoped",async()=>{
  items.clear();
  localStorage.setItem("lifepilot-token","test-token");
  await rememberIdentity(api,owner,"test-token");
  assert.deepEqual(await offlineIdentity(),{api,owner,token:"test-token"});
  writeDraft(api,owner,"Entwurf");
  const a=enqueueCapture(api,owner,"Ein Gedanke");
  assert.equal(readDraft(api,other),"");
  assert.equal(readDraft(api+"-other",owner),"");
  assert.deepEqual(pendingCaptures(api,other),[]);
  assert.deepEqual(pendingCaptures(api,owner),[a]);
  localStorage.setItem("lifepilot-token","other-token");
  assert.equal(await offlineIdentity(),null);
  await rememberIdentity(api,other,"other-token");
  assert.equal((await offlineIdentity()).owner,other);
  forgetIdentity();
  assert.equal(await offlineIdentity(),null);
  assert.equal(readDraft(api,owner),"Entwurf");
  assert.equal(pendingCaptures(api,owner).length,1);
});
test("failed or ambiguous delivery is retained; retry preserves id and time",async()=>{
  items.clear();
  const a=enqueueCapture(api,owner,"Offline notiert");
  const b=enqueueCapture(api,owner,"Zweiter Gedanke");
  const sent=[];
  await assert.rejects(syncCaptures(api,owner,async payload=>{sent.push(payload);throw new Error("offline");}));
  assert.equal(pendingCaptures(api,owner).length,2);
  await assert.rejects(syncCaptures(api,owner,async()=>({id:randomUUID(),original_text:"wrong"})));
  assert.equal(pendingCaptures(api,owner).length,2);
  const count=await syncCaptures(api,owner,async payload=>{
    sent.push(payload);return {id:randomUUID(),original_text:payload.original_text};
  });
  assert.equal(count,2);
  assert.deepEqual(sent[0],sent[1]);
  assert.equal(sent[0].expected_owner_id,owner);
  assert.deepEqual(new Set(sent.slice(1).map(v=>v.client_request_id)),new Set([a.id,b.id]));
  assert.equal(pendingCaptures(api,owner).length,0);
});
test("local discard affects only selected account; abort preserves unsent entries",async()=>{
  items.clear();
  const a=enqueueCapture(api,owner,"A");
  const b=enqueueCapture(api,other,"B");
  removeCapture(api,other,a.id);
  assert.equal(pendingCaptures(api,owner).length,1);
  assert.deepEqual(pendingCaptures(api,other),[b]);
  const ctrl=new AbortController();ctrl.abort();
  assert.equal(await syncCaptures(api,owner,async()=>{throw Error("must not send");},ctrl.signal),0);
  assert.equal(pendingCaptures(api,owner).length,1);
  removeCapture(api,owner,a.id);
  assert.equal(pendingCaptures(api,owner).length,0);
});
