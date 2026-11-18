import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const username = process.env.LIFEPILOT_E2E_USERNAME ?? process.env.LIFE_PILOT_BOOTSTRAP_USERNAME;
const password = process.env.LIFEPILOT_E2E_PASSWORD ?? process.env.LIFE_PILOT_BOOTSTRAP_PASSWORD;
const apiUrl = process.env.LIFEPILOT_E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const suffix = randomUUID().slice(0, 8);
const parentName = `E2E-Person-${suffix}`;
const childName = `E2E-Kind-${suffix}`;
const captureText = `E2E-Original-${suffix}`;
const chatCaptureText = `E2E-Chat-Gedanke-${suffix}`;

async function login(page: Page): Promise<void> {
  if (!username || !password) {
    throw new Error("Für E2E sind LIFEPILOT_E2E_USERNAME und LIFEPILOT_E2E_PASSWORD erforderlich.");
  }
  await page.goto("/");
  await page.getByLabel("Benutzername").fill(username);
  await page.getByLabel("Passwort").fill(password);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
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
    for (const capture of captures.filter(({ original_text }) => original_text === captureText || original_text === chatCaptureText)) {
      await request.delete(`${apiUrl}/api/captures/${capture.id}`, { headers: { Authorization: `Bearer ${token}` } });
    }
  }
}

test.afterEach(async ({ request }) => {
  await deleteCreatedPeople(request);
});

test("Anmeldung, Beziehungen, Chat-Gedächtnisfragen und PWA-Offline-Shell funktionieren", async ({ page }) => {
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
  await expect(page.getByRole("status")).toContainText(/Originaltext gespeichert|Eingabe gespeichert/);
  await page.goto("/inbox");
  await expect(page.locator(".inbox-panel")).toContainText(captureText);

  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(parentName) })).toBeVisible();
  await page.locator("#people input[name=first_name]").fill(childName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(childName) })).toBeVisible();

  await page.getByRole("button", { name: new RegExp(childName) }).click();
  await expect(page).toHaveURL(/\/people\/.+/);
  await page.locator(".relationship-form select[name=target_id]").selectOption({ label: parentName });
  await page.locator(".relationship-form select[name=relationship_type]").selectOption({ label: "Diese Person ist Tochter von / andere ist Vater" });
  await page.getByRole("button", { name: "Beziehung hinzufügen" }).click();
  await expect(page.locator(".person-profile")).toContainText(`${childName} ist Tochter von`);
  await expect(page.locator(".person-profile")).toContainText(`${parentName} ist Vater von`);

  await page.goto("/people");
  await page.getByRole("button", { name: new RegExp(parentName) }).click();
  await expect(page).toHaveURL(/\/people\/.+/);
  await page.locator(".owner-relationship-form input[name=relationship_type]").fill("Arbeitskollegin");
  await page.locator(".owner-relationship-form").getByRole("button", { name: "Beziehung speichern" }).click();
  await expect(page.locator(".person-profile")).toContainText(`Du kennst ${parentName} als Arbeitskollegin`);

  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Chat" })).toBeVisible();
  await page.getByLabel("Was möchtest du festhalten?").fill(chatCaptureText);
  await page.getByRole("button", { name: "Speichern und prüfen" }).click();
  await expect(page.locator(".chat-entry.assistant")).toBeVisible();
  await page.goto("/inbox");
  await expect(page.locator(".inbox-panel")).toContainText(chatCaptureText);

  await page.goto("/chat");
  await page.getByRole("button", { name: "Fragen" }).click();
  await page.getByLabel("Deine Frage").fill(`Was weißt du über ${parentName}?`);
  await page.getByRole("button", { name: "Frage stellen" }).click();
  await expect(page.locator(".chat-entry.assistant").last()).toBeVisible();
  await expect(page.locator(".chat-source").filter({ hasText: parentName }).first()).toBeVisible();

  await page.goto("/planning");
  const eventForm = page.locator(".events-panel .event-form");
  await eventForm.locator("input[name=title]").fill(`E2E-Termin-${suffix}`);
  await eventForm.locator("input[name=starts_at]").fill("2027-04-01T14:30");
  await eventForm.locator("select[name=participant_ids]").selectOption([{ label: parentName }, { label: childName }]);
  await eventForm.getByRole("button", { name: "Termin speichern" }).click();
  const eventRow = page.locator(".event-item").filter({ hasText: `E2E-Termin-${suffix}` });
  await expect(eventRow).toContainText(parentName);
  await expect(eventRow).toContainText(childName);
  page.once("dialog", dialog => dialog.accept());
  await eventRow.getByRole("button", { name: "Löschen" }).click();
  await expect(eventRow).toHaveCount(0);

  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker?.controller))).toBe(true);
  await page.goto("/");
  await page.context().setOffline(true);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
  await page.context().setOffline(false);
});
