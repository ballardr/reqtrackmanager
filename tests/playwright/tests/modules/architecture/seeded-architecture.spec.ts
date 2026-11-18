import { expect, test } from "@playwright/test";

import { loginAs, openProject, PERSONAS, PROJECT_NAMES } from "../../e2e-workflows/helpers";

/**
 * Job to be done: an architect opens a product whose architecture is already recorded and finds its parts. This browses the fixed
 * fixture the E2E seed builds (a software service and a hardware board joined by one connection, a diagram and a state machine of
 * the board). It only reads: every other architecture spec builds its own disposable organisation, so nothing here may edit the
 * fixture.
 */
test.describe("System Architecture: seeded fixture", () => {
  test("the seeded software service, hardware board, connection, diagram and state machine are listed", async ({ page }) => {
    await loginAs(page, PERSONAS.orgAdminGamma.email);
    await openProject(page, PROJECT_NAMES.eta1);
    const projectId = new URL(page.url()).pathname.split("/")[2];
    const tab = (name: string) => page.goto(`/projects/${projectId}/modules/architecture?tab=${name}`);

    await test.step("the Elements tab lists the service and the board", async () => {
      await tab("elements");
      const elements = page.getByRole("table", { name: "Elements" });
      await expect(elements.getByText("E2E Mission service")).toBeVisible();
      await expect(elements.getByText("E2E Flight controller board")).toBeVisible();
    });

    await test.step("the Connections tab lists the link between them", async () => {
      await tab("connections");
      await expect(page.getByRole("table", { name: "Connections" }).getByText("E2E Telemetry link")).toBeVisible();
    });

    await test.step("the Diagrams tab lists the block diagram and the state machine", async () => {
      await tab("diagrams");
      await expect(page.getByText("E2E Flight system overview")).toBeVisible();
      await expect(page.getByText("E2E Flight controller modes")).toBeVisible();
    });
  });
});
