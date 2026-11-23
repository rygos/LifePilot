import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const username = process.env.LIFEPILOT_E2E_USERNAME ?? process.env.LIFE_PILOT_BOOTSTRAP_USERNAME;
const password = process.env.LIFEPILOT_E2E_PASSWORD ?? process.env.LIFE_PILOT_BOOTSTRAP_PASSWORD;
const apiUrl = process.env.LIFEPILOT_E2E_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const suffix = randomUUID().slice(0, 8);

async function signIn(page: Page): Promise<void> {
  if (!username || !password) throw new Error("Für diesen Browser-Test fehlen Benutzername oder Passwort.");
  await page.goto("/");
  await page.getByLabel("Benutzername").fill(username);
  await page.getByLabel("Passwort").fill(password);
  await page.getByRole("button", { name: "Anmelden" }).click();
  await expect(page.getByRole("heading", { name: "Übersicht" })).toBeVisible();
}

test("Stammbaum zeigt mehrere Generationen und öffnet Personenprofile", async ({ page, request }) => {
  await signIn(page);
  const session = await request.post(`${apiUrl}/api/auth/login`, { data: { username, password } });
  expect(session.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await session.json()).access_token as string}` };
  const ids: string[] = [];
  const makePerson = async (first_name: string) => {
    const response = await request.post(`${apiUrl}/api/people`, { headers, data: { first_name: `${first_name}-${suffix}`, last_name: "Diagramm" } });
    expect(response.status()).toBe(201);
    const person = await response.json() as { id: string };
    ids.push(person.id);
    return person;
  };
  try {
    const grandparent = await makePerson("Großelternteil");
    const parent = await makePerson("Elternteil");
    const root = await makePerson("Ausgangspunkt");
    const partner = await makePerson("Partnerperson");
    const child = await makePerson("Nachkomme");
    const sibling = await makePerson("Geschwister");
    const relation = async (source: { id: string }, target: { id: string }, relationship_type: string) => {
      const response = await request.post(`${apiUrl}/api/relationships`, { headers, data: { source_person_id: source.id, target_person_id: target.id, relationship_type } });
      expect(response.status()).toBe(201);
    };
    await relation(grandparent, parent, "parent");
    await relation(root, parent, "child");
    await relation(root, partner, "spouse");
    await relation(root, child, "parent");
    await relation(partner, child, "parent");
    await relation(root, sibling, "parent");
    await relation(partner, sibling, "parent");
    await relation(child, sibling, "sibling");

    await page.goto(`/people/${root.id}`);
    await expect(page.getByRole("heading", { level: 2, name: new RegExp(`Ausgangspunkt-${suffix}`) })).toBeVisible();
    await page.getByRole("button", { name: "Stammbaum anzeigen" }).click();
    const dialog = page.getByRole("dialog", { name: new RegExp("Stammbaum von") });
    await expect(dialog).toContainText(`Großelternteil-${suffix}`);
    await expect(dialog).toContainText(`Elternteil-${suffix}`);
    await expect(dialog).toContainText(`Nachkomme-${suffix}`);
    await expect(dialog).toContainText(`Geschwister-${suffix}`);
    await expect(dialog.locator(".family-tree-edge")).toHaveCount(3);
    await expect(dialog.locator(".family-tree-edge-label")).toHaveCount(0);
    const childCards = dialog.locator(".family-tree-node").filter({ hasText: new RegExp(`(Nachkomme|Geschwister)-${suffix}`) });
    const childBoxes = await Promise.all([childCards.nth(0).boundingBox(), childCards.nth(1).boundingBox()]);
    if (!childBoxes[0] || !childBoxes[1]) throw new Error("Die Geschwisterkarten sind nicht sichtbar.");
    expect(Math.abs(childBoxes[0].y - childBoxes[1].y)).toBeLessThanOrEqual(142);
    await dialog.getByRole("link", { name: new RegExp(`Nachkomme-${suffix}`) }).click();
    await expect(page).toHaveURL(new RegExp(`/people/${child.id}$`));
  } finally {
    for (const id of ids) await request.delete(`${apiUrl}/api/people/${id}`, { headers });
  }
});
