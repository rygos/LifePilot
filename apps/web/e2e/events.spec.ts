import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const username = process.env.LIFEPILOT_E2E_USERNAME ?? process.env.LIFE_PILOT_BOOTSTRAP_USERNAME;
const password = process.env.LIFEPILOT_E2E_PASSWORD ?? process.env.LIFE_PILOT_BOOTSTRAP_PASSWORD;
const apiUrl = process.env.LIFEPILOT_E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const suffix = randomUUID().slice(0, 8);
const personName = `E2E-Ereignis-${suffix}`;
const eventTitle = `E2E-Treffen-${suffix}`;

async function login(page: Page): Promise<void> {
  if (!username || !password) throw new Error("Für E2E sind LIFEPILOT_E2E_USERNAME und LIFEPILOT_E2E_PASSWORD erforderlich.");
  await page.goto("/");
  await page.getByLabel("Benutzername").fill(username);
  await page.getByLabel("Passwort").fill(password);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
}

async function removeFixtures(request: APIRequestContext): Promise<void> {
  if (!username || !password) return;
  const loginResponse = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  if (!loginResponse.ok()) return;
  const token = (await loginResponse.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const eventsResponse = await request.get(`${apiUrl}/api/events`, { headers });
  if (eventsResponse.ok()) {
    const events = (await eventsResponse.json()) as { id: string; title: string }[];
    for (const event of events.filter(item => item.title === eventTitle)) await request.delete(`${apiUrl}/api/events/${event.id}`, { headers });
  }
  const peopleResponse = await request.get(`${apiUrl}/api/people`, { headers });
  if (peopleResponse.ok()) {
    const people = (await peopleResponse.json()) as { id: string; first_name: string }[];
    for (const person of people.filter(item => item.first_name === personName)) await request.delete(`${apiUrl}/api/people/${person.id}`, { headers });
  }
}

test.afterEach(async ({ request }) => removeFixtures(request));

test("past event can be selected from the calendar with participants, place and photos", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(personName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();

  await page.goto("/events");
  const calendarSpacing = await page.locator(".event-calendar-heading").evaluate(element => {
    const [previous, title, next] = Array.from(element.children, child => child.getBoundingClientRect());
    return { left: title.left - previous.right, right: next.left - title.right };
  });
  expect(calendarSpacing.left).toBeGreaterThan(0);
  expect(calendarSpacing.left).toBeLessThan(20);
  expect(calendarSpacing.right).toBeGreaterThan(0);
  expect(calendarSpacing.right).toBeLessThan(20);
  await page.getByText("Ereignis manuell festhalten").click();
  const form = page.locator(".event-create form");
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000);
  const localNow = new Date(yesterday.getTime() - yesterday.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  await form.locator("input[name=title]").fill(eventTitle);
  await form.locator("input[name=starts_at]").fill(localNow);
  await form.locator("input[name=location]").fill("Bei Freunden");
  await form.locator("input[name=location_address]").fill("Beispielweg 7");
  const participantPicker = form.getByRole("combobox", { name: "Teilnehmende" });
  await participantPicker.fill(personName);
  await form.getByRole("option", { name: personName }).click();
  await expect(form.locator(".person-picker-chip")).toContainText(personName);
  await form.getByRole("button", { name: `${personName} entfernen` }).click();
  await expect(form.locator(".person-picker-chip")).toHaveCount(0);
  await participantPicker.fill(personName);
  await participantPicker.press("ArrowDown");
  await participantPicker.press("Enter");
  await form.locator("textarea[name=description]").fill("Wir haben gemeinsam Lego gebaut.");
  await form.getByRole("button", { name: "Ereignis speichern" }).click();

  await expect(page.locator(".event-detail")).toContainText(eventTitle);
  await expect(page.locator(".event-detail")).toContainText("Wir haben gemeinsam Lego gebaut.");
  await expect(page.locator(".event-detail")).toContainText("Bei Freunden");
  await expect(page.locator(".event-participant-card")).toContainText(personName);
  await expect(page.locator(".event-summary-context")).toContainText("Wir haben gemeinsam Lego gebaut.");

  await page.locator(".event-detail").getByRole("button", { name: "Bearbeiten" }).click();
  const editForm = page.locator(".event-detail .event-edit-form");
  await expect(editForm.locator("input[name=title]")).toBeVisible();
  await expect(page.locator(".event-summary-context")).toHaveCount(0);
  await expect(page.locator(".event-participant-cards")).toHaveCount(0);
  await editForm.locator("textarea[name=description]").fill("Wir haben gemeinsam Lego gebaut und weiter darüber gesprochen.");
  await editForm.getByRole("button", { name: "Änderungen speichern" }).click();
  await expect(page.locator(".event-summary-context")).toContainText("Wir haben gemeinsam Lego gebaut und weiter darüber gesprochen.");
  await expect(editForm).toHaveCount(0);

  const image = await readFile("public/icon-192.png");
  const upload = page.locator(".event-photo-upload");
  await upload.locator("input[name=file]").setInputFiles({ name: "event.png", mimeType: "image/png", buffer: image });
  await upload.locator("input[name=caption]").fill("Lego-Projekt");
  await upload.getByRole("button", { name: "Hochladen" }).click();
  await expect(page.locator(".event-photo-card")).toContainText("Lego-Projekt");
  await expect(page.locator(".event-photo-card img")).toBeVisible();

  const monthHeading = page.locator(".event-calendar-heading h3");
  const eventMonth = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(yesterday);
  const previousMonth = new Date(yesterday.getFullYear(), yesterday.getMonth() - 1, 1);
  await page.getByRole("button", { name: "Vorheriger Monat" }).click();
  await expect(monthHeading).toHaveText(new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric" }).format(previousMonth));
  await page.getByRole("button", { name: "Nächster Monat" }).click();
  await expect(monthHeading).toHaveText(eventMonth);
  await expect(page.locator(".event-day-list")).toContainText(eventTitle);
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileWidths = await page.locator(".event-archive").evaluate(element => ({ client: element.clientWidth, scroll: element.scrollWidth }));
  expect(mobileWidths.scroll).toBeLessThanOrEqual(mobileWidths.client);
});
