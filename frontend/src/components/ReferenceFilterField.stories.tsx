import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { useTagFilter } from "../hooks/useTagFilter";
import { buildReferenceFilterApi, REFERENCES_PROJECT_ID } from "../testing/referencesFixtures";
import { ReferenceFilterField } from "./ReferenceFilterField";

function Harness({ api }: { api: React.ComponentProps<typeof ReferenceFilterField>["api"] }) {
  const filter = useTagFilter();
  return (
    <div className="stack" style={{ maxWidth: 260 }}>
      <ReferenceFilterField projectId={REFERENCES_PROJECT_ID} filter={filter} api={api} />
      <output aria-label="Query">{filter.query}</output>
      <output aria-label="Active">{String(filter.active)}</output>
    </div>
  );
}

/**
 * The external reference filter of a list's filter panel: tick systems and type part of a key. A record matches when it
 * has a reference in any ticked system whose key contains the text. The list page sends `query` (or the list filters).
 */
const meta: Meta<typeof Harness> = {
  title: "Components/ReferenceFilterField",
  component: Harness,
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const TickingSystemsAndTypingAKeyBuildsTheQuery: Story = {
  args: { api: buildReferenceFilterApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "External system" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Jira" }));
    await expect(canvas.getByLabelText("Query").textContent).toBe("external_system=Jira");
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "DOORS" }));
    await expect(canvas.getByLabelText("Query").textContent).toBe("external_system=Jira&external_system=DOORS");
    await userEvent.type(canvas.getByRole("textbox", { name: "External key" }), "PROJ-1");
    await userEvent.tab();
    await expect(canvas.getByLabelText("Query").textContent).toBe("external_system=Jira&external_system=DOORS&external_key=PROJ-1");
    await expect(canvas.getByLabelText("Active").textContent).toBe("true");
  },
};

/** A project with no external system shows no filter at all. */
export const HiddenWhenTheProjectHasNoSystems: Story = {
  args: { api: buildReferenceFilterApi([]) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.systems).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("button", { name: "External system" })).not.toBeInTheDocument();
  },
};

export const HiddenWhenTheReadFails: Story = {
  args: { api: { systems: fn(async () => { throw new Error("Failed"); }) } },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.systems).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("textbox", { name: "External key" })).not.toBeInTheDocument();
  },
};
