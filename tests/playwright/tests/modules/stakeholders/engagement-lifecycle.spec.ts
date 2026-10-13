import { expect, test, type Page } from "@playwright/test";

import { installCleanupHook } from "../../e2e-workflows/helpers";
import { API_BASE_URL, setUpOrg } from "./helpers";

// Deletes this file's disposable orgs after each test (see deleteOrgOnCleanup).
installCleanupHook();

/**
 * Job to be done: docs/plans/module-02-stakeholders-and-personas-plan.md
 * Phase 5's exit criteria — Playwright e2e coverage for the Engagement UI
 * (`frontend/src/modules/stakeholders/`) against a real backend: log, edit and
 * permanently delete an engagement; add participants and covered Personas;
 * aim it at a Stakeholder group (a snapshot of members); log a contact from a
 * Stakeholder's page and see the timeline and "Last engaged"; record what an
 * engagement raised; and the research extras (prompts, anonymous participants,
 * findings) appearing only once the sub-component is on; and the compact
 * page layout: every "add" is a (+) button opening its form on demand, and the
 * facilitator is assigned from a popover rather than an always-open search box.
 *
 * Each test builds its own disposable org (see `./helpers.ts`), so none depends
 * on seeded state or on another test having run.
 */

type Headers = Record<string, string>;

async function post<T>(page: Page, url: string, headers: Headers, data: object): Promise<T> {
  const resp = await page.request.post(url, { headers, data });
  expect(resp.ok(), await resp.text()).toBeTruthy();
  return (await resp.json().catch(() => ({}))) as T;
}

const projectBase = (projectId: string) => `${API_BASE_URL}/api/v1/projects/${projectId}/modules/stakeholders`;
const today = () => new Date().toISOString().slice(0, 10);

test.describe("Stakeholders & Personas: Engagements", () => {
  test("logs, edits and permanently deletes an engagement", async ({ page }) => {
    const { suffix, project } = await setUpOrg(page, "EngLife");
    const title = `Quarterly review ${suffix}`;

    await page.goto(`/projects/${project.id}`);
    await page.getByRole("link", { name: "Engagements", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/engagements$`));
    await expect(page.getByText("No engagements logged for this project yet.")).toBeVisible();

    // --- Log (a Modal layer); the channel renders through its label map.
    await page.getByRole("button", { name: "Log engagement" }).click();
    const dialog = page.getByRole("dialog", { name: "Log engagement" });
    await dialog.getByLabel("Engagement title").fill(title);
    await dialog.getByLabel("Channel").selectOption("workshop");
    await dialog.getByLabel("Summary").fill("Agreed the evidence list.");
    await dialog.getByLabel("Notes").fill("Pat asked for the traceability export.");
    await dialog.getByLabel("Consent recorded").check();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Engagement logged.")).toBeVisible();
    const row = page.locator("tr", { hasText: title });
    await expect(row.getByText("Workshop", { exact: true })).toBeVisible();
    await expect(row.getByText(today())).toBeVisible();

    await page.getByRole("button", { name: title }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/engagements/[^/]+$`));
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    await expect(page.getByText("Pat asked for the traceability export.")).toBeVisible();
    await expect(page.getByTestId("consent")).toHaveText("Consent recorded: Yes");
    // The research extras are off by default: their blocks are not offered.
    await expect(page.getByText("Session prompts", { exact: true })).toHaveCount(0);

    // --- Edit as a layer.
    await page.getByRole("button", { name: "Edit", exact: true }).click();
    const edit = page.getByRole("dialog", { name: `Edit ${title}` });
    await edit.getByLabel("Summary").fill("Evidence list agreed and dated.");
    await edit.getByLabel("Retain until").fill("2020-01-01");
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Engagement updated.")).toBeVisible();
    await expect(page.getByText("Evidence list agreed and dated.")).toBeVisible();
    // A retain-until date in the past flags the engagement for review; nothing is deleted.
    await expect(page.getByText("Retention review due")).toBeVisible();

    // --- Permanent delete is a tier-2 confirm needing the exact title.
    await page.getByRole("button", { name: "Delete permanently" }).click();
    const confirm = page.getByRole("dialog", { name: `Permanently delete ${title}?` });
    const confirmButton = confirm.getByRole("button", { name: "Delete permanently" });
    await expect(confirmButton).toBeDisabled();
    await confirm.getByRole("textbox").fill(title);
    await confirmButton.click();
    await expect(page.getByText("Engagement permanently deleted.")).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/modules/stakeholders/engagements$`));
    await expect(page.getByText("No engagements logged for this project yet.")).toBeVisible();
  });

  test("adds and removes participants and covered Personas, and the list filters by participant", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "EngPeople");
    const base = projectBase(project.id);
    const patName = `Pat Regulator ${suffix}`;
    const samName = `Sam Client ${suffix}`;
    const personaName = `Field Technician ${suffix}`;
    await post(page, `${base}/stakeholders`, adminHeaders, { name: patName });
    await post(page, `${base}/stakeholders`, adminHeaders, { name: samName });
    await post(page, `${base}/personas`, adminHeaders, { name: personaName });
    const title = `Kick-off ${suffix}`;
    const other = `Unrelated call ${suffix}`;
    const engagement = await post<{ id: string }>(page, `${base}/engagements`, adminHeaders, { title, channel: "meeting", engagement_date: today() });
    await post(page, `${base}/engagements`, adminHeaders, { title: other, channel: "call", engagement_date: today() });

    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}`);
    await expect(page.getByText("No Stakeholders are recorded as taking part.")).toBeVisible();

    await page.getByRole("button", { name: "Add to Participants" }).click();
    const addParticipant = page.getByRole("dialog", { name: "Add to Participants" });
    await addParticipant.getByLabel("Stakeholder to add").selectOption({ label: patName });
    await addParticipant.getByRole("button", { name: "Add", exact: true }).click();
    // The participants list and the Links panel both name Pat, so take the first.
    await expect(page.getByRole("link", { name: patName }).first()).toBeVisible();
    // Pat takes part, so is no longer offered.
    await page.getByRole("button", { name: "Add to Participants" }).click();
    await expect(page.getByRole("dialog", { name: "Add to Participants" }).getByLabel("Stakeholder to add").locator("option", { hasText: patName })).toHaveCount(0);
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "Add to Personas covered" }).click();
    const addPersona = page.getByRole("dialog", { name: "Add to Personas covered" });
    await addPersona.getByLabel("Persona covered").selectOption({ label: personaName });
    await addPersona.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("link", { name: personaName }).first()).toBeVisible();

    // --- The list filters by participant (applied by the API).
    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements`);
    await expect(page.getByRole("button", { name: other })).toBeVisible();
    await page.getByLabel("Participant").selectOption({ label: patName });
    await expect(page.getByRole("button", { name: other })).toHaveCount(0);
    await expect(page.getByRole("button", { name: title })).toBeVisible();

    // --- Remove the participant behind a tier-1 confirm.
    await page.getByRole("button", { name: title }).click();
    await page.getByRole("button", { name: `Remove ${patName}` }).click();
    await page.getByRole("dialog", { name: `Remove ${patName}?` }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Link removed.")).toBeVisible();
    await expect(page.getByText("No Stakeholders are recorded as taking part.")).toBeVisible();
  });

  test("aiming at a Stakeholder group copies its members in as a snapshot", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "EngAudience");
    const base = projectBase(project.id);
    const patName = `Pat ${suffix}`;
    const samName = `Sam ${suffix}`;
    const groupName = `Acme ${suffix}`;
    const pat = await post<{ id: string }>(page, `${base}/stakeholders`, adminHeaders, { name: patName });
    const sam = await post<{ id: string }>(page, `${base}/stakeholders`, adminHeaders, { name: samName });
    const group = await post<{ id: string }>(page, `${base}/stakeholder-groups`, adminHeaders, { name: groupName });
    await post(page, `${base}/stakeholder-groups/${group.id}/members`, adminHeaders, { stakeholder_id: pat.id });
    await post(page, `${base}/stakeholder-groups/${group.id}/members`, adminHeaders, { stakeholder_id: sam.id });
    const engagement = await post<{ id: string }>(page, `${base}/engagements`, adminHeaders, {
      title: `Acme workshop ${suffix}`, channel: "workshop", engagement_date: today(),
    });

    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}`);
    await expect(page.getByText("Not aimed at a group.")).toBeVisible();
    await page.getByRole("button", { name: "Add to Audience groups" }).click();
    const addAudience = page.getByRole("dialog", { name: "Add everyone in a group" });
    await addAudience.getByRole("button", { name: "Groups to add" }).click();
    await page.getByRole("group", { name: "Groups to add" }).getByRole("checkbox", { name: groupName }).check();
    // Close the tree through its own trigger (Escape would close the modal as well).
    await addAudience.getByRole("button", { name: "Groups to add" }).click();
    await addAudience.getByRole("button", { name: "Add everyone in group" }).click();
    await expect(page.getByText("Added 2 people as participants.")).toBeVisible();
    await expect(page.getByRole("link", { name: patName }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: samName }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: `Remove audience ${groupName}` })).toBeVisible();

    // --- A no-show is removed individually; removing the audience keeps everyone else.
    await page.getByRole("button", { name: `Remove ${samName}` }).click();
    await page.getByRole("dialog", { name: `Remove ${samName}?` }).getByRole("button", { name: "Remove" }).click();
    await expect(page.getByRole("link", { name: samName })).toHaveCount(0);
    await page.getByRole("button", { name: `Remove audience ${groupName}` }).click();
    const dialog = page.getByRole("dialog", { name: `Remove audience ${groupName}?` });
    await expect(dialog.getByText(/The people it added stay as participants/)).toBeVisible();
    await dialog.getByRole("button", { name: "Remove" }).click();
    await expect(page.getByText("Audience removed.")).toBeVisible();
    await expect(page.getByRole("link", { name: patName }).first()).toBeVisible();
  });

  test("logs a contact from a Stakeholder's page and shows the timeline and last engaged", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "EngContact");
    const base = projectBase(project.id);
    const patName = `Pat Regulator ${suffix}`;
    const stakeholder = await post<{ id: string }>(page, `${base}/stakeholders`, adminHeaders, { name: patName });

    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await expect(page.getByTestId("last-engaged")).toHaveText("Last engaged: Never");
    await expect(page.getByText("No engagements logged yet.")).toBeVisible();

    await page.getByRole("button", { name: "Log contact" }).click();
    const dialog = page.getByRole("dialog", { name: `Log contact with ${patName}` });
    // The quick add keeps only the fields a one-line contact needs.
    await expect(dialog.getByLabel("Notes")).toHaveCount(0);
    await dialog.getByLabel("Engagement title").fill(`Evidence email ${suffix}`);
    await expect(dialog.getByLabel("Channel")).toHaveValue("email");
    await dialog.getByLabel("Summary").fill("Sent the export.");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Contact logged.")).toBeVisible();
    await expect(page.getByRole("link", { name: `${today()} · Email · Evidence email ${suffix}` })).toBeVisible();

    // --- Last engaged reads the derived date, here and in the list column.
    await page.reload();
    await expect(page.getByTestId("last-engaged")).toHaveText(`Last engaged: ${today()}`);
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders`);
    await expect(page.locator("tr", { hasText: patName }).getByText(today())).toBeVisible();

    // --- The link opens the engagement, which lists Pat as a participant.
    await page.goto(`/projects/${project.id}/modules/stakeholders/stakeholders/${stakeholder.id}`);
    await page.getByRole("link", { name: `${today()} · Email · Evidence email ${suffix}` }).click();
    await expect(page.getByRole("heading", { name: `Evidence email ${suffix}` })).toBeVisible();
    await expect(page.getByRole("link", { name: patName }).first()).toBeVisible();
  });

  test("records what an engagement raised and links it to the Need", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "EngOutcome");
    const base = projectBase(project.id);
    const needName = `Work offline ${suffix}`;
    const need = await post<{ id: string }>(page, `${base}/needs`, adminHeaders, { name: needName });
    const engagement = await post<{ id: string }>(page, `${base}/engagements`, adminHeaders, {
      title: `Site visit ${suffix}`, channel: "meeting", engagement_date: today(),
    });

    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}`);
    await expect(page.getByText("Nothing raised or answered yet.")).toBeVisible();
    await page.getByRole("button", { name: "Add to Raised and answered" }).click();
    const addOutcome = page.getByRole("dialog", { name: "Record an outcome" });
    await addOutcome.getByLabel("Outcome type").selectOption({ label: "Stakeholder Need" });
    await addOutcome.getByLabel("Outcome record").selectOption({ label: needName });
    await addOutcome.getByRole("button", { name: "Add outcome" }).click();
    await expect(page.getByText("Outcome recorded.")).toBeVisible();
    await expect(page.getByText("Raised · Stakeholder Need:")).toBeVisible();

    // --- The Need is reachable from the outcome, and the engagement from the Need's Links panel.
    await page.getByRole("link", { name: needName }).first().click();
    await expect(page).toHaveURL(new RegExp(`/modules/stakeholders/needs/${need.id}$`));
    await expect(page.getByRole("link", { name: `Site visit ${suffix}` })).toBeVisible();
  });

  test("shows the research extras only when the sub-component is on, and a finding link opens its engagement", async ({ page }) => {
    const { suffix, org, project, adminHeaders } = await setUpOrg(page, "EngResearch");
    const base = projectBase(project.id);
    const personaName = `Field Technician ${suffix}`;
    await post(page, `${base}/personas`, adminHeaders, { name: personaName });
    const engagement = await post<{ id: string }>(page, `${base}/engagements`, adminHeaders, {
      title: `Focus group ${suffix}`, channel: "focus_group", engagement_date: today(),
    });
    const url = `/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}`;

    await page.goto(url);
    await expect(page.getByRole("heading", { name: `Focus group ${suffix}` })).toBeVisible();
    await expect(page.getByText("Session prompts", { exact: true })).toHaveCount(0);

    // --- Switch the research extras on (the organisation's default, which the project inherits).
    const resp = await page.request.put(
      `${API_BASE_URL}/api/v1/orgs/${org.id}/modules/stakeholders/subcomponents/research_extras`,
      { headers: adminHeaders, data: { enabled: true } },
    );
    expect(resp.ok(), await resp.text()).toBeTruthy();
    await page.reload();
    await expect(page.getByText("Session prompts", { exact: true })).toBeVisible();

    // --- A session prompt with notes.
    await page.getByRole("button", { name: "Add to Session prompts" }).click();
    const addPrompt = page.getByRole("dialog", { name: "Add to Session prompts" });
    await addPrompt.getByLabel("New session prompt").fill("Walk me through an inspection");
    await addPrompt.getByRole("button", { name: "Add prompt" }).click();
    await expect(page.getByText("Prompt added.")).toBeVisible();
    await page.getByRole("button", { name: "Edit Walk me through an inspection" }).click();
    const promptDialog = page.getByRole("dialog", { name: "Edit session prompt" });
    await promptDialog.getByLabel("Response notes").fill("Starts with the checklist.");
    await promptDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Starts with the checklist.")).toBeVisible();
    // Rows of different length keep their action buttons in one column.
    await page.getByRole("button", { name: "Add to Session prompts" }).click();
    const secondPrompt = page.getByRole("dialog", { name: "Add to Session prompts" });
    await secondPrompt.getByLabel("New session prompt").fill("What would make the checklist worth opening, if anything at all?");
    await secondPrompt.getByRole("button", { name: "Add prompt" }).click();
    const edges = async (name: string) => (await page.getByRole("button", { name }).boundingBox())!.x;
    expect(await edges("Delete Walk me through an inspection"))
      .toBe(await edges("Delete What would make the checklist worth opening, if anything at all?"));

    // --- An anonymous participant with a Persona, labelled rather than named.
    await page.getByRole("button", { name: "Add to Anonymous participants" }).click();
    const addAnonymous = page.getByRole("dialog", { name: "Add to Anonymous participants" });
    await addAnonymous.getByLabel("Participant label").fill("Participant 1");
    await addAnonymous.getByLabel("Persona represented").selectOption({ label: personaName });
    await addAnonymous.getByRole("button", { name: "Add participant" }).click();
    await expect(page.getByText(`Participant 1 · ${personaName}`)).toBeVisible();

    // --- A finding.
    await page.getByRole("button", { name: "Add finding" }).click();
    const findingDialog = page.getByRole("dialog", { name: "New finding" });
    await findingDialog.getByLabel("Finding title").fill("Technicians skip the checklist offline");
    await findingDialog.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Finding added.")).toBeVisible();
    // (The title also appears, hidden, in the collapsed Links panel group, so name the card's own heading.)
    await expect(page.locator("strong", { hasText: "Technicians skip the checklist offline" })).toBeVisible();
    // It gets a project-scoped code, and links through the shared "Add a link" dialog like any other record.
    const card = page.getByLabel("Finding Technicians skip the checklist offline");
    await expect(card.getByText("FND-001")).toBeVisible();
    const needName = `Work offline ${suffix}`;
    await post(page, `${base}/needs`, adminHeaders, { name: needName });
    await card.getByRole("button", { name: "Add link" }).click();
    const linkDialog = page.getByRole("dialog", { name: "Add a link" });
    await linkDialog.getByLabel("Link to").selectOption({ label: "Stakeholder need" });
    await linkDialog.getByLabel("Record").selectOption({ label: needName });
    await linkDialog.getByLabel("Relationship").selectOption({ label: "Raised" });
    await linkDialog.getByRole("button", { name: "Add link" }).click();
    await expect(page.getByText("Link added.").last()).toBeVisible();
    await expect(card.getByRole("link", { name: needName })).toBeVisible();
    // The engagement's own Links panel lists its findings, but starts with that group collapsed.
    const findingsGroup = page.getByRole("button", { name: "Research finding", exact: true });
    await expect(findingsGroup).toHaveAttribute("aria-expanded", "false");
    await findingsGroup.click();
    await expect(findingsGroup).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("link", { name: /FND-001 Technicians skip the checklist offline/ }).first()).toBeVisible();

    // --- The list counts the anonymous participant, and a finding link redirects to its engagement.
    const findings = await (await page.request.get(`${base}/findings`, { headers: adminHeaders })).json();
    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements`);
    await expect(page.locator("tr", { hasText: `Focus group ${suffix}` }).getByText("Focus group", { exact: true })).toBeVisible();
    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements?finding=${findings[0].id}`);
    await expect(page).toHaveURL(new RegExp(`/engagements/${engagement.id}#finding-${findings[0].id}$`));
    await expect(page.getByRole("heading", { name: `Focus group ${suffix}` })).toBeVisible();
    await expect(page.getByLabel("Finding Technicians skip the checklist offline")).toBeInViewport();
  });
  test("the page stays compact: adds open on demand and the facilitator is assigned from a (+)", async ({ page }) => {
    const { suffix, project, adminHeaders } = await setUpOrg(page, "EngCompact");
    const engagement = await post<{ id: string }>(page, `${projectBase(project.id)}/engagements`, adminHeaders, {
      title: `Compact ${suffix}`, channel: "call", engagement_date: today(),
    });

    await page.goto(`/projects/${project.id}/modules/stakeholders/engagements/${engagement.id}`);
    // No add form is open on the page: no pickers, only (+) buttons.
    await expect(page.getByLabel("Stakeholder to add")).toHaveCount(0);
    await expect(page.getByLabel("Engagement facilitator")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add to Facilitators" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Add to Participants" })).toBeVisible();

    // Facilitators are a list: add a user and a group from the (+), then remove one with its "x".
    await post(page, `${API_BASE_URL}/api/v1/projects/${project.id}/groups`, adminHeaders, { name: `Squad ${suffix}` });
    await page.reload();
    await page.getByRole("button", { name: "Add to Facilitators" }).click();
    let popover = page.getByRole("dialog", { name: "Add to Facilitators" });
    await popover.getByLabel("Engagement facilitator").fill("Admin");
    await popover.getByRole("option").first().click();
    await expect(page.getByText("Facilitators updated.")).toBeVisible();
    await page.getByRole("button", { name: "Add to Facilitators" }).click();
    popover = page.getByRole("dialog", { name: "Add to Facilitators" });
    await popover.getByLabel("Engagement facilitator").fill(`Squad ${suffix}`);
    await popover.getByRole("option").first().click();
    await expect(page.getByRole("button", { name: /^Remove E2E EngCompact Admin/ })).toBeVisible();
    await expect(page.getByRole("button", { name: `Remove Squad ${suffix}` })).toBeVisible();
    await page.getByRole("button", { name: `Remove Squad ${suffix}` }).click();
    await expect(page.getByRole("button", { name: `Remove Squad ${suffix}` })).toHaveCount(0);
    await page.getByRole("button", { name: /^Remove E2E EngCompact Admin/ }).click();
    await expect(page.getByText("Nobody is recorded as running it.")).toBeVisible();
  });
});
