import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ScoringScheme } from "../api/scoring";
import { buildCustomCriteriaScheme, buildScoringScheme, withToast } from "../testing/storybook-helpers";
import { ProjectScoringSettings } from "./ProjectScoringSettings";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/scoring-schemes/pain_point`;

function mockProjectApis(initial: ScoringScheme) {
  let scheme = initial;
  spyOn(api, "get").mockImplementation(async () => scheme);
  spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/default-model")) {
      const model = (body as { model: string | null }).model;
      scheme = model
        ? { ...scheme, default_model_key: model, default_model_source: "project" }
        : { ...scheme, default_model_key: "sxfxc", default_model_source: "org" };
    } else {
      const bands = (body as { bands: ScoringScheme["models"][number]["bands"] | null }).bands;
      const modelKey = path.split("/models/")[1].split("/")[0];
      scheme = { ...scheme, models: scheme.models.map((m) => (m.key === modelKey
        ? { ...m, bands: bands ?? initial.models[0].bands, bands_source: bands ? "project" : "org" } : m)) };
    }
    return scheme;
  });
}

const meta: Meta<typeof ProjectScoringSettings> = {
  title: "Components/Scoring/ProjectScoringSettings",
  component: ProjectScoringSettings,
  args: { projectId: PROJECT_ID, schemeKey: "pain_point" },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectScoringSettings>;

const inherited = () => buildScoringScheme({
  default_model_source: "org",
  models: buildScoringScheme().models.map((m) => ({ ...m, bands_source: "ancestor" as const })),
});

/** Inherited values say where they come from; levels are read-only. */
export const InheritedFromOrgAndParent: Story = {
  beforeEach: () => mockProjectApis(inherited()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Inherited from organisation")).toBeInTheDocument());
    await expect(canvas.getByText("Inherited from parent project")).toBeInTheDocument();
    await expect(canvas.getByText("Levels are set by the organisation.")).toBeInTheDocument();
    await expect(canvas.queryByRole("textbox", { name: /level name/ })).not.toBeInTheDocument();
  },
};

export const OverrideAndClearDefaultModel: Story = {
  beforeEach: () => mockProjectApis(inherited()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Default model" }), "sxf");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/default-model`, { model: "sxf" }));
    await waitFor(() => expect(within(document.body).getByText("Default model saved.")).toBeInTheDocument());
    await userEvent.click(canvas.getAllByRole("button", { name: "Use inherited value" })[0]);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/default-model`, { model: null }));
  },
};

export const OverrideBands: Story = {
  beforeEach: () => mockProjectApis(inherited()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const label = await canvas.findByRole("textbox", { name: "Band 4 label" });
    await userEvent.clear(label);
    await userEvent.type(label, "Severe");
    await userEvent.click(canvas.getByRole("button", { name: "Save bands" }));
    await waitFor(() => expect(within(document.body).getByText("Rating bands saved.")).toBeInTheDocument());
    // Now an override: the pill offers a way back to the inherited bands.
    await waitFor(() => expect(canvas.getAllByRole("button", { name: "Use inherited value" })).toHaveLength(1));
  },
};

const OWN_AXIS = {
  key: "c_local", label: "Local fit", description: null, origin: "project" as const, owner_project_id: PROJECT_ID,
  levels: [
    { id: "loc-1", name: "Weak", description: null, weight: 1 },
    { id: "loc-2", name: "Strong", description: null, weight: 2 },
  ],
};

/** A project edits the levels of an axis it defined, with its own level endpoints; other axes stay read-only. */
export const OwnAxisLevelsAreEditable: Story = {
  args: { schemeKey: "enhancement_request" },
  beforeEach: () => {
    const base = buildCustomCriteriaScheme();
    mockProjectApis(buildCustomCriteriaScheme({ axes: [...base.axes, OWN_AXIS] }));
    spyOn(api, "patch").mockImplementation(async (_path: string, body?: unknown) => body);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Criteria" });
    await expect(canvas.getByText("Levels are set by the organisation, except for an axis this project defined.")).toBeInTheDocument();
    await expect(canvas.getAllByRole("textbox", { name: "Local fit level name" }).length).toBeGreaterThan(0);
    await expect(canvas.queryByRole("textbox", { name: "Impact level name" })).not.toBeInTheDocument();
    const name = canvas.getAllByRole("textbox", { name: "Local fit level name" })[0];
    await userEvent.clear(name);
    await userEvent.type(name, "Poor");
    await userEvent.tab();
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/scoring-schemes/enhancement_request/levels/loc-1`, expect.objectContaining({ name: "Poor" }),
    ));
  },
};

/** Models shown is the project's own choice, with a way back to inheriting. */
export const ModelsShownOverrideAndReset: Story = {
  args: { schemeKey: "enhancement_request" },
  beforeEach: () => mockProjectApis(buildCustomCriteriaScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Show Weighted value" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/scoring-schemes/enhancement_request/enabled-models", { models: ["ice"] },
    ));
  },
};
