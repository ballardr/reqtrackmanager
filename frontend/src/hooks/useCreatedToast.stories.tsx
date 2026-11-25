import type { Meta, StoryObj } from "@storybook/react-vite";
import { useLocation } from "react-router-dom";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { withRouter, withToast } from "../testing/storybook-helpers";
import { useCreatedToast } from "./useCreatedToast";

function Harness({ artefactType = "decision", verb }: { artefactType?: string; verb?: string }) {
  const announce = useCreatedToast("project-1", artefactType);
  const { pathname } = useLocation();
  return (
    <div className="stack">
      <button className="btn" onClick={() => announce("Decision", { id: "d-4", unique_code: "DEC-004" }, verb)}>Create</button>
      <output aria-label="Path">{pathname}</output>
    </div>
  );
}

/**
 * The confirmation after a record is created from a list: it names the record by its code and offers Open, so a person
 * whose sort or filter keeps the new record off the visible rows can reach it at once.
 */
const meta: Meta<typeof Harness> = {
  title: "Hooks/useCreatedToast",
  component: Harness,
  decorators: [withRouter("/projects/project-1/modules/decisions"), withToast()],
};
export default meta;

type Story = StoryObj<typeof Harness>;

/** The toast names the record by its code and Open goes to the record's registered page. */
export const NamesTheRecordAndOffersOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Create" }));
    await expect(await within(document.body).findByText("Decision DEC-004 created.")).toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("button", { name: "Open DEC-004" }));
    await waitFor(() => expect(canvas.getByLabelText("Path").textContent).toBe("/projects/project-1/modules/decisions/d-4"));
    await expect(within(document.body).queryByText("Decision DEC-004 created.")).not.toBeInTheDocument();
  },
};

/** A record logged or raised says so in its own verb. */
export const UsesTheCallersVerb: Story = {
  args: { verb: "logged" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Create" }));
    await expect(await within(document.body).findByText("Decision DEC-004 logged.")).toBeInTheDocument();
  },
};

/** A type with no registered page gets the text without a dead button. */
export const WithoutAPageThereIsNoOpenButton: Story = {
  args: { artefactType: "no_such_type" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Create" }));
    await expect(await within(document.body).findByText("Decision DEC-004 created.")).toBeInTheDocument();
    await expect(within(document.body).queryByRole("button", { name: /^Open/ })).not.toBeInTheDocument();
  },
};
