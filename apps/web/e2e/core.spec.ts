import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const username = process.env.LIFEPILOT_E2E_USERNAME ?? process.env.LIFE_PILOT_BOOTSTRAP_USERNAME;
const password = process.env.LIFEPILOT_E2E_PASSWORD ?? process.env.LIFE_PILOT_BOOTSTRAP_PASSWORD;
const apiUrl = process.env.LIFEPILOT_E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const suffix = randomUUID().slice(0, 8);
const parentName = `E2E-Person-${suffix}`;
const childName = `E2E-Kind-${suffix}`;
const captureText = `E2E-Original-${suffix}`;

async function login(page: Page): Promise<void> {
  if (!username || !password) {
    throw new Error("Für E2E sind LIFEPILOT_E2E_USERNAME und LIFEPILOT_E2E_PASSWORD erforderlich.");
  }
  await page.goto("/");
  await page.getByLabel("Benutzername").fill(username);
  await page.getByLabel("Passwort").fill(password);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.locator("#people")).toBeVisible();
}

async function deleteCreatedPeople(request: APIRequestContext): Promise<void> {
  if (!username || !password) return;
  const loginResponse = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  if (!loginResponse.ok()) return;
  const token = (await loginResponse.json()).access_token as string;
  const peopleResponse = await request.get(`${apiUrl}/api/people?q=E2E-`, { headers: { Authorization: `Bearer ${token}` } });
  if (!peopleResponse.ok()) return;
  const people = (await peopleResponse.json()) as { id: string; first_name: string }[];
  for (const person of people.filter(({ first_name }) => first_name === parentName || first_name === childName)) {
    await request.delete(`${apiUrl}/api/people/${person.id}`, { headers: { Authorization: `Bearer ${token}` } });
  }
  const capturesResponse = await request.get(`${apiUrl}/api/captures`, { headers: { Authorization: `Bearer ${token}` } });
  if (capturesResponse.ok()) {
    const captures = (await capturesResponse.json()) as { id: string; original_text: string }[];
    for (const capture of captures.filter(({ original_text }) => original_text === captureText)) {
      await request.delete(`${apiUrl}/api/captures/${capture.id}`, { headers: { Authorization: `Bearer ${token}` } });
    }
  }
}

test.afterEach(async ({ request }) => {
  await deleteCreatedPeople(request);
});

test("Anmeldung, Personenbeziehung und PWA-Offline-Shell funktionieren", async ({ page }) => {
  await login(page);

  const manifest = await page.request.get(new URL("/manifest.webmanifest", page.url()).toString());
  expect(manifest.ok()).toBeTruthy();
  const manifestBody = await manifest.json();
  expect(manifestBody.display).toBe("standalone");
  expect(manifestBody.icons.some((icon: { sizes: string }) => icon.sizes === "192x192")).toBeTruthy();
  expect(manifestBody.icons.some((icon: { sizes: string }) => icon.sizes === "512x512")).toBeTruthy();
  expect((await page.request.get(new URL("/icon-192.png", page.url()).toString())).ok()).toBeTruthy();
  expect((await page.request.get(new URL("/icon-512.png", page.url()).toString())).ok()).toBeTruthy();

  await page.locator(".capture textarea[name=content]").fill(captureText);
  await page.locator(".capture").getByRole("button", { name: "Speichern" }).click();
  await expect(page.locator(".inbox-panel")).toContainText(captureText);

  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(parentName) })).toBeVisible();
  await page.locator("#people input[name=first_name]").fill(childName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(childName) })).toBeVisible();

  await page.getByRole("button", { name: new RegExp(childName) }).click();
  await page.locator(".relationship-form select[name=target_id]").selectOption({ label: parentName });
  await page.locator(".relationship-form select[name=relationship_type]").selectOption({ label: "Diese Person ist Tochter von / andere ist Vater" });
  await page.getByRole("button", { name: "Beziehung hinzufügen" }).click();
  await expect(page.locator(".person-profile")).toContainText(`${childName} ist Tochter von`);
  await expect(page.locator(".person-profile")).toContainText(`${parentName} ist Vater von`);

  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker?.controller))).toBe(true);
  await page.context().setOffline(true);
  await page.reload();
  await expect(page.locator("#people")).toBeVisible();
  await page.context().setOffline(false);
});
