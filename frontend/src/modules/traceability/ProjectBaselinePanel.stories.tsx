import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, buildStage, withRouter, withToast } from "../../testing/storybook-helpers";
import { expectStressStable, STRESS_TEXT } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import {
  buildProjectBaseline, EMPTY_BASELINE, mockGets, ORG_ID, PREVIEW_CLEAR, PREVIEW_WITH_FAILURES, PROJECT_ID, projectBaselineUrl,
} from "./policyFixtures";
import { ProjectBaselinePanel } from "./ProjectBaselinePanel";

const PREVIEW_URL = `/api/v1/projects/${PROJECT_ID}/modules/traceability/baseline-checks`;
const STAGES_URL = `/api/v1/projects/${PROJECT_ID}/stages`;
const reads = (baseline = buildProjectBaseline()) => ({
  [projectBaselineUrl]: baseline,
  [STAGES_URL]: [buildStage({ id: "stage-1", name: "Build" })],
  [PREVIEW_URL]: PREVIEW_WITH_FAILURES,
  [`/api/v1/projects/${PROJECT_ID}`]: buildProject({ id: PROJECT_ID, organization_id: ORG_ID }),
});

const meta: Meta<typeof ProjectBaselinePanel> = {
  title: "Modules/Governance/ProjectBaselinePanel",
  component: ProjectBaselinePanel,
  args: { projectId: PROJECT_ID },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => mockGets(reads()),
};
export default meta;

type Story = StoryObj<typeof ProjectBaselinePanel>;

export const ShowsWhatAppliesNowWithSources: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const checks = within(await canvas.findByRole("table", { name: "Baseline checks in force" }));
    const required = checks.getByRole("cell", { name: "Required fields" }).closest("tr")!;
    await expect(within(required).getByText("Stage and manual baselines")).toBeInTheDocument();
    await expect(within(required).getByText("Assurance profile, This project")).toBeInTheDocument();
    const missing = checks.getByRole("cell", { name: /compliance:evidence/ }).closest("tr")!;
    await expect(within(missing).getByText("Unavailable")).toBeInTheDocument();
  },
};

export const AFieldTheProjectDoesNotOfferIsMarked: Story = {
  play: async ({ canvasElement }) => {
    const fields = within(await within(canvasElement).findByRole("table", { name: "Required fields in force" }));
    await expect(fields.getByText("custom_gone (not offered in this project)")).toBeInTheDocument();
    await expect(fields.getByText("Reasoning")).toBeInTheDocument();
  },
};

export const HeadersSortTheTables: Story = {
  play: async ({ canvasElement }) => {
    const checks = within(await within(canvasElement).findByRole("table", { name: "Baseline checks in force" }));
    await userEvent.click(checks.getByRole("button", { name: /Check/ }));
    await expect(checks.getAllByRole("row")[1]).toHaveTextContent("compliance:evidence");
    await userEvent.click(checks.getByRole("button", { name: /Check/ }));
    await expect(checks.getAllByRole("row")[1]).toHaveTextContent("Required fields");
  },
};

export const SavingSendsTheProjectsOwnPolicy: Story = {
  play: async ({ canvasElement }) => {
    spyOn(api, "put").mockResolvedValue(buildProjectBaseline(true, { ...EMPTY_BASELINE, checks: ["traceability:required_approvals"] }));
    const canvas = within(canvasElement);
    const form = within(await canvas.findByRole("region", { name: "Project policy" }));
    await userEvent.click(form.getByRole("checkbox", { name: "Required fields" }));
    await userEvent.click(form.getByRole("checkbox", { name: "Required approvals" }));
    await userEvent.click(form.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(projectBaselineUrl, {
      settings: {
        applies_to_stage: true, applies_to_manual: true, notify_managers: true, checks: ["traceability:required_approvals"],
        required_fields: [{ artefact_type: "requirement", field_key: "reasoning" }],
      },
    }));
    await expect(await within(document.body).findByText("Baseline policy saved.")).toBeInTheDocument();
  },
};

export const UseInheritedValueFollowsTheParentProject: Story = {
  play: async ({ canvasElement }) => {
    spyOn(api, "put").mockResolvedValue(buildProjectBaseline(true, null));
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(projectBaselineUrl, { settings: null }));
    await expect(await canvas.findByText("Inherited from Programme Atlas")).toBeInTheDocument();
  },
};

export const AProjectWithNoPolicyOfItsOwnNamesWhatItInherits: Story = {
  beforeEach: () => mockGets(reads(buildProjectBaseline(true, null))),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Inherited from Programme Atlas")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Use inherited value" })).not.toBeInTheDocument();
  },
};

export const AReaderWhoCannotManageSeesOnlyWhatApplies: Story = {
  beforeEach: () => mockGets(reads(buildProjectBaseline(false))),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Baseline checks in force" });
    await expect(canvas.queryByRole("region", { name: "Project policy" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("region", { name: "Preview a baseline" })).not.toBeInTheDocument();
  },
};

export const NoCheckAndNoFieldInForce: Story = {
  beforeEach: () => mockGets(reads({ ...buildProjectBaseline(false), checks: [], required_fields: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No baseline check is enabled for this project.")).toBeInTheDocument();
    await expect(canvas.getByText("No field is required for this project.")).toBeInTheDocument();
  },
};

export const PreviewListsEveryFailure: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const preview = within(await canvas.findByRole("region", { name: "Preview a baseline" }));
    await userEvent.selectOptions(await preview.findByRole("combobox", { name: "Stage" }), "stage-1");
    await userEvent.click(preview.getByRole("button", { name: "Run preview" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${PREVIEW_URL}?kind=stage&stage_id=stage-1`));
    const failures = within(await preview.findByRole("table", { name: "Baseline check failures" }));
    await expect(failures.getByText("REQ-004")).toBeInTheDocument();
    await expect(failures.getByText("REQ-009")).toBeInTheDocument();
  },
};

export const PreviewWithNoFailureIsAllClear: Story = {
  beforeEach: () => mockGets({ ...reads(), [PREVIEW_URL]: PREVIEW_CLEAR }),
  play: async ({ canvasElement }) => {
    const preview = within(await within(canvasElement).findByRole("region", { name: "Preview a baseline" }));
    await userEvent.selectOptions(await preview.findByRole("combobox", { name: "Stage" }), "stage-1");
    await userEvent.click(preview.getByRole("button", { name: "Run preview" }));
    await expect(await preview.findByText("The baseline would be written: no check fails.")).toBeInTheDocument();
  },
};

export const AManualPreviewNeedsNoStage: Story = {
  beforeEach: () => mockGets({ ...reads(), [PREVIEW_URL]: { ...PREVIEW_CLEAR, kind: "manual" } }),
  play: async ({ canvasElement }) => {
    const preview = within(await within(canvasElement).findByRole("region", { name: "Preview a baseline" }));
    await expect(preview.getByRole("button", { name: "Run preview" })).toBeDisabled();
    await userEvent.selectOptions(preview.getByRole("combobox", { name: "Kind of baseline" }), "manual");
    await expect(preview.queryByRole("combobox", { name: "Stage" })).not.toBeInTheDocument();
    await userEvent.click(preview.getByRole("button", { name: "Run preview" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${PREVIEW_URL}?kind=manual`));
  },
};

export const APreviewThatFailsToRunIsReported: Story = {
  beforeEach: () => mockGets({ ...reads(), [PREVIEW_URL]: () => { throw new Error("The stage was not found."); } }),
  play: async ({ canvasElement }) => {
    const preview = within(await within(canvasElement).findByRole("region", { name: "Preview a baseline" }));
    await userEvent.selectOptions(await preview.findByRole("combobox", { name: "Stage" }), "stage-1");
    await userEvent.click(preview.getByRole("button", { name: "Run preview" }));
    await expect(await preview.findByText("The stage was not found.")).toBeInTheDocument();
  },
};

export const LongText: Story = {
  beforeEach: () => {
    let calls = 0;
    mockGets({
      ...reads(),
      [projectBaselineUrl]: () => {
        const baseline = buildProjectBaseline(false);
        if (calls++ % 2 === 1) {
          baseline.checks[0].name = STRESS_TEXT.name;
          baseline.checks[0].sources = [STRESS_TEXT.word, STRESS_TEXT.name];
          baseline.required_fields[0].field_label = STRESS_TEXT.word;
          baseline.required_fields[1].field_key = STRESS_TEXT.name;
        }
        return baseline;
      },
    });
  },
  render: (args) => <TextStress render={() => <ProjectBaselinePanel {...args} />} width={900} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findAllByRole("table", { name: "Baseline checks in force" });
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...ShowsWhatAppliesNowWithSources, globals: { theme: "dark" } };
