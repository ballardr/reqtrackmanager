import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { CodePrefixRow } from "../api/types";
import { buildUser, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { RecordCodePrefixPanel } from "./RecordCodePrefixPanel";

const row = (artefact_type: string, label: string, prefix: string, extra: Partial<CodePrefixRow> = {}): CodePrefixRow => ({
  artefact_type, label, module_key: null, module_name: null, default_prefix: prefix, own_prefix: null, prefix, source: "default", inherited_prefix: prefix,
  inherited_source: "default", ...extra,
});

const ROWS: CodePrefixRow[] = [
  row("requirement_action", "Action", "ACT"),
  row("change_request", "Change request", "CR"),
  row("decision", "Decision", "DEC"),
];

/** The prefix new records of each type are numbered with, for one tier: an organisation or a project. */
const meta: Meta<typeof RecordCodePrefixPanel> = {
  title: "Components/RecordCodePrefixPanel",
  component: RecordCodePrefixPanel,
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof RecordCodePrefixPanel>;

const MODULE_ROWS: CodePrefixRow[] = [
  row("decision", "Decision", "DEC", { module_key: "decisions", module_name: "Decision Management" }),
  row("risk", "Risk", "RSK", { module_key: "risk", module_name: "Risk Management", own_prefix: "RISK", prefix: "RISK", source: "project" }),
  row("risk_control", "Risk control", "CTL", { module_key: "risk", module_name: "Risk Management" }),
];

/** A project inheriting a prefix shows it as the placeholder and says which tier it comes from; nothing is dirty. */
export const ProjectShowsInheritedPrefixesAsPlaceholders: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      ROWS[0],
      row("change_request", "Change request", "CR", { prefix: "CHG", source: "organization", inherited_prefix: "CHG", inherited_source: "organization" }),
      row("decision", "Decision", "DEC", { prefix: "ADR", source: "parent_project", inherited_prefix: "ADR", inherited_source: "parent_project" }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const decision = await canvas.findByRole("textbox", { name: "Prefix for Decision" });
    await expect(decision).toHaveValue("");
    await expect(decision).toHaveAttribute("placeholder", "ADR");
    await expect(canvas.getByText("Parent project")).toBeInTheDocument();
    await expect(canvas.getByText("Organisation")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save the prefix for Decision" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Use the inherited prefix for Decision" })).toBeDisabled();
  },
};

/** Typing a prefix enables Save only for two to five letters; the value is upper-cased as it is typed. */
export const SavingSendsOnePrefixForOneType: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ROWS);
    spyOn(api, "put").mockResolvedValue(row("decision", "Decision", "DEC", { own_prefix: "ADR", prefix: "ADR", source: "project" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByRole("textbox", { name: "Prefix for Decision" });
    const save = canvas.getByRole("button", { name: "Save the prefix for Decision" });
    await userEvent.type(input, "a");
    await expect(save).toBeDisabled();
    await userEvent.type(input, "dr");
    await expect(input).toHaveValue("ADR");
    await expect(save).toBeEnabled();
    await userEvent.type(input, "xyz");
    await expect(input).toHaveValue("ADRXY");
    await userEvent.clear(input);
    await userEvent.type(input, "adr");
    await userEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/code-prefixes/decision", { prefix: "ADR" }));
  },
};

/** A prefix the project set can be cleared, which returns to the inherited value; a refusal shows the server's message. */
export const ClearingReturnsToTheInheritedValue: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      ROWS[0], ROWS[1],
      row("decision", "Decision", "DEC", { own_prefix: "ADR", prefix: "ADR", source: "project", inherited_prefix: "DEC" }),
    ]);
    spyOn(api, "delete").mockResolvedValue(ROWS[2]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("textbox", { name: "Prefix for Decision" })).toHaveValue("ADR");
    await userEvent.click(canvas.getByRole("button", { name: "Use the inherited prefix for Decision" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/project-1/code-prefixes/decision"));
  },
};

/** The organisation tier writes to the organisation endpoint and has no parent to inherit from. */
export const OrganisationTierSavesToTheOrganisation: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ROWS);
    spyOn(api, "put").mockResolvedValue(ROWS[2]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "Prefix for Decision" }), "adr");
    await userEvent.click(canvas.getByRole("button", { name: "Save the prefix for Decision" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/code-prefixes/decision", { prefix: "ADR" }));
  },
};

/** Without the right to change them, the prefixes are shown and cannot be edited. */
export const ReadOnlyWithoutEditRight: Story = {
  args: { scope: { kind: "project", projectId: "project-1" }, canEdit: false },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ROWS);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("textbox", { name: "Prefix for Decision" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: /Save the prefix/ })).not.toBeInTheDocument();
  },
};

/** A load failure shows the message instead of an empty table. */
export const LoadFailure: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Boom"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/Boom|Could not load the record code prefixes/)).toBeInTheDocument();
  },
};

/** Core types are in an open section; each module's types are in a folded section of its own, and a folded section that
 *  holds a prefix this tier set shows how many, so an override is visible without opening it. */
export const SectionsByModuleShowOverridesWhenFolded: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([ROWS[0], ROWS[1], ...MODULE_ROWS]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("textbox", { name: "Prefix for Change request" })).toBeVisible();
    await expect(canvas.getByText("Core")).toBeInTheDocument();
    await expect(canvas.getByText("2 types")).toBeInTheDocument();
    await expect(canvas.getByText("1 custom")).toBeInTheDocument();
    await expect(canvas.queryByRole("textbox", { name: "Prefix for Risk" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Risk Management section" }));
    await expect(await canvas.findByRole("textbox", { name: "Prefix for Risk" })).toHaveValue("RISK");
    await expect(canvas.getByRole("textbox", { name: "Prefix for Risk control" })).toHaveValue("");
    await expect(canvas.queryByRole("textbox", { name: "Prefix for Decision" })).not.toBeInTheDocument();
  },
};

/** A prefix is edited and cleared inside a module's section like in the Core one. */
export const SettingAPrefixInsideAModuleSection: Story = {
  args: { scope: { kind: "organization", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([ROWS[0], ...MODULE_ROWS]);
    spyOn(api, "put").mockResolvedValue(MODULE_ROWS[0]);
    spyOn(api, "delete").mockResolvedValue(MODULE_ROWS[1]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Decision Management section" }));
    await userEvent.type(await canvas.findByRole("textbox", { name: "Prefix for Decision" }), "adr");
    await userEvent.click(canvas.getByRole("button", { name: "Save the prefix for Decision" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/code-prefixes/decision", { prefix: "ADR" }));
    await userEvent.click(canvas.getByRole("button", { name: "Risk Management section" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Use the inherited prefix for Risk" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1/code-prefixes/risk"));
  },
};
