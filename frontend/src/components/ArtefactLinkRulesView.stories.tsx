import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ArtefactLinkRule } from "../api/types";
import { buildLinkType, withToast } from "../testing/storybook-helpers";
import { ArtefactLinkRulesView } from "./ArtefactLinkRulesView";

const linkTypes = [
  buildLinkType({ id: "lt-related", forward_name: "Related to", reverse_name: "Related to" }),
  buildLinkType({ id: "lt-derives", forward_name: "Derives from", reverse_name: "Is the source of" }),
  buildLinkType({ id: "lt-implements", forward_name: "Implements", reverse_name: "Is implemented by" }),
];

const rules: ArtefactLinkRule[] = [
  { artefact_type: "requirement", label: "Requirement", link_type_ids: null },
  { artefact_type: "decision", label: "Decision", link_type_ids: ["lt-implements"] },
];

const meta: Meta<typeof ArtefactLinkRulesView> = {
  title: "Components/ArtefactLinkRulesView",
  component: ArtefactLinkRulesView,
  decorators: [withToast()],
  args: { scope: { kind: "organization", orgId: "org-1" }, linkTypes, rules, onChanged: fn(async () => {}) },
  beforeEach: () => {
    spyOn(api, "put").mockResolvedValue(undefined);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
};
export default meta;

type Story = StoryObj<typeof ArtefactLinkRulesView>;

/** One row per artefact type; an unlimited one says "Any link type" and a
 * limited one says so with a way back. Names are labels, never raw type keys. */
export const ShowsAnyAndLimitedRows: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.getByText("Decision")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Link types allowed for Requirement" })).toHaveTextContent("Related to, Derives from, Implements");
    await expect(canvas.getByRole("button", { name: "Link types allowed for Decision" })).toHaveTextContent("Implements");
    await expect(canvas.getAllByRole("button", { name: "Allow any link type" })).toHaveLength(1);
    await expect(canvas.queryByText("requirement")).not.toBeInTheDocument();
  },
};

/** Limiting an unrestricted artefact type starts from every link type checked,
 * so unchecking one saves a rule of all the others (never an empty or one-item
 * rule by accident). */
export const LimitingStartsFromAllCheckedMinusOne: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Link types allowed for Requirement" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Requirement: Related to" }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/artefact-link-rules/requirement", {
        link_type_ids: ["lt-derives", "lt-implements"],
      })
    );
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
    await expect(await within(document.body).findByText("Link rule updated.")).toBeInTheDocument();
  },
};

/** A rule must keep at least one link type: its last checkbox is disabled with a hint. */
export const LastLinkTypeCannotBeUnchecked: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Link types allowed for Decision" }));
    const last = within(document.body).getByRole("checkbox", { name: "Decision: Implements" });
    await expect(last).toBeChecked();
    await expect(last).toBeDisabled();
  },
};

/** Removing a rule is confirmed (Tier 1), saved, and confirmed with a Toast. */
export const RemovingARuleAsksFirst: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Allow any link type" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Allow any link type for Decision?" }));
    await expect(dialog.getByText(/Existing links are not changed/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Remove rule" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1/artefact-link-rules/decision"));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
    await expect(await within(document.body).findByText("Link rule removed.")).toBeInTheDocument();
  },
};
