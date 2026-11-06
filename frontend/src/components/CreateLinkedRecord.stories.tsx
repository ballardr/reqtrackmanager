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
 * The panel's "Add link" menu, "Create a new record": a first step chooses the record type and relationship, then the
 * records another module can create (here the Pain Point dialog the Pain Point module registers) are created and
 * linked in one step. The Links API is injected; the dialog's own calls go through `api`.
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

/** Opens the create flow's first step from the "Add link" menu. */
async function openCreateStep(canvasElement: HTMLElement) {
  await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add link" }));
  await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Create a new record" }));
  return within(await within(document.body).findByRole("dialog", { name: "Create and link a new record" }));
}

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
    const step = await openCreateStep(canvasElement);
    // Only one type can be created, so its select is unavailable and a tooltip says why.
    const recordType = step.getByLabelText("Record type");
    await expect(recordType).toHaveDisplayValue("Pain Point");
    await expect(recordType).toBeDisabled();
    await userEvent.hover(recordType.closest(".tooltip-trigger") as HTMLElement);
    await expect(await within(document.body).findByText(/Only a Pain Point can be created and linked from this record/)).toBeInTheDocument();
    await expect(step.getByLabelText("Relationship")).toHaveDisplayValue("Addresses (default)");
    await userEvent.click(step.getByRole("button", { name: "Next" }));
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

/** The first step lists every relationship that reaches the type, the one the request means leading; the choice is the one linked. */
export const OffersTheRelationshipWhenSeveralReachTheType: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      // Listed with the preferred one last: the request's own module says "Addresses" leads.
      options: fn(async () => [buildOption({ link_type_id: "lt-derives", forward_name: "Derives from", phrase: "Derives from", other_types: [{ type: "pain_point", label: "Pain Point" }] }), ADDRESSES]),
      create: fn(async () => {}),
    }),
  },
  play: async ({ canvasElement, args }) => {
    spyOn(api, "post").mockResolvedValue({ id: "pp-new", title: "Reports are slow" } as never);
    const step = await openCreateStep(canvasElement);
    const select = step.getByRole("combobox", { name: "Relationship" });
    await expect(select).toHaveDisplayValue("Addresses (default)"); // the request's preferred relationship leads, not the first listed
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Addresses (default)", "Derives from"]);
    await userEvent.selectOptions(select, "Derives from");
    await userEvent.click(step.getByRole("button", { name: "Next" }));
    const body = within(document.body);
    await userEvent.selectOptions(await body.findByLabelText("Type"), "type-user");
    await userEvent.type(body.getByLabelText("Pain Point title"), "Reports are slow");
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.create).toHaveBeenCalledWith(
      LINKS_PROJECT_ID, "enhancement_request", LINKS_ARTEFACT_ID,
      expect.objectContaining({ link_type_id: "lt-derives", other_type: "pain_point", other_id: "pp-new" }),
    ));
  },
};

/** A record that no link type reaches a creatable type from keeps the plain "Add link" button, with no create choice. */
export const OffersNothingWhereNothingCanBeCreated: Story = {
  args: {
    api: buildLinksApi({
      graph: fn(async () => buildGraph([], { can_link: true })),
      options: fn(async () => [buildOption({ other_types: [{ type: "nothing_registered", label: "Nothing" }] })]),
    }),
  },
  play: async ({ canvasElement }) => {
    const addLink = await within(canvasElement).findByRole("button", { name: "Add link" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(addLink).not.toHaveAttribute("aria-haspopup", "menu");
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
    await expect(canvas.queryByRole("button", { name: "Add link" })).not.toBeInTheDocument();
  },
};

/** A type whose module declares a create check is offered only to someone it allows (a role-gated type never shows a refused choice). */
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
    const addLink = await within(canvasElement).findByRole("button", { name: "Add link" });
    await new Promise((resolve) => setTimeout(resolve, 300));
    await expect(addLink).not.toHaveAttribute("aria-haspopup", "menu");
  },
};
