import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { ProjectScopeApi, ProjectScopeOptions } from "../api/projectScope";
import { useProjectScope } from "../hooks/useProjectScope";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ProjectScopeFilter } from "./ProjectScopeFilter";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

function fakeApi(options: ProjectScopeOptions): ProjectScopeApi {
  return { options: fn(async () => options) };
}

function Harness({ api }: { api: ProjectScopeApi }) {
  const scope = useProjectScope(PROJECT_ID, api);
  return (
    <div className="stack" style={{ maxWidth: 260 }}>
      <ProjectScopeFilter scope={scope} />
      <output aria-label="Query">{scope.query}</output>
    </div>
  );
}

/**
 * The scope filter of a list's filter panel: widen a list to the parent and/or child projects the
 * viewer can open. Only the choices the project can offer are listed; a project with no openable
 * relatives shows nothing.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/ProjectScopeFilter",
  component: Harness,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** Choosing a wider scope changes the query the list sends. */
export const ChoosingParentsBuildsTheQuery: Story = {
  args: { api: fakeApi({ has_parents: true, has_children: false, truncated: false }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Show records from" });
    await expect(canvas.getByLabelText("Query").textContent).toBe("");
    await expect(within(select).queryByRole("option", { name: /child/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(select, "parents");
    await expect(canvas.getByLabelText("Query").textContent).toBe("project_scope=parents");
    await expect(canvas.getByText(/Includes records from related/)).toBeInTheDocument();
  },
};

/** A project with both a parent and children also offers the combination. */
export const ParentAndChildrenOfferBoth: Story = {
  args: { api: fakeApi({ has_parents: true, has_children: true, truncated: false }) },
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Show records from" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "This project",
      "This + parent projects",
      "This + child projects",
      "This + parent and child projects",
    ]);
  },
};

/** A project with no openable relatives shows no filter at all. */
export const HiddenWithoutRelatives: Story = {
  args: { api: fakeApi({ has_parents: false, has_children: false, truncated: false }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api.options).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("combobox", { name: "Show records from" })).not.toBeInTheDocument();
  },
};

/** The viewer's default applies until they choose: "both" shows the widest part the project offers. */
export const TheDefaultDegradesToWhatTheProjectOffers: Story = {
  args: { api: fakeApi({ has_parents: true, has_children: false, truncated: false }) },
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { default_project_scope: "both" } }))],
  play: async ({ canvasElement }) => {
    const select = await within(canvasElement).findByRole("combobox", { name: "Show records from" });
    await expect(select).toHaveValue("parents");
    await expect(within(canvasElement).getByLabelText("Query").textContent).toBe("project_scope=parents");
  },
};
