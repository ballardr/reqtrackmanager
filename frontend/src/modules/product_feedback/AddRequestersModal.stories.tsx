import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildCandidate, buildLinksApi, buildOption } from "../../testing/artefactLinksFixtures";
import { withRouter } from "../../testing/storybook-helpers";
import { AddRequestersModal } from "./AddRequestersModal";
import { PROJECT_ID } from "./requestFixtures";

const REQUESTED_BY = buildOption({
  link_type_id: "lt-requested-by", forward_name: "Requested by", reverse_name: "Requests", phrase: "Requested by",
  other_types: [{ type: "stakeholder", label: "Stakeholder", can_create: false }, { type: "persona", label: "Persona", can_create: false }],
});
const RELATED = buildOption();

const meta: Meta<typeof AddRequestersModal> = {
  title: "Modules/ProductFeedback/AddRequestersModal",
  component: AddRequestersModal,
  decorators: [withRouter("/")],
  args: { projectId: PROJECT_ID, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof AddRequestersModal>;

/** The field offers only the "Requested by" link type and only the record types it reaches; Save hands them back. */
export const OnlyRequestersCanBeChosenAndSaveReturnsThem: Story = {
  args: {
    api: buildLinksApi({
      options: fn(async () => [RELATED, REQUESTED_BY]),
      candidates: fn(async () => ({
        items: [
          buildCandidate({ type: "decision", id: "dec-1", type_label: "Decision", label: "DEC-001 Use Postgres" }),
          buildCandidate({ type: "stakeholder", id: "sh-1", type_label: "Stakeholder", label: "Hana High" }),
        ],
        truncated: false,
      })),
    }),
  },
  play: async ({ args }) => {
    const d = within(document.body);
    const save = await d.findByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await userEvent.type(await d.findByRole("combobox", { name: "Requested by" }), "ha");
    await expect(await d.findByRole("option", { name: /Hana High/ })).toBeInTheDocument();
    await expect(d.queryByRole("option", { name: /Use Postgres/ })).not.toBeInTheDocument(); // a Decision cannot be a requester
    await userEvent.click(d.getByRole("option", { name: /Hana High/ }));
    await expect(d.getByText("Requested by", { selector: "li *" })).toBeInTheDocument();
    await userEvent.click(save);
    await expect(args.onSave).toHaveBeenCalledWith([
      expect.objectContaining({ link_type_id: "lt-requested-by", other_type: "stakeholder", other_id: "sh-1" }),
    ]);
  },
};
