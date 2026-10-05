import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ScoringScheme } from "../api/scoring";
import { buildScoringScheme, withToast } from "../testing/storybook-helpers";
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
