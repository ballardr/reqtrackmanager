import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ScoringScheme } from "../api/scoring";
import { buildCustomCriteriaScheme, buildScoringScheme, buildUser, expandScoringLevels, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { ScoringSchemeEditor } from "./ScoringSchemeEditor";

const ORG_ID = "org-1";
const BASE = `/api/v1/orgs/${ORG_ID}/scoring-schemes/pain_point`;

/** In-memory scheme behind mocked `api.*` calls (mirrors the backend's
 * ordering-by-weight and 409-when-in-use behaviour). */
function mockSchemeApis(initial: ScoringScheme, inUseLevelIds: string[] = []) {
  let scheme = initial;
  spyOn(api, "get").mockImplementation(async () => scheme);
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    const axisKey = path.split("/axes/")[1].split("/")[0];
    const level = { id: `new-${Date.now()}`, ...(body as { name: string; weight: number; description: string | null }) };
    scheme = { ...scheme, axes: scheme.axes.map((a) => (a.key === axisKey
      ? { ...a, levels: [...a.levels, level].sort((x, y) => x.weight - y.weight) } : a)) };
    return level;
  });
  spyOn(api, "delete").mockImplementation(async (path: string) => {
    const [levelId, query] = path.split("/levels/")[1].split("?");
    if (inUseLevelIds.includes(levelId) && !query) throw new ApiError(409, "This level is used by 2 score(s); choose another level to move them to.");
    scheme = { ...scheme, axes: scheme.axes.map((a) => ({ ...a, levels: a.levels.filter((l) => l.id !== levelId) })) };
  });
  spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/default-model")) {
      const model = (body as { model: string | null }).model;
      scheme = { ...scheme, default_model_key: model ?? scheme.system_default_model_key, default_model_source: model ? "org" : "system" };
    }
    return scheme;
  });
}

const meta: Meta<typeof ScoringSchemeEditor> = {
  title: "Components/Scoring/ScoringSchemeEditor",
  component: ScoringSchemeEditor,
  args: { orgId: ORG_ID, schemeKey: "pain_point" },
  // The folding blocks remember their state through the signed-in person's preferences.
  decorators: [withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof ScoringSchemeEditor>;

export const ShowsAxesAndDefaults: Story = {
  beforeEach: () => mockSchemeApis(buildScoringScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Levels" });
    // Each axis's levels are folded until opened.
    await expect(canvas.queryByDisplayValue("Blocker")).not.toBeInTheDocument();
    await expect(canvas.getByText("5 levels")).toBeInTheDocument();
    await expandScoringLevels(canvas);
    await waitFor(() => expect(canvas.getByDisplayValue("Blocker")).toBeInTheDocument());
    await expect(canvas.getByText("Severity")).toBeInTheDocument();
    await expect(canvas.getByText("Frequency")).toBeInTheDocument();
    // Levels are weight-ordered, not manually reordered.
    await expect(canvas.queryByRole("button", { name: "Move up" })).not.toBeInTheDocument();
    await expect(canvas.getAllByText("Module default").length).toBeGreaterThan(0);
    // A scheme that does not score with several models at once, or take custom criteria, shows neither setting.
    await expect(canvas.queryByRole("heading", { name: "Models shown" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("heading", { name: "Criteria" })).not.toBeInTheDocument();
  },
};

export const AddLevel: Story = {
  beforeEach: () => mockSchemeApis(buildScoringScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Levels" });
    await expandScoringLevels(canvas);
    await waitFor(() => canvas.getByDisplayValue("Blocker"));
    const names = canvas.getAllByRole("textbox", { name: "Confidence level name" });
    const name = names[names.length - 1];
    await userEvent.type(name, "Medium");
    const weights = canvas.getAllByRole("spinbutton", { name: "Confidence level weight" });
    const weight = weights[weights.length - 1];
    await userEvent.type(weight, "0.8");
    await userEvent.click(canvas.getByRole("button", { name: "Add Confidence level" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/axes/confidence/levels`, {
      name: "Medium", weight: 0.8, description: null,
    }));
    await waitFor(() => expect(within(document.body).getByText("Level added.")).toBeInTheDocument());
  },
};

/** An in-use level opens the shared in-use dialog; confirming retries with the target. */
export const DeleteInUseLevelReassigns: Story = {
  beforeEach: () => mockSchemeApis(buildScoringScheme(), ["freq-1"]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Levels" });
    await expandScoringLevels(canvas);
    await waitFor(() => canvas.getByDisplayValue("Rare"));
    // "Rare" is the first Frequency level, so its delete button is the first one.
    await userEvent.click(canvas.getAllByRole("button", { name: "Delete Frequency level" })[0]);
    const dialog = within(await within(document.body).findByRole("dialog"));
    await waitFor(() => expect(dialog.getByText(/used by 2 score/)).toBeInTheDocument());
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "freq-2");
    await userEvent.click(dialog.getByRole("button", { name: /confirm/i }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/levels/freq-1?reassign_to_id=freq-2`));
  },
};

/** An axis at two levels can't lose another. */
export const MinimumTwoLevels: Story = {
  beforeEach: () => mockSchemeApis(buildScoringScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Levels" });
    await expandScoringLevels(canvas);
    await waitFor(() => canvas.getByDisplayValue("Blocker"));
    const buttons = canvas.getAllByRole("button", { name: /At least 2 are required/ });
    await expect(buttons).toHaveLength(2); // both Confidence levels
  },
};

export const ChangeAndResetDefaultModel: Story = {
  beforeEach: () => mockSchemeApis(buildScoringScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Default model" });
    await userEvent.selectOptions(select, "sxf");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/default-model`, { model: "sxf" }));
    await waitFor(() => expect(within(document.body).getByText("Default model saved.")).toBeInTheDocument());
    await userEvent.click(canvas.getAllByRole("button", { name: "Reset to module default" })[0]);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/default-model`, { model: null }));
  },
};

export const PermissionErrorToasts: Story = {
  beforeEach: () => {
    mockSchemeApis(buildScoringScheme());
    spyOn(api, "put").mockRejectedValue(new ApiError(403, "Insufficient permissions to configure scoring."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Default model" }), "sxf");
    await waitFor(() => expect(within(document.body).getByText("Insufficient permissions to configure scoring.")).toBeInTheDocument());
  },
};

export const LoadError: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Not found."));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Not found.")).toBeInTheDocument());
  },
};

/** A scheme that takes custom criteria lists its criteria; Models shown saves the whole set. */
export const CustomCriteriaAndModelsShown: Story = {
  args: { schemeKey: "enhancement_request" },
  beforeEach: () => mockSchemeApis(buildCustomCriteriaScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Criteria" });
    await expect(canvas.getByRole("button", { name: "Edit Strategic fit" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Hide Impact" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show Weighted value" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/scoring-schemes/enhancement_request/enabled-models`, { models: ["ice"] },
    ));
    await waitFor(() => expect(within(document.body).getByText("Models shown saved.")).toBeInTheDocument());
  },
};

/** A derived axis (Demand) edits a threshold per level, and a new level must give one. */
export const DerivedAxisLevelsHaveAThreshold: Story = {
  args: { schemeKey: "enhancement_request" },
  beforeEach: () => mockSchemeApis(buildCustomCriteriaScheme()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("heading", { name: "Criteria" });
    await expandScoringLevels(canvas);
    await expect(canvas.getAllByRole("spinbutton", { name: "Demand level threshold" })).toHaveLength(4); // 3 levels + the add row
    await expect(canvas.queryByRole("spinbutton", { name: "Impact level threshold" })).not.toBeInTheDocument();
    const names = canvas.getAllByRole("textbox", { name: "Demand level name" });
    await userEvent.type(names[names.length - 1], "Huge");
    const weights = canvas.getAllByRole("spinbutton", { name: "Demand level weight" });
    await userEvent.type(weights[weights.length - 1], "4");
    await expect(canvas.getByRole("button", { name: "Add Demand level" })).toBeDisabled(); // no threshold yet
    const thresholds = canvas.getAllByRole("spinbutton", { name: "Demand level threshold" });
    await userEvent.type(thresholds[thresholds.length - 1], "25");
    await userEvent.click(canvas.getByRole("button", { name: "Add Demand level" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/scoring-schemes/enhancement_request/axes/demand/levels`,
      { name: "Huge", weight: 4, description: null, threshold: 25 },
    ));
  },
};
