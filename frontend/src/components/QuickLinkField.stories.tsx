import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DRAFT_ARTEFACT_ID, type CollectedLink } from "../api/artefactLinks";
import { buildCandidate, buildLinksApi, buildOption, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { withRouter } from "../testing/storybook-helpers";
import { QuickLinkField } from "./QuickLinkField";

/** Holds the chosen links in state, as a create form does. */
function Harness({ initial = [], onSubmit, ...rest }: Omit<React.ComponentProps<typeof QuickLinkField>, "value" | "onChange"> & {
  initial?: CollectedLink[];
  onSubmit?: () => void;
}) {
  const [links, setLinks] = useState<CollectedLink[]>(initial);
  return (
    <form onSubmit={(e) => { e.preventDefault(); onSubmit?.(); }}>
      <QuickLinkField {...rest} value={links} onChange={setLinks} />
    </form>
  );
}

const CHOSEN: CollectedLink = {
  link_type_id: "lt-related", direction: "outgoing", other_type: "decision", other_id: "dec-1",
  phrase: "Related to", otherLabel: "DEC-001 Use Postgres", otherTypeLabel: "Decision",
};

/**
 * The "Link to" field of a create form: search for records, pick the relationship, and the form creates
 * the links once the record exists. Reads are made about a record that does not exist yet
 * (`DRAFT_ARTEFACT_ID`), so the server applies the usual link rules.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/QuickLinkField",
  component: Harness,
  decorators: [withRouter("/")],
  args: { projectId: LINKS_PROJECT_ID, artefactType: "pain_point" },
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const SearchingAddsARecordWithTheDefaultRelationship: Story = {
  args: { api: buildLinksApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("combobox", { name: "Link to" }), "redis");
    await userEvent.click(await canvas.findByRole("option", { name: /DEC-002 Use Redis/ }));
    const list = canvas.getByRole("list", { name: "Records to link" });
    await expect(within(list).getByText("DEC-002 Use Redis")).toBeInTheDocument();
    await expect(within(list).getByText("Related to")).toBeInTheDocument();
    await expect(args.api!.options).toHaveBeenCalledWith(LINKS_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID);
    await expect(args.api!.candidates).toHaveBeenCalledWith(
      LINKS_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID, expect.objectContaining({ query: "redis" }),
    );
  },
};

/** A caller who cannot link this type (the server refuses the draft) sees no field at all. */
export const HiddenWhenTheCallerCannotLink: Story = {
  args: { api: buildLinksApi({ options: fn(async () => { throw new Error("You do not have permission"); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.options).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("combobox")).not.toBeInTheDocument();
  },
};

export const HiddenWhenNoLinkTypeReachesAnotherRecord: Story = {
  args: { api: buildLinksApi({ options: fn(async () => []) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.options).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("combobox")).not.toBeInTheDocument();
  },
};

/** When several link types reach the record, the relationship can be changed on the chosen row. */
export const TheRelationshipCanBeChanged: Story = {
  args: {
    initial: [CHOSEN],
    api: buildLinksApi({
      options: fn(async () => [
        buildOption({ other_types: [{ type: "decision", label: "Decision" }] }),
        buildOption({
          link_type_id: "lt-addresses", forward_name: "Addresses", reverse_name: "Addressed by", phrase: "Addresses",
          other_types: [{ type: "decision", label: "Decision" }],
        }),
      ]),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Relationship to DEC-001 Use Postgres" });
    await userEvent.selectOptions(select, "lt-addresses:outgoing");
    await expect(select).toHaveValue("lt-addresses:outgoing");
  },
};

export const ARecordCanBeRemoved: Story = {
  args: { initial: [CHOSEN], api: buildLinksApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Do not link DEC-001 Use Postgres" }));
    await expect(canvas.queryByText("DEC-001 Use Postgres")).not.toBeInTheDocument();
  },
};

/** With a preferred type the box lists that type's records as soon as it is focused, and sorts them first. */
export const ThePreferredTypeIsListedOnFocus: Story = {
  args: {
    preferredType: "persona",
    api: buildLinksApi({
      options: fn(async () => [buildOption({ other_types: [{ type: "persona", label: "Persona" }] })]),
      candidates: fn(async () => ({
        items: [buildCandidate({ type: "persona", id: "per-1", type_label: "Persona", label: "PER-001 Field engineer" })],
        truncated: false,
      })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("combobox", { name: "Link to" }));
    await expect(await canvas.findByRole("option", { name: /PER-001 Field engineer/ })).toBeInTheDocument();
    await expect(args.api!.candidates).toHaveBeenCalledWith(
      LINKS_PROJECT_ID, "pain_point", DRAFT_ARTEFACT_ID, expect.objectContaining({ otherType: "persona" }),
    );
  },
};

export const NoMatchesSaysSo: Story = {
  args: { api: buildLinksApi({ candidates: fn(async () => ({ items: [], truncated: false })) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("combobox", { name: "Link to" }), "zzz");
    await expect(await canvas.findByText("No matching records.")).toBeInTheDocument();
  },
};

/** A record already chosen is not offered again. */
export const ChosenRecordsAreNotOfferedAgain: Story = {
  args: {
    initial: [{ ...CHOSEN, other_id: "dec-2", otherLabel: "DEC-002 Use Redis" }],
    api: buildLinksApi(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("combobox", { name: "Link to" }), "use");
    await expect(await canvas.findByText("No matching records.")).toBeInTheDocument();
    await expect(canvas.queryByRole("option")).not.toBeInTheDocument();
  },
};

/** Enter picks the highlighted record and never submits the create form around the field. */
export const EnterPicksTheHighlightedRecordWithoutSubmittingTheForm: Story = {
  args: { api: buildLinksApi(), onSubmit: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const box = await canvas.findByRole("combobox", { name: "Link to" });
    await userEvent.type(box, "redis");
    await canvas.findByRole("option", { name: /DEC-002 Use Redis/ });
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await expect(within(canvas.getByRole("list", { name: "Records to link" })).getByText("DEC-002 Use Redis")).toBeInTheDocument();
    await expect(args.onSubmit).not.toHaveBeenCalled();
  },
};
