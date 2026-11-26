import { expect, test } from "@playwright/test";

test("offline page survives reload and sends the same queued capture after reconnect", async ({ page, context, baseURL }) => {
  const owner = "3b16b2eb-82e1-4515-88c2-4c8eb231fed1";
  const token = "offline-browser-test-token";
  const api = new URL(baseURL!).origin;
  const posted: Record<string, unknown>[] = [];
  await context.route("**/api/**", async route => {
    if (route.request().url().endsWith("/api/auth/me")) {
      await route.fulfill({json: {id: owner, username: "offline-test", role: "user"}});
    } else if (route.request().url().endsWith("/api/captures") && route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      posted.push(body);
      await route.fulfill({status: 201, json: {id:"3b16b2eb-82e1-4515-88c2-4c8eb231fed2", original_text:body.original_text}});
    } else {
      await route.fulfill({status: 404, json: {detail:"Unexpected test request"}});
    }
  });
  await page.goto("/offline.html");
  await page.evaluate(async ({api,owner,token}) => {
    localStorage.setItem("lifepilot-token",token);
    const url = "/offline-store.mjs";
    const store = await import(/* webpackIgnore: true */ url);
    await store.rememberIdentity(api,owner,token);
    await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
  }, {api,owner,token});
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  await context.setOffline(true);
  await page.reload({waitUntil:"domcontentloaded"});
  await expect(page.getByRole("heading",{name:"LifePilot · Offline-Schnellerfassung"})).toBeVisible();
  await page.getByLabel("Was möchtest du festhalten?").fill("Ein Offline-Gedanke");
  await page.getByRole("button",{name:"Lokal speichern"}).click();
  await expect(page.getByText("Ein Offline-Gedanke",{exact:true})).toBeVisible();
  await page.getByLabel("Was möchtest du festhalten?").fill("Noch ein Entwurf");
  await page.reload({waitUntil:"domcontentloaded"});
  await expect(page.getByLabel("Was möchtest du festhalten?")).toHaveValue("Noch ein Entwurf");
  await expect(page.getByText("Ein Offline-Gedanke",{exact:true})).toBeVisible();
  expect(posted).toHaveLength(0);
  await context.setOffline(false);
  await expect.poll(()=>posted.length).toBe(1);
  expect(posted[0]).toMatchObject({original_text:"Ein Offline-Gedanke",expected_owner_id:owner,source:"capture"});
  expect(posted[0].client_request_id).toMatch(/^[0-9a-f-]{36}$/);
  await expect(page.getByText("Keine ausstehenden Eingaben.")).toBeVisible();
  await expect(page.getByLabel("Was möchtest du festhalten?")).toHaveValue("Noch ein Entwurf");
});
