import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { buildPlace, buildPlacementsApi, buildRecordPlacements } from "../testing/placementsFixtures";
import { buildRecordReferences, buildReference, buildReferencesApi, REFERENCES_PROJECT_ID } from "../testing/referencesFixtures";
import {
  buildChip, buildRecordTags, buildRecordTagsApi, chooseAddition, openRecordTagBox, TAGS_PROJECT_ID,
} from "../testing/tagsFixtures";
import { withToast } from "../testing/storybook-helpers";
import { RecordTags } from "./RecordTags";

/**
 * The labels of one record in its header: one row of chips (tags, components, external references) and one (+) whose
 * menu names each addition. Someone who may change a kind edits it in place and each change is saved at once; everyone
 * else sees the chips (or nothing, when there are none). A row of the menu is absent when the person cannot do it.
 */
const meta: Meta<typeof RecordTags> = {
  title: "Components/RecordTags",
  component: RecordTags,
  decorators: [withToast()],
  args: {
    projectId: TAGS_PROJECT_ID, artefactType: "requirement", artefactId: "req-1",
    api: buildRecordTagsApi(), placementsApi: buildPlacementsApi(), referencesApi: buildReferencesApi(),
  },
};
export default meta;

type Story = StoryObj<typeof RecordTags>;

const ADD = "Add tag, component or external reference";

/** The three kinds in one row, in the order tags, components, references, the (+) after the last chip. */
export const OneRowHoldsEveryKindAndTheAddControl: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const row = within(await canvas.findByRole("group", { name: "Tags, components and references" }));
    const tag = await row.findByText("Safety");
    const place = await row.findByText("Hardware / Cooling");
    const reference = await row.findByText(/Jira:/);
    const add = row.getByRole("button", { name: ADD });
    const before = (a: Element, b: Element) => expect(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    before(tag, place);
    before(place, reference);
    before(reference, add);
    // One add control only: no separate tag, component or reference button.
    await expect(row.queryByRole("button", { name: "Add tag" })).not.toBeInTheDocument();
    await expect(row.queryByRole("button", { name: "Add external reference" })).not.toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...OneRowHoldsEveryKindAndTheAddControl, globals: { theme: "dark" } };

/** The menu names every addition, one row each. */
export const TheMenuNamesEachAddition: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: ADD }));
    const menu = within(await within(document.body).findByRole("menu"));
    await expect(menu.getAllByRole("menuitem").map((item) => item.textContent?.trim())).toEqual([
      "Add tag", "Add component or category", "Add external reference",
    ]);
  },
};

export const AddingATagSavesTheWholeSet: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openRecordTagBox(canvas), "sec");
    await userEvent.click(await within(document.body).findByRole("option", { name: "Security" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", ["Safety", "Security"]));
    await expect(await canvas.findByRole("button", { name: "Remove tag Security" })).toBeInTheDocument();
  },
};

export const RemovingATagSavesWithoutIt: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Remove tag Safety" }));
    await waitFor(() => expect(args.api!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", []));
  },
};

/** A refused save puts the tags back as they were and says why. */
export const ARefusedTagSaveIsRevertedWithAMessage: Story = {
  args: {
    api: buildRecordTagsApi(buildRecordTags({ restricted: false }), {
      set: fn(async () => { throw new Error("'Security' is not in the tag list."); }),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await openRecordTagBox(canvas), "sec");
    await userEvent.click(await within(document.body).findByRole("option", { name: "Security" }));
    await waitFor(() => expect(canvas.queryByRole("button", { name: "Remove tag Security" })).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Remove tag Safety" })).toBeInTheDocument();
    await expect(await within(document.body).findByText(/Could not save the tags: 'Security' is not in the tag list\./)).toBeInTheDocument();
  },
};

/** In a restricted project the tag box is a picker only. */
export const RestrictedProjectOffersTheListOnly: Story = {
  args: { api: buildRecordTagsApi(buildRecordTags({ restricted: true, tags: [] })) },
  play: async ({ canvasElement }) => {
    await expect(await openRecordTagBox(within(canvasElement))).toHaveAttribute("placeholder", "Choose a tag…");
  },
};

export const ChangedCallbackFiresAfterASave: Story = {
  args: { onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Remove tag Safety" }));
    await waitFor(() => expect(args.onChanged).toHaveBeenCalled());
  },
};

export const AddingAComponentFromTheMenu: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await chooseAddition(canvas, "Add component or category");
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add component or category" }));
    await userEvent.click(await dialog.findByRole("button", { name: "Components and categories" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Software" }));
    await waitFor(() => expect(args.placementsApi!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", [
      { component_id: "c-hw", category_id: "k-cool" },
      { component_id: "c-sw", category_id: null },
    ]));
    await expect(await canvas.findByText("Software")).toBeInTheDocument();
  },
};

export const RemovingAComponentSavesWithoutIt: Story = {
  args: { placementsApi: buildPlacementsApi(buildRecordPlacements({ placements: [buildPlace("c-hw", "k-cool"), buildPlace("c-sw")] })) },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Remove Hardware / Cooling" }));
    await waitFor(() => expect(args.placementsApi!.set).toHaveBeenCalledWith(TAGS_PROJECT_ID, "requirement", "req-1", [
      { component_id: "c-sw", category_id: null },
    ]));
  },
};

export const ARefusedComponentChangeIsPutBack: Story = {
  args: { placementsApi: buildPlacementsApi(undefined, { set: fn(async () => { throw new Error("Refused."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove Hardware / Cooling" }));
    await expect(await canvas.findByText("Hardware / Cooling")).toBeInTheDocument();
    await expect(await within(document.body).findByText(/Could not save the components: Refused\./)).toBeInTheDocument();
  },
};

export const AddingAReferenceFromTheMenuSavesItAndSaysSo: Story = {
  args: { onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await chooseAddition(canvas, "Add external reference");
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add an external reference" }));
    // Save needs a system and a key or a link.
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "System" }), "DOORS");
    await userEvent.type(dialog.getByRole("textbox", { name: "Key" }), "REQ-77");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Role" }), "Delivery");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.referencesApi!.add).toHaveBeenCalledWith(
      REFERENCES_PROJECT_ID, "requirement", "req-1",
      { system_id: "s-doors", key: "REQ-77", url: null, note: "", role: "delivery" },
    ));
    await expect(await within(document.body).findByText("Reference added.")).toBeInTheDocument();
    await expect(args.onChanged).toHaveBeenCalled();
    await expect(await canvas.findByText(/REQ-77/)).toBeInTheDocument();
  },
};

export const EditingAReferenceChangesOnlyThatOne: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Edit reference DOORS: REQ-9" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit external reference" }));
    const key = dialog.getByRole("textbox", { name: "Key" });
    await expect(key).toHaveValue("REQ-9");
    await userEvent.clear(key);
    await userEvent.type(key, "REQ-10");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.referencesApi!.update).toHaveBeenCalledWith(
      REFERENCES_PROJECT_ID, "requirement", "req-1", "ref-s-doors-REQ-9",
      { system_id: "s-doors", key: "REQ-10", url: null, note: "", role: null },
    ));
    await expect(await within(document.body).findByText("Reference saved.")).toBeInTheDocument();
  },
};

/** Removing asks first (the key is not always easy to type again); cancelling changes nothing. */
export const RemovingAReferenceAsksFirst: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    let dialog = within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(args.referencesApi!.remove).not.toHaveBeenCalled();
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    dialog = within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.referencesApi!.remove).toHaveBeenCalledWith(REFERENCES_PROJECT_ID, "requirement", "req-1", "ref-s-doors-REQ-9"));
    await expect(await within(document.body).findByText("Reference removed.")).toBeInTheDocument();
    await waitFor(() => expect(canvas.queryByText(/REQ-9/)).not.toBeInTheDocument());
  },
};

/** A refused save keeps the dialog open and says why beside the actions. */
export const ARefusedReferenceSaveStaysInTheDialog: Story = {
  args: { referencesApi: buildReferencesApi(undefined, { add: fn(async () => { throw new ApiError(400, "A record can have at most 50 references."); }) }) },
  play: async ({ canvasElement }) => {
    await chooseAddition(within(canvasElement), "Add external reference");
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add an external reference" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "System" }), "Jira");
    await userEvent.type(dialog.getByRole("textbox", { name: "Key" }), "PROJ-2");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText("Could not save the reference: A record can have at most 50 references.")).toBeInTheDocument();
  },
};

export const ARefusedReferenceRemovalIsReportedAndTheReferenceStays: Story = {
  args: { referencesApi: buildReferencesApi(undefined, { remove: fn(async () => { throw new ApiError(403, "Not allowed."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" })).getByRole("button", { name: "Remove" }));
    await expect(await within(document.body).findByText("Could not remove the reference: Not allowed.")).toBeInTheDocument();
    await expect(canvas.getByText(/REQ-9/)).toBeInTheDocument();
  },
};

/** A reference is a link only for an absolute http(s) address, whatever the server returned. */
export const AReferenceLinksOnlyToAWebAddress: Story = {
  args: {
    referencesApi: buildReferencesApi(buildRecordReferences({
      can_edit: false, references: [buildReference({ key: "X-1", link: "javascript:alert(1)" }), buildReference({ key: "PROJ-1" })],
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/X-1/)).toBeInTheDocument();
    const link = canvas.getByRole("link", { name: "Open Jira: PROJ-1 in a new tab" });
    await expect(link).toHaveAttribute("href", "https://tracker.example/browse/PROJ-1");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(canvas.getAllByRole("link")).toHaveLength(1);
  },
};

/** Without any right to change a kind, only chips are drawn: no remove, no edit, no (+). */
export const ReadOnlyForSomeoneWhoCannotChangeAnything: Story = {
  args: {
    api: buildRecordTagsApi(buildRecordTags({ can_edit: false })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ can_edit: false })),
    referencesApi: buildReferencesApi(buildRecordReferences({ can_edit: false })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Safety")).toBeInTheDocument();
    await expect(await canvas.findByText("Hardware / Cooling")).toBeInTheDocument();
    await expect(await canvas.findByText(/Jira:/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: ADD })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Remove|Edit/ })).not.toBeInTheDocument();
  },
};

/** A row of the menu is absent, not disabled, when the person cannot do it; the others stay. */
export const OnlyTheRowsThePersonMayUseAreInTheMenu: Story = {
  args: {
    api: buildRecordTagsApi(buildRecordTags({ can_edit: false })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ can_edit: false })),
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add external reference" }));
    const menu = within(await within(document.body).findByRole("menu"));
    await expect(menu.getAllByRole("menuitem")).toHaveLength(1);
    await expect(menu.getByRole("menuitem", { name: "Add external reference" })).toBeEnabled();
  },
};

/** With no system to refer to there is no reference row. */
export const NoReferenceRowWhenThereIsNoSystem: Story = {
  args: { referencesApi: buildReferencesApi(buildRecordReferences({ systems: [] })) },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add tag or component" }));
    const menu = within(await within(document.body).findByRole("menu"));
    await expect(menu.queryByRole("menuitem", { name: "Add external reference" })).not.toBeInTheDocument();
    await expect(menu.getAllByRole("menuitem")).toHaveLength(2);
  },
};

/** The (+) is named after exactly the rows its menu holds: every combination, in the menu's order. */
const NO_TAGS = { api: buildRecordTagsApi(buildRecordTags({ can_edit: false })) };
const NO_PLACES = { placementsApi: buildPlacementsApi(buildRecordPlacements({ can_edit: false })) };
const NO_REFERENCES = { referencesApi: buildReferencesApi(buildRecordReferences({ can_edit: false })) };

async function expectNameToMatchMenu(canvasElement: HTMLElement, name: string, rows: string[]): Promise<void> {
  const plus = await within(canvasElement).findByRole("button", { name });
  await userEvent.click(plus);
  const menu = within(await within(document.body).findByRole("menu", { name }));
  await expect(menu.getAllByRole("menuitem").map((item) => item.textContent?.trim())).toEqual(rows);
}

export const TheAddControlNamesTheTagRowAlone: Story = {
  args: { ...NO_PLACES, ...NO_REFERENCES },
  play: ({ canvasElement }) => expectNameToMatchMenu(canvasElement, "Add tag", ["Add tag"]),
};

export const TheAddControlNamesTheComponentRowAlone: Story = {
  args: { ...NO_TAGS, ...NO_REFERENCES },
  play: ({ canvasElement }) => expectNameToMatchMenu(canvasElement, "Add component or category", ["Add component or category"]),
};

export const TheAddControlNamesTagAndComponent: Story = {
  args: { ...NO_REFERENCES },
  play: ({ canvasElement }) => expectNameToMatchMenu(canvasElement, "Add tag or component", ["Add tag", "Add component or category"]),
};

export const TheAddControlNamesComponentAndReference: Story = {
  args: { ...NO_TAGS },
  play: ({ canvasElement }) => expectNameToMatchMenu(
    canvasElement, "Add component or external reference", ["Add component or category", "Add external reference"],
  ),
};

/** A record that keeps its own component (or a type left out with `components={false}`) has no component row or chips. */
export const NoComponentRowForARecordThatKeepsItsOwn: Story = {
  args: { placementsApi: buildPlacementsApi(buildRecordPlacements({ managed_on_record: true })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add tag or external reference" }));
    await expect(within(document.body).queryByRole("menuitem", { name: "Add component or category" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Hardware / Cooling")).not.toBeInTheDocument();
  },
};

export const ComponentsCanBeLeftOut: Story = {
  args: { components: false },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(await within(canvasElement).findByText("Safety")).toBeInTheDocument();
    await expect(args.placementsApi!.get).not.toHaveBeenCalled();
  },
};

/** A page that keeps its own references (a Product Feedback request) leaves them out. */
export const ReferencesCanBeLeftOut: Story = {
  args: { references: false },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(await within(canvasElement).findByText("Safety")).toBeInTheDocument();
    await expect(within(canvasElement).queryByText(/Jira:/)).not.toBeInTheDocument();
    await expect(args.referencesApi!.get).not.toHaveBeenCalled();
  },
};

/** Nothing is drawn for a record with no labels that the viewer cannot add to, so the header stays clean. */
export const NothingWhenThereIsNothingAndNoRightToAdd: Story = {
  args: {
    api: buildRecordTagsApi(buildRecordTags({ can_edit: false, tags: [] })),
    placementsApi: buildPlacementsApi(buildRecordPlacements({ can_edit: false, placements: [] })),
    referencesApi: buildReferencesApi(buildRecordReferences({ can_edit: false, references: [] })),
  },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await waitFor(() => expect(args.referencesApi!.get).toHaveBeenCalled());
    await expect(canvasElement.textContent).toBe("");
  },
};

/** The server answers 404 while references are switched off for the type: the references are left out, the rest stays. */
export const ReferencesSwitchedOffLeaveTheOtherKinds: Story = {
  args: { referencesApi: buildReferencesApi(undefined, { get: fn(async () => { throw new ApiError(404, "External references are switched off here."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Safety")).toBeInTheDocument();
    await userEvent.click(await canvas.findByRole("button", { name: "Add tag or component" }));
    await expect(within(document.body).queryByRole("menuitem", { name: "Add external reference" })).not.toBeInTheDocument();
  },
};

/** Labels that cannot be read leave the header without them rather than with an error. */
export const AFailedReadShowsNothing: Story = {
  args: {
    api: buildRecordTagsApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }),
    placementsApi: buildPlacementsApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }),
    referencesApi: buildReferencesApi(undefined, { get: fn(async () => { throw new Error("nope"); }) }),
  },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(canvasElement.textContent).toBe("");
  },
};

const NARROW: Decorator = (Story) => <div style={{ width: 260 }}><Story /></div>;

/** A row that wraps keeps the (+) after the last chip, on that chip's line, and never grows sideways. */
export const WrappingKeepsTheAddControlAfterTheLastChip: Story = {
  decorators: [NARROW],
  args: {
    api: buildRecordTagsApi(buildRecordTags({
      tags: ["Safety", "Release 2", "Security", "Thermal", "Mechanical", "Firmware"].map((name) => buildChip(name)),
    })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const add = await canvas.findByRole("button", { name: ADD });
    const chips = Array.from(canvasElement.querySelectorAll(".chip"));
    const last = chips[chips.length - 1].getBoundingClientRect();
    const plus = add.getBoundingClientRect();
    // After the last chip's line, never above it, and on its line when there is room.
    await expect(plus.top).toBeGreaterThanOrEqual(chips[0].getBoundingClientRect().top);
    await expect(Math.abs((plus.top + plus.height / 2) - (last.top + last.height / 2))).toBeLessThan(plus.height);
    const row = canvasElement.querySelector<HTMLElement>("[role=group]")!;
    await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth);
  },
};

/** Long unbroken names in several chips wrap inside the row; the row does not grow sideways and the (+) stays reachable. */
export const LongText: Story = {
  decorators: [NARROW],
  args: {
    api: buildRecordTagsApi(buildRecordTags({ tags: [buildChip("A".repeat(60)), buildChip("a very long tag name that goes on and on and on")] })),
    referencesApi: buildReferencesApi(buildRecordReferences({ references: [buildReference({ key: "K".repeat(60), note: "x".repeat(200) })] })),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: ADD });
    const row = canvasElement.querySelector<HTMLElement>("[role=group]")!;
    await expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth);
    for (const chip of Array.from(canvasElement.querySelectorAll(".chip"))) {
      await expect(chip.getBoundingClientRect().right).toBeLessThanOrEqual(row.getBoundingClientRect().right + 1);
    }
  },
};
