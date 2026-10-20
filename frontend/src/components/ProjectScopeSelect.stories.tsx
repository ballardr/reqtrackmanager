import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ProjectScopeApi, ProjectScopeOptions } from "../api/projectScope";
import { useProjectScope } from "../hooks/useProjectScope";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ProjectScopeSelect } from "./ProjectScopeSelect";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

function fakeApi(options: ProjectScopeOptions): ProjectScopeApi {
  return { options: fn(async () => options) };
}

function Harness({ api, covered, width }: { api: ProjectScopeApi; covered?: number; width?: number }) {
  const scope = useProjectScope(PROJECT_ID, api);
  return (
    <div className="row" style={{ width, justifyContent: "space-between", alignItems: "center" }}>
      <h1 style={{ margin: 0 }}>Atlas</h1>
      <div className="row" style={{ alignItems: "center" }}>
        <ProjectScopeSelect scope={scope} compact coveredProjects={covered} />
        <button className="btn btn-primary">New requirement</button>
      </div>
    </div>
  );
}

/**
 * The compact scope select for a page's title row: its explanation is a tooltip (hover and keyboard
 * focus) and is always available to assistive technology; a widened scope is outlined.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/ProjectScopeSelect",
  component: Harness,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof Harness>;

const BOTH = { has_parents: true, has_children: true, truncated: false };

export const DefaultIsThisProjectOnly: Story = {
  args: { api: fakeApi(BOTH) },
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Show records from" });
    await expect(select).not.toHaveClass("project-scope-select-widened");
    await expect(select).toHaveAccessibleDescription(/Choose whether the counts cover related projects/);
  },
};

/** Widening outlines the control, and the tooltip opens on hover and on keyboard focus. */
export const WidenedIsOutlinedWithATooltip: Story = {
  args: { api: fakeApi(BOTH), covered: 3 },
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Show records from" });
    await userEvent.selectOptions(select, "both");
    await waitFor(() => expect(select).toHaveClass("project-scope-select-widened"));
    await expect(select).toHaveAccessibleDescription(/Counts cover 3 projects/);
    await userEvent.hover(select);
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Counts cover 3 projects");
    await userEvent.unhover(select);
    await waitFor(() => expect(within(document.body).queryByRole("tooltip")).not.toBeInTheDocument());
    // Selecting an option left the select focused; focus it afresh to show the keyboard path.
    select.blur();
    select.focus();
    await expect(await within(document.body).findByRole("tooltip")).toHaveTextContent("Counts cover 3 projects");
  },
};

/** No openable relatives: nothing is drawn, so the title row has no gap. */
export const HiddenWithoutRelatives: Story = {
  args: { api: fakeApi({ has_parents: false, has_children: false, truncated: false }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api.options).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("combobox")).not.toBeInTheDocument();
  },
};

/** A narrow header wraps the controls under the title; the select never overlaps the button. */
export const NarrowHeaderWraps: Story = {
  args: { api: fakeApi(BOTH), width: 300 },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Show records from" });
    const button = canvas.getByRole("button", { name: "New requirement" });
    const a = select.getBoundingClientRect();
    const b = button.getBoundingClientRect();
    await expect(a.right <= b.left + 1 || a.bottom <= b.top + 1 || b.bottom <= a.top + 1).toBe(true);
  },
};
