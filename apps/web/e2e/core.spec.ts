import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const username = process.env.LIFEPILOT_E2E_USERNAME ?? process.env.LIFE_PILOT_BOOTSTRAP_USERNAME;
const password = process.env.LIFEPILOT_E2E_PASSWORD ?? process.env.LIFE_PILOT_BOOTSTRAP_PASSWORD;
const apiUrl = process.env.LIFEPILOT_E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const suffix = randomUUID().slice(0, 8);
const parentName = `E2E-Person-${suffix}`;
const childName = `E2E-Kind-${suffix}`;
const captureText = `E2E-Original-${suffix}`;
const chatCaptureText = `E2E-Chat-Gedanke-${suffix}`;
const chatFollowUpText = `E2E-Nachtrag-${suffix}`;
const chatQuestionText = `Was weißt du über ${parentName}?`;
const organizationName = `E2E-Verein-${suffix}`;
const projectName = `E2E-Projekt-${suffix}`;
const journalTitle = `E2E-Tagebuch-${suffix}`;
const journalContent = `Eintrag zum Browserablauf ${suffix}`;
const journalEventTitle = `E2E-Tagebuch-Ereignis-${suffix}`;
const monicaPersonName = `E2E-Monica-${suffix}`;
const lentItemName = `E2E-Leihgabe-${suffix}`;
const borrowedItemName = `E2E-Rueckgabe-${suffix}`;
const petName = `E2E-Hund-${suffix}`;
const petHolderName = `E2E-Tierhalter-${suffix}`;
const petEventTitle = `E2E-Tierspaziergang-${suffix}`;

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
  const headers = { Authorization: `Bearer ${token}` };
  const petsResponse = await request.get(`${apiUrl}/api/pets?q=${encodeURIComponent(petName)}`, { headers });
  if (petsResponse.ok()) {
    const pets = (await petsResponse.json()) as { id: string; name: string }[];
    for (const pet of pets.filter(({ name }) => name === petName)) await request.delete(`${apiUrl}/api/pets/${pet.id}`, { headers });
  }
  const journalResponse = await request.get(`${apiUrl}/api/journal?q=${encodeURIComponent(journalContent)}`, { headers: { Authorization: `Bearer ${token}` } });
  if (journalResponse.ok()) {
    const entries = (await journalResponse.json()) as { id: string; title: string }[];
    for (const entry of entries.filter(({ title }) => title === journalTitle)) {
      await request.delete(`${apiUrl}/api/journal/${entry.id}`, { headers: { Authorization: `Bearer ${token}` } });
    }
  }
  const peopleResponse = await request.get(`${apiUrl}/api/people?q=E2E-`, { headers });
  if (!peopleResponse.ok()) return;
  const people = (await peopleResponse.json()) as { id: string; first_name: string }[];
  for (const person of people.filter(({ first_name }) => first_name === parentName || first_name === childName || first_name === monicaPersonName || first_name === petHolderName)) {
    await request.delete(`${apiUrl}/api/people/${person.id}`, { headers });
  }
  const organizationsResponse = await request.get(`${apiUrl}/api/organizations`, { headers });
  if (organizationsResponse.ok()) {
    const organizations = (await organizationsResponse.json()) as { id: string; name: string }[];
    for (const organization of organizations.filter(({ name }) => name === organizationName)) {
      await request.delete(`${apiUrl}/api/organizations/${organization.id}`, { headers });
    }
  }
  const capturesResponse = await request.get(`${apiUrl}/api/captures`, { headers });
  if (capturesResponse.ok()) {
    const captures = (await capturesResponse.json()) as { id: string; original_text: string }[];
    for (const capture of captures.filter(({ original_text }) => original_text === captureText || original_text === chatCaptureText || original_text === chatFollowUpText)) {
      await request.delete(`${apiUrl}/api/captures/${capture.id}`, { headers });
    }
  }
  const loansResponse = await request.get(`${apiUrl}/api/loans?open_only=false`, { headers });
  if (loansResponse.ok()) {
    const loans = (await loansResponse.json()) as { id: string; item_name: string }[];
    for (const loan of loans.filter(({ item_name }) => item_name === lentItemName || item_name === borrowedItemName)) {
      await request.delete(`${apiUrl}/api/loans/${loan.id}`, { headers });
    }
  }
  const projectsResponse = await request.get(`${apiUrl}/api/projects?q=E2E-`, { headers });
  if (projectsResponse.ok()) {
    const projects = (await projectsResponse.json()) as { id: string; name: string }[];
    for (const project of projects.filter(({ name }) => name === projectName)) {
      await request.delete(`${apiUrl}/api/projects/${project.id}`, { headers });
    }
  }
  const eventsResponse = await request.get(`${apiUrl}/api/events`, { headers });
  if (eventsResponse.ok()) {
    const events = (await eventsResponse.json()) as { id: string; title: string }[];
    for (const event of events.filter(({ title }) => title === journalEventTitle || title === petEventTitle)) {
      await request.delete(`${apiUrl}/api/events/${event.id}`, { headers });
    }
  }
}

test.afterEach(async ({ request }) => {
  await deleteCreatedPeople(request);
});

test("Tierprofile lassen sich anlegen, mit Mensch und Ereignis verbinden und bearbeiten", async ({ page, request }) => {
  await login(page);
  const loginResponse = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  const token = (await loginResponse.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const personResponse = await request.post(`${apiUrl}/api/people`, { headers, data: { first_name: petHolderName } });
  const personId = ((await personResponse.json()) as { id: string }).id;
  const eventResponse = await request.post(`${apiUrl}/api/events`, { headers, data: { title: petEventTitle, record_type: "experience", starts_at: "2026-11-22T10:00:00+01:00", participant_ids: [personId] } });
  const eventId = ((await eventResponse.json()) as { id: string }).id;

  await page.goto("/pets");
  const create = page.locator(".pet-create");
  if (await create.getAttribute("open") === null) await create.locator("summary").click();
  const form = create.locator(".pet-form");
  await form.locator("input[name=name]").fill(petName);
  await form.locator("input[name=species]").fill("Hund");
  await form.getByRole("combobox", { name: "Person verknüpfen" }).fill(petHolderName);
  await form.getByRole("option", { name: petHolderName }).click();
  await form.getByLabel("Ereignisse").selectOption(eventId);
  await form.getByRole("button", { name: "Tierprofil anlegen" }).click();

  const pet = page.locator(".pet-card").filter({ hasText: petName });
  await expect(pet).toContainText("Hund");
  await expect(pet).toContainText(petHolderName);
  await expect(pet).toContainText(petEventTitle);
  await pet.getByRole("button", { name: "Bearbeiten" }).click();
  const editForm = page.locator(".pet-card .pet-form");
  await editForm.locator("textarea[name=notes]").fill("Mag Spaziergänge am See");
  await editForm.getByRole("button", { name: "Änderungen speichern" }).click();
  await expect(pet).toContainText("Mag Spaziergänge am See");
});

test("Projektanhänge lassen sich in der Projektansicht verwalten", async ({ page }) => {
  await login(page);
  const projects = page.locator("#dashboard-panels");
  await projects.getByPlaceholder("Projektname").fill(projectName);
  await projects.getByRole("button", { name: "Projekt speichern" }).click();
  const project = projects.locator(".project-item").filter({ hasText: projectName });
  await expect(project).toBeVisible();
  await project.locator("summary").click();
  await project.locator(".resource-attachment-form input[type=file]").setInputFiles({ name: "projekt-notiz.txt", mimeType: "text/plain", buffer: Buffer.from("Private Projektunterlage") });
  await project.locator(".resource-attachment-form button[type=submit]").click();
  await expect(project.locator(".resource-attachment-list")).toContainText("projekt-notiz.txt");
  await project.getByRole("button", { name: "projekt-notiz.txt löschen" }).click();
  await expect(project.locator(".resource-attachment-list")).toHaveCount(0);
});

test("Tagebucheinträge lassen sich mit Personen, Projekten und Ereignissen verbinden", async ({ page, request }) => {
  await login(page);
  const loginResponse = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  const token = (await loginResponse.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };
  const person = await request.post(`${apiUrl}/api/people`, { headers, data: { first_name: parentName } });
  const personId = ((await person.json()) as { id: string }).id;
  const project = await request.post(`${apiUrl}/api/projects`, { headers, data: { name: projectName } });
  const projectId = ((await project.json()) as { id: string }).id;
  const eventResponse = await request.post(`${apiUrl}/api/events`, { headers, data: { title: journalEventTitle, record_type: "experience", starts_at: "2026-11-20T17:00:00+01:00", participant_ids: [personId] } });
  const eventId = ((await eventResponse.json()) as { id: string }).id;
  const newerEventResponse = await request.post(`${apiUrl}/api/events`, { headers, data: { title: `${journalEventTitle}-neu`, record_type: "experience", starts_at: "2026-11-22T17:00:00+01:00" } });
  const newerEventId = ((await newerEventResponse.json()) as { id: string }).id;
  await page.goto("/journal");
  const form = page.locator(".journal-new-entry .journal-entry-form");
  await form.locator("input[name=entry_date]").fill("2026-11-20");
  await form.locator("input[name=title]").fill(journalTitle);
  await form.locator("textarea[name=content]").fill(journalContent);
  await form.locator("select[name=mood]").selectOption("dankbar");
  await form.locator("select[name=project_ids]").selectOption(projectId);
  await form.locator("select[name=event_ids]").selectOption(eventId);
  await expect(form.locator(".person-picker-chip")).toContainText(parentName);
  const eventOptions = await form.locator("select[name=event_ids] option").allTextContents();
  expect(eventOptions.findIndex(text => text.includes(`${journalEventTitle}-neu`))).toBeLessThan(eventOptions.findIndex(text => text.includes(journalEventTitle)));
  await form.locator("select[name=event_ids]").selectOption([eventId, newerEventId]);
  await form.getByRole("button", { name: "Eintrag speichern" }).click();
  const entry = page.locator(".journal-entry").filter({ hasText: journalTitle });
  await expect(entry).toContainText(journalContent);
  await expect(entry).toContainText("Dankbar");
  await expect(entry).toContainText(parentName);
  await expect(entry).toContainText(projectName);
  await expect(entry).toContainText(journalEventTitle);
  await page.getByLabel("Suchen", { exact: true }).fill(journalContent);
  await expect(entry).toBeVisible();
  page.once("dialog", dialog => dialog.accept());
  await entry.getByRole("button", { name: "Löschen" }).click();
  await expect(page.locator(".journal-entry")).toHaveCount(0);
});

test("Personenfavoriten, Labels und Kennenlerngeschichte lassen sich bearbeiten und finden", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(monicaPersonName);
  await page.locator("#people input[name=last_name]").fill("Kontaktpflege");
  await page.getByRole("button", { name: "Person hinzufügen" }).click();

  await page.locator(".person-card").filter({ hasText: monicaPersonName }).click();
  await page.getByRole("button", { name: "Bearbeiten" }).click();
  await page.locator(".person-profile textarea[name=how_met]").fill("Beim Sommerfest im Sportverein");
  await page.locator(".person-profile input[name=tags]").fill("Verein, Familie");
  await page.getByRole("button", { name: "Profil speichern" }).click();
  await expect(page.locator(".person-profile")).toContainText("Beim Sommerfest im Sportverein");
  await expect(page.locator(".person-profile")).toContainText("Verein · Familie");

  await page.getByRole("button", { name: "Bearbeiten" }).click();
  await page.locator(".contact-method-create-form select[name=method_type]").selectOption("email");
  await page.locator(".contact-method-create-form input[name=label]").fill("Arbeit");
  await page.locator(".contact-method-create-form input[name=value]").fill("mara@example.org");
  await page.getByRole("button", { name: "Kontakt hinzufügen" }).click();
  await expect(page.locator(".contact-method-edit-form input[name=value]")).toHaveValue("mara@example.org");
  await page.getByRole("button", { name: "Abbrechen" }).click();
  await expect(page.locator(".contact-methods-panel")).toContainText("mara@example.org");

  await page.getByRole("button", { name: "Zu Favoriten" }).click();
  await expect(page.getByRole("button", { name: "★ Favorit" })).toBeVisible();
  await page.goto("/people");
  await page.getByLabel("Filtern").selectOption("favorite");
  await expect(page.locator(".person-card").filter({ hasText: monicaPersonName })).toBeVisible();
  await page.getByLabel("Personen suchen").fill("mara@example.org");
  await expect(page.locator(".person-card").filter({ hasText: monicaPersonName })).toBeVisible();
  await page.getByLabel("Personen suchen").fill("Sportverein");
  await expect(page.locator(".person-card").filter({ hasText: monicaPersonName })).toBeVisible();
});

test("Freunde-Beziehungen sind im Personenprofil sichtbar", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(parentName) })).toBeVisible();
  await page.locator("#people input[name=first_name]").fill(childName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(childName) })).toBeVisible();

  await page.getByRole("button", { name: new RegExp(parentName) }).click();
  await page.locator(".relationship-form select[name=target_id]").selectOption({ label: childName });
  await page.locator(".relationship-form select[name=relationship_type]").selectOption({ label: "Freunde" });
  await page.getByRole("button", { name: "Beziehung hinzufügen" }).click();
  await expect(page.locator(".person-profile")).toContainText(`${parentName} und ${childName} sind befreundet`);

  await page.goto("/people");
  await page.getByRole("button", { name: new RegExp(childName) }).click();
  await expect(page.locator(".person-profile")).toContainText(`${parentName} und ${childName} sind befreundet`);
});

test("Profilgeschlecht bestimmt Beziehungsnamen und das X entfernt die Karte oben rechts", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people select[name=gender]").selectOption("female");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await page.locator("#people select[name=gender]").selectOption("male");
  await page.locator("#people input[name=first_name]").fill(childName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();

  await page.locator(".person-card").filter({ hasText: parentName }).click();
  await page.locator(".relationship-form select[name=target_id]").selectOption({ label: childName });
  await page.locator(".relationship-form select[name=relationship_type]").selectOption("parent");
  await page.getByRole("button", { name: "Beziehung hinzufügen" }).click();
  const relationCard = page.locator(".relationship-card");
  await expect(relationCard).toContainText("Mutter von");
  const remove = page.getByRole("button", { name: `Beziehung zu ${childName} entfernen` });
  const cardBox = await relationCard.boundingBox();
  const removeBox = await remove.boundingBox();
  if (!cardBox || !removeBox) throw new Error("Beziehungskarte oder Entfernen-Schaltfläche hat keine sichtbare Position.");
  expect(removeBox.y - cardBox.y).toBeLessThan(16);
  expect(removeBox.width).toBeGreaterThanOrEqual(44);
  expect(removeBox.height).toBeGreaterThanOrEqual(44);
  await remove.click();
  await expect(page.locator(".relationship-card")).toHaveCount(0);
});

test("Beziehungsmenü ist gestaltet und Chatverläufe bleiben getrennt", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await page.getByRole("button", { name: new RegExp(parentName) }).click();

  const relationshipSelect = page.locator(".owner-relationship-form select[name=relationship_type]");
  const relationshipInput = page.locator(".owner-relationship-form input[name=valid_from]");
  await expect(relationshipSelect).toBeVisible();
  const selectStyle = await relationshipSelect.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color, padding: getComputedStyle(element).padding }));
  const inputStyle = await relationshipInput.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, color: getComputedStyle(element).color, padding: getComputedStyle(element).padding }));
  expect(selectStyle).toEqual(inputStyle);

  await page.goto("/chat");
  await page.getByLabel("Was möchtest du festhalten?").fill(chatCaptureText);
  await page.getByRole("button", { name: "Nachricht senden" }).click();
  await expect(page.locator(".chat-transcript")).toContainText(chatCaptureText);
  await page.getByRole("button", { name: "Fragen" }).click();
  await expect(page.locator(".chat-transcript")).not.toContainText(chatCaptureText);
  await expect(page.locator(".chat-history-note")).toContainText("40 Nachrichten");
  await page.getByRole("button", { name: "Festhalten" }).click();
  await expect(page.locator(".chat-transcript")).toContainText(chatCaptureText);
  await page.getByRole("button", { name: "Fragen" }).click();
  await expect(page.locator(".chat-transcript")).not.toContainText(chatCaptureText);
});

test("Leihgaben lassen sich in beide Richtungen mit optionalem Rückgabedatum erfassen", async ({ page, request }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.locator("#people input[name=last_name]").fill("Leih-Test");
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  const person = page.locator(".person-card").filter({ hasText: parentName });
  await expect(person).toBeVisible();
  await page.goto("/things");
  const loanForm = page.locator(".loan-form");
  await loanForm.locator("input[name=item_name]").fill(lentItemName);
  await loanForm.locator("select[name=direction]").selectOption("lent");
  await loanForm.locator("select[name=person_id]").selectOption({ label: `${parentName} Leih-Test` });
  await loanForm.locator("input[name=due_at]").fill("2026-12-01");
  await loanForm.getByRole("button", { name: "Leihgabe speichern" }).click();
  await expect(page.locator(".panel").filter({ hasText: "Leihgaben" })).toContainText("Rückgabe bis 01.12.2026");
  await loanForm.locator("input[name=item_name]").fill(borrowedItemName);
  await loanForm.locator("select[name=direction]").selectOption("borrowed");
  await loanForm.locator("select[name=person_id]").selectOption({ label: `${parentName} Leih-Test` });
  await loanForm.getByRole("button", { name: "Leihgabe speichern" }).click();
  await expect(page.locator(".panel").filter({ hasText: "Leihgaben" })).toContainText("Ohne Rückgabedatum");
  const loginResponse = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  const token = (await loginResponse.json()).access_token as string;
  const loansResponse = await request.get(`${apiUrl}/api/loans`, { headers: { Authorization: `Bearer ${token}` } });
  const records = (await loansResponse.json()) as { item_name: string; lender_person_id: string | null; borrower_person_id: string | null; due_at: string | null }[];
  const lent = records.find(loan => loan.item_name === lentItemName);
  const borrowed = records.find(loan => loan.item_name === borrowedItemName);
  expect(lent?.lender_person_id).toBeNull();
  expect(lent?.borrower_person_id).not.toBeNull();
  expect(lent?.due_at).toContain("2026-12-01");
  expect(borrowed?.lender_person_id).not.toBeNull();
  expect(borrowed?.borrower_person_id).toBeNull();
  expect(borrowed?.due_at).toBeNull();
});

test("Personenkarten, Profilfoto und Vereinsmitgliedschaften funktionieren auch für das eigene Profil", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.locator("#people select[name=birthday_precision]").selectOption("exact");
  await page.locator("#people input[name=birthday]").fill("1990-01-01");
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  const personCard = page.locator(".person-card").filter({ hasText: parentName });
  await expect(personCard).toContainText("Jahre");
  await personCard.click();
  await expect(page).toHaveURL(/\/people\/.+/);

  await page.getByRole("button", { name: "Bearbeiten" }).click();
  const image = await readFile("public/icon-192.png");
  await page.getByLabel("Profilbild auswählen").setInputFiles({ name: "profil.png", mimeType: "image/png", buffer: image });
  await expect(page.locator(".person-profile-hero .avatar-photo")).toBeVisible();

  await page.locator(".resource-attachment-form input[type=file]").setInputFiles({ name: "kontakt-notiz.txt", mimeType: "text/plain", buffer: Buffer.from("Private Notiz zum Kontakt") });
  await page.locator(".resource-attachment-form button[type=submit]").click();
  await expect(page.locator(".resource-attachment-list")).toContainText("kontakt-notiz.txt");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Herunterladen" }).click();
  expect((await downloadPromise).suggestedFilename()).toBe("kontakt-notiz.txt");
  await page.getByRole("button", { name: "kontakt-notiz.txt löschen" }).click();
  await expect(page.locator(".resource-attachment-list")).toHaveCount(0);

  await page.locator(".membership-create-form input[name=organization_name]").fill(organizationName);
  await page.locator(".membership-create-form").getByRole("button", { name: "Anlegen" }).click();
  await expect(page.getByRole("status")).toContainText("Verein gespeichert");
  await page.locator(".membership-form select[name=organization_id]").selectOption({ label: organizationName });
  await page.locator(".membership-form input[name=role]").fill("Mitglied");
  await page.locator(".membership-form").getByRole("button", { name: "Mitgliedschaft hinzufügen" }).click();
  await expect(page.locator(".organization-card")).toContainText(organizationName);
  await expect(page.locator(".organization-card")).toContainText("Mitglied");

  await page.goto("/people");
  await page.getByLabel("Filtern").selectOption("photo");
  await expect(page.locator(".person-card").filter({ hasText: parentName })).toBeVisible();
  await page.getByLabel("Personen suchen").fill("nicht vorhanden");
  await expect(page.locator("#people")).toContainText("Keine passenden Personen");

  await page.getByLabel("Personen suchen").fill("");
  await page.getByLabel("Filtern").selectOption("all");
  await page.setViewportSize({ width: 390, height: 844 });
  const cardPositions = await page.locator(".people-grid .person-card").evaluateAll(cards => cards.slice(0, 2).map(card => card.getBoundingClientRect().top));
  expect(cardPositions).toHaveLength(2);
  expect(cardPositions[0]).toBe(cardPositions[1]);
  const selfCard = page.locator(".person-card").filter({ hasText: "Du · eigenes Profil" });
  await selfCard.click();
  await page.getByRole("button", { name: "Bearbeiten" }).click();
  await page.locator(".membership-form select[name=organization_id]").selectOption({ label: organizationName });
  await page.locator(".membership-form").getByRole("button", { name: "Mitgliedschaft hinzufügen" }).click();
  await expect(page.locator(".organization-card").filter({ hasText: organizationName })).toContainText("Mitglied");
});

test("Profilbild lässt sich ohne Dateidialog aus der Zwischenablage einfügen", async ({ page }) => {
  await login(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await page.locator(".person-card").filter({ hasText: parentName }).click();
  await page.getByRole("button", { name: "Bild einfügen" }).click();
  const pasteField = page.getByLabel("Bild aus Zwischenablage einfügen");
  await expect(pasteField).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);

  const image = Array.from(await readFile("public/icon-192.png"));
  await page.evaluate(bytes => {
    const target = document.querySelector<HTMLTextAreaElement>(".photo-paste-field");
    if (!target) throw new Error("Zwischenablagefeld ist nicht verfügbar.");
    const clipboard = new DataTransfer();
    clipboard.items.add(new File([new Uint8Array(bytes)], "kopiertes-bild.png", { type: "image/png" }));
    target.dispatchEvent(new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true, cancelable: true }));
  }, image);

  await expect(page.locator(".photo-crop-window canvas")).toBeVisible();
  await page.getByRole("button", { name: "Bild übernehmen" }).click();
  await expect(page.getByRole("dialog", { name: "Profilbild zuschneiden" })).toHaveCount(0);
  await expect(page.locator(".person-profile-hero .avatar-photo")).toBeVisible();
});

test("Beziehung im gleichen Ablauf anlegen, Teilgeburtstag speichern und Telefonat protokollieren", async ({ page }) => {
  await login(page);
  await page.goto("/people");
  await page.locator("#people input[name=first_name]").fill(`E2E-Kontakt-${suffix}`);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await page.locator(".person-card").filter({ hasText: `E2E-Kontakt-${suffix}` }).click();
  await page.getByRole("button", { name: "Bearbeiten" }).click();

  await page.locator(".relationship-target-mode label").nth(1).click();
  await page.locator(".relationship-new-person input[name=new_first_name]").fill(`E2E-Neue-Person-${suffix}`);
  await page.locator(".relationship-new-person select[name=birthday_precision]").selectOption("month_day");
  await page.locator(".relationship-new-person input[name=birthday_month_day]").fill("2000-02-29");
  await page.locator(".relationship-form select[name=relationship_type]").selectOption("friend");
  await page.getByRole("button", { name: "Person anlegen und verbinden" }).click();
  await expect(page.locator(".relationship-card-grid")).toContainText(`E2E-Neue-Person-${suffix}`);

  await page.getByRole("button", { name: "Verlauf" }).click();
  await page.getByRole("button", { name: "Telefonat festhalten" }).click();
  await page.locator(".person-call-form textarea[name=notes]").fill("Über das Wochenende gesprochen");
  await page.locator(".person-call-form input[name=duration_minutes]").fill("8");
  await page.getByRole("button", { name: "Telefonat speichern" }).click();
  await expect(page.locator(".person-call-history")).toContainText("Über das Wochenende gesprochen");
  await expect(page.locator(".person-call-history")).toContainText("8 Minuten");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim())).toBe("#f6f5f2");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--bg").trim())).toBe("#171a18");
});

test("Anmeldung, Beziehungen, Chat-Gedächtnisfragen und PWA-Offline-Shell funktionieren", async ({ page }) => {
  await login(page);

  await page.goto("/people");
  const selfPerson = page.locator(".person-card").filter({ hasText: "Du · eigenes Profil" });
  await expect(selfPerson).toBeVisible();
  await selfPerson.click();
  await expect(page).toHaveURL(/\/people\/.+/);
  await page.goto("/");

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
  await page.locator("#people select[name=gender]").selectOption("male");
  await page.locator("#people input[name=first_name]").fill(parentName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await page.locator("#people select[name=gender]").selectOption("female");
  await expect(page.getByRole("button", { name: new RegExp(parentName) })).toBeVisible();
  await page.locator("#people input[name=first_name]").fill(childName);
  await page.getByRole("button", { name: "Person hinzufügen" }).click();
  await expect(page.getByRole("button", { name: new RegExp(childName) })).toBeVisible();

  await page.getByRole("button", { name: new RegExp(childName) }).click();
  await expect(page).toHaveURL(/\/people\/.+/);
  await page.locator(".relationship-form select[name=target_id]").selectOption({ label: parentName });
  await page.locator(".relationship-form select[name=relationship_type]").selectOption("child");
  await page.getByRole("button", { name: "Beziehung hinzufügen" }).click();
  await expect(page.locator(".person-profile")).toContainText(`${childName} ist Tochter von`);
  await expect(page.locator(".person-profile")).toContainText(`${parentName} ist Vater von`);

  await page.goto("/people");
  await page.getByRole("button", { name: new RegExp(parentName) }).click();
  await expect(page).toHaveURL(/\/people\/.+/);
  await page.locator(".owner-relationship-form select[name=relationship_type]").selectOption("colleague");
  await page.locator(".owner-relationship-form").getByRole("button", { name: "Beziehung speichern" }).click();
  await expect(page.locator(".person-profile")).toContainText(`Du kennst ${parentName} als Arbeitskollege`);

  await page.goto("/chat");
  await expect(page.getByRole("heading", { name: "Chat" })).toBeVisible();
  await page.getByLabel("Was möchtest du festhalten?").fill(chatCaptureText);
  await page.getByRole("button", { name: "Nachricht senden" }).click();
  await expect(page.locator(".chat-entry.assistant")).toBeVisible();
  await expect(page.locator(".capture-chat-result")).toContainText("Vorschläge aus deiner Eingabe");
  await page.goto("/inbox");
  await expect(page.locator(".inbox-panel")).not.toContainText(chatCaptureText);
  await page.goto("/chat");
  await expect(page.locator(".chat-transcript")).toContainText(chatCaptureText);
  await page.getByLabel("Was möchtest du festhalten?").fill(chatFollowUpText);
  await page.getByRole("button", { name: "Nachricht senden" }).click();
  await expect(page.locator(".chat-transcript")).toContainText(chatFollowUpText);

  await page.goto("/chat");
  await page.getByRole("button", { name: "Fragen" }).click();
  await expect(page.locator(".chat-transcript")).not.toContainText(chatCaptureText);
  await page.getByLabel("Deine Frage").fill(chatQuestionText);
  await page.getByRole("button", { name: "Frage stellen" }).click();
  await expect(page.locator(".chat-entry.assistant").last()).toBeVisible();
  await expect(page.locator(".chat-source").filter({ hasText: parentName }).first()).toBeVisible();
  await page.getByRole("button", { name: "Festhalten" }).click();
  await expect(page.locator(".chat-transcript")).toContainText(chatCaptureText);
  await expect(page.locator(".chat-transcript")).not.toContainText(chatQuestionText);
  await page.getByRole("button", { name: "Fragen" }).click();
  await expect(page.locator(".chat-transcript")).toContainText(chatQuestionText);
  await expect(page.locator(".chat-transcript")).not.toContainText(chatCaptureText);
  await expect(page.locator(".chat-history-note")).toContainText("40 Nachrichten");

  await page.goto("/planning");
  const eventForm = page.locator(".events-panel .event-form");
  await eventForm.locator("input[name=title]").fill(`E2E-Termin-${suffix}`);
  await eventForm.locator("input[name=starts_at]").fill("2027-04-01T14:30");
  const appointmentParticipants = eventForm.getByRole("combobox", { name: "Teilnehmende" });
  await appointmentParticipants.fill(parentName);
  await eventForm.getByRole("option", { name: parentName }).click();
  await appointmentParticipants.fill(childName);
  await eventForm.getByRole("option", { name: childName }).click();
  await expect(eventForm.locator(".person-picker-chip")).toHaveCount(2);
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
