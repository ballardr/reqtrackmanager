import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildSearchHit } from "../testing/searchFixtures";
import { SearchHitSummary } from "./SearchHitSummary";

const meta: Meta<typeof SearchHitSummary> = {
  title: "Components/SearchHitSummary",
  component: SearchHitSummary,
  args: { hit: buildSearchHit(), terms: ["volt"] },
};
export default meta;
type Story = StoryObj<typeof SearchHitSummary>;

/** A record in a project: its code is qualified by the project code, and the matched word is marked in the title. */
export const ProjectRecordWithTheMatchMarked: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ALPHA-REQ-001")).toBeInTheDocument();
    await expect(canvasElement.querySelector("mark")?.textContent).toBe("Volt");
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();
    await expect(canvas.getByText("in Alpha")).toBeInTheDocument();
  },
};

/** An organisation-owned record has no project: it is qualified by the organisation code and says so. */
export const OrganisationOwnedRecord: Story = {
  args: {
    hit: buildSearchHit({ type: "persona", type_label: "Persona", code: "PER-001", project_id: null, project_name: null, project_code: null }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ACME-PER-001")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation record")).toBeInTheDocument();
  },
};

/** A code that is not a `PREFIX-nnn` code (a clause reference) is shown as it is, never qualified. */
export const AClauseReferenceIsNotQualified: Story = {
  args: { hit: buildSearchHit({ type: "compliance_requirement", type_label: "Compliance standard clause", code: "A.5.15", project_id: null, project_name: null, project_code: null }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("A.5.15")).toBeInTheDocument();
  },
};

/** The page shows the snippet of the first matching field; archived records say so. */
export const SnippetAndArchivedBadge: Story = {
  args: {
    showSnippet: true,
    hit: buildSearchHit({
      is_archived: true, snippet: { field_key: "description", field_label: "Description", text: "supply voltage sag", ranges: [[7, 12]] },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Archived")).toBeInTheDocument();
    await expect(canvas.getByText(/Description:/)).toBeInTheDocument();
    await expect(canvasElement.querySelectorAll("mark")).toHaveLength(2); // the title's match and the snippet's
  },
};

/** A 200-character title wraps inside its box. */
export const LongTitleWraps: Story = {
  args: { hit: buildSearchHit({ title: "voltage ".repeat(30).trim() }) },
  play: async ({ canvasElement }) => {
    await expect((canvasElement.firstElementChild as HTMLElement).scrollWidth).toBeLessThanOrEqual((canvasElement.firstElementChild as HTMLElement).clientWidth + 1);
  },
};

/** The dropdown's compact density is one line: code, truncated title (full title in the tooltip) and the place. */
export const CompactIsOneLine: Story = {
  args: {
    density: "compact",
    hit: buildSearchHit({ title: "voltage ".repeat(30).trim() }),
  },
  decorators: [(Story) => <div style={{ width: 320 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    const row = canvasElement.querySelector(".search-hit-compact") as HTMLElement;
    await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
    await expect(row.getBoundingClientRect().height).toBeLessThan(28);
    await expect(within(canvasElement).getByText("ALPHA-REQ-001")).toBeInTheDocument();
    await expect(within(canvasElement).getByText("in Alpha")).toBeInTheDocument();
    await expect(within(canvasElement).queryByText("Draft")).toBeNull(); // status stays on the results page
  },
};
