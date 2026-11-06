import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildGraph, buildLinksApi, buildOption, LINKS_ARTEFACT_ID, LINKS_PROJECT_ID } from "../testing/artefactLinksFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../testing/storybook-helpers";
import { getLinkedRecordCreator } from "../modules/linkedRecordCreators";
import { ArtefactLinksPanel } from "./ArtefactLinksPanel";

const ADDRESSES = buildOption({
  link_type_id: "lt-addresses", forward_name: "Addresses", reverse_name: "Is addressed by", phrase: "Addresses",
  other_types: [{ type: "pain_point", label: "Pain Point" }],
});
const RELATED = buildOption({ other_types: [{ type: "pain_point", label: "Pain Point" }, { type: "decision", label: "Decision" }] });

/**
 * The panel's "Create new": records another module can create (here the Pain Point dialog the Pain Point module
 * registers) are created and linked in one step. The Links API is injected; the dialog's own calls go through `api`.
 */
const meta: Meta<typeof ArtefactLinksPanel> = {
  title: "Components/ArtefactLinksPanel/Create new",
  component: ArtefactLinksPanel,
  decorators: [withToast(), withRouter("/"), withStatefulAuth(buildUser())],
  args: { projectId: LINKS_PROJECT_ID, artefactType: "enhancement_request", artefactId: LINKS_ARTEFACT_ID },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/pain-point-types")) {
        return [{ id: "type-user", name: "User", display_order: 0, is_enabled: true, source: "org", definition: null }] as never;
      }
      return [] as never;
    });
  },
};
export default meta;

type Story = StoryObj<typeof ArtefactLinksPanel>;

/** Creating a Pain Point from the panel links it with the most specific relationship (Addresses), not "Related to". */
export const CreatesAPainPointAndLinksItWithTheSpecificRelationship: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      options: fn(async () => [RELATED, ADDRESSES]),
      create: fn(async () => {}),
    }),
  },
  play: async ({ canvasElement, args }) => {
    spyOn(api, "post").mockResolvedValue({ id: "pp-new", title: "Reports are slow" } as never);
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Create a record and link it" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "New Pain Point" }));
    const body = within(document.body);
    await userEvent.selectOptions(await body.findByLabelText("Type"), "type-user");
    await userEvent.type(body.getByLabelText("Pain Point title"), "Reports are slow");
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(
      LINKS_PROJECT_ID, "enhancement_request", LINKS_ARTEFACT_ID,
      expect.objectContaining({ link_type_id: "lt-addresses", other_type: "pain_point", other_id: "pp-new" }),
    ));
    await expect(await within(document.body).findByText("Pain Point created and linked.")).toBeInTheDocument();
  },
};

/** When several relationships reach the type, the one the request means leads and the person can pick another. */
export const OffersTheRelationshipWhenSeveralReachTheType: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      // Listed with the preferred one last: the request's own module says "Addresses" leads.
      options: fn(async () => [buildOption({ link_type_id: "lt-derives", forward_name: "Derives from", phrase: "Derives from", other_types: [{ type: "pain_point", label: "Pain Point" }] }), ADDRESSES]),
    }),
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Create a record and link it" }));
    const popover = within(document.body);
    const select = await popover.findByRole("combobox", { name: "Pain Point Relationship" });
    await expect(select).toHaveDisplayValue("Addresses"); // the request's preferred relationship leads, not the first listed
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Addresses", "Derives from"]);
  },
};

/** A record that no link type reaches a creatable type from, or that cannot be linked, offers no "Create new". */
export const OffersNothingWhereNothingCanBeCreated: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      options: fn(async () => [buildOption({ other_types: [{ type: "nothing_registered", label: "Nothing" }] })]),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "Add link" });
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Create a record and link it" })).not.toBeInTheDocument());
  },
};

export const OffersNothingWhenLinksAreReadOnly: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: false, can_propose: false })),
      options: fn(async () => [ADDRESSES]),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("No links yet.");
    await expect(canvas.queryByRole("button", { name: "Create a record and link it" })).not.toBeInTheDocument();
  },
};

/** A type whose module declares a create check is offered only to someone it allows (a role-gated type never shows a refused control). */
export const OffersATypeOnlyToSomeoneAllowedToCreateIt: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      options: fn(async () => [ADDRESSES]),
    }),
  },
  // The check must be in place before the panel mounts; the original is restored afterwards.
  beforeEach: () => {
    const creator = getLinkedRecordCreator("pain_point")!;
    const original = creator.canCreate;
    creator.canCreate = async () => false;
    return () => { creator.canCreate = original; };
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "Add link" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(canvas.queryByRole("button", { name: "Create a record and link it" })).not.toBeInTheDocument();
  },
};
