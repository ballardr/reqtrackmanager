import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { buildRecordReferences, buildReference, buildReferencesApi, REFERENCES_PROJECT_ID } from "../testing/referencesFixtures";
import { RecordReferences } from "./RecordReferences";

/**
 * The external references of one existing record, in its header: a chip per reference (system and key, the key a link
 * when the item has one, the role as a badge, the note as a tooltip) and, for someone who may change them, buttons to
 * add, edit and remove one. Every change is saved at once and reported in a toast.
 */
const meta: Meta<typeof RecordReferences> = {
  title: "Components/RecordReferences",
  component: RecordReferences,
  args: { projectId: REFERENCES_PROJECT_ID, artefactType: "pain_point", artefactId: "record-1" },
};
export default meta;

type Story = StoryObj<typeof RecordReferences>;

export const ShowsEachReferenceWithItsLinkAndRole: Story = {
  args: { api: buildReferencesApi() },
  play: async ({ canvasElement }) => {
    const group = within(await within(canvasElement).findByRole("group", { name: "External references" }));
    const link = await group.findByRole("link", { name: "Open Jira: PROJ-1 in a new tab" });
    await expect(link).toHaveAttribute("href", "https://tracker.example/browse/PROJ-1");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(group.getByText("Origin")).toBeInTheDocument();
    // A reference with no link shows its key as plain text.
    await expect(group.getByText(/DOORS:/)).toBeInTheDocument();
    await expect(group.queryByRole("link", { name: /DOORS/ })).not.toBeInTheDocument();
  },
};

/** Only an absolute http(s) address becomes a link, whatever the server returned. */
export const NeverLinksAnythingButAWebAddress: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ can_edit: false, references: [buildReference({ key: "X-1", link: "javascript:alert(1)" })] })) },
  play: async ({ canvasElement }) => {
    const group = within(await within(canvasElement).findByRole("group", { name: "External references" }));
    await expect(await group.findByText(/X-1/)).toBeInTheDocument();
    await expect(group.queryByRole("link")).not.toBeInTheDocument();
  },
};

export const AddingAReferenceSavesItAndSaysSo: Story = {
  args: { api: buildReferencesApi(), onChanged: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add external reference" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add an external reference" }));
    // Save needs a system and a key or a link.
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "System" }), "DOORS");
    await userEvent.type(dialog.getByRole("textbox", { name: "Key" }), "REQ-77");
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Role" }), "Delivery");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.add).toHaveBeenCalledWith(
      REFERENCES_PROJECT_ID, "pain_point", "record-1",
      { system_id: "s-doors", key: "REQ-77", url: null, note: "", role: "delivery" },
    ));
    await expect(await within(document.body).findByText("Reference added.")).toBeInTheDocument();
    await expect(args.onChanged).toHaveBeenCalled();
    await expect(await canvas.findByText(/REQ-77/)).toBeInTheDocument();
  },
};

export const EditingAReferenceChangesOnlyThatOne: Story = {
  args: { api: buildReferencesApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit reference DOORS: REQ-9" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit external reference" }));
    const key = dialog.getByRole("textbox", { name: "Key" });
    await expect(key).toHaveValue("REQ-9");
    await userEvent.clear(key);
    await userEvent.type(key, "REQ-10");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith(
      REFERENCES_PROJECT_ID, "pain_point", "record-1", "ref-s-doors-REQ-9",
      { system_id: "s-doors", key: "REQ-10", url: null, note: "", role: null },
    ));
    await expect(await within(document.body).findByText("Reference saved.")).toBeInTheDocument();
  },
};

/** Removing asks first (the key is not always easy to type again); cancelling changes nothing. */
export const RemovingAReferenceAsksFirst: Story = {
  args: { api: buildReferencesApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    let dialog = within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await expect(args.api!.remove).not.toHaveBeenCalled();
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    dialog = within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith(REFERENCES_PROJECT_ID, "pain_point", "record-1", "ref-s-doors-REQ-9"));
    await expect(await within(document.body).findByText("Reference removed.")).toBeInTheDocument();
    await waitFor(() => expect(canvas.queryByText(/REQ-9/)).not.toBeInTheDocument());
  },
};

/** A refused save keeps the dialog open and says why beside the actions. */
export const ARefusedSaveStaysInTheDialog: Story = {
  args: { api: buildReferencesApi(undefined, { add: fn(async () => { throw new ApiError(400, "A record can have at most 50 references."); }) }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Add external reference" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add an external reference" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "System" }), "Jira");
    await userEvent.type(dialog.getByRole("textbox", { name: "Key" }), "PROJ-2");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(await dialog.findByText("Could not save the reference: A record can have at most 50 references.")).toBeInTheDocument();
  },
};

export const ARefusedRemovalIsReportedAndTheReferenceStays: Story = {
  args: { api: buildReferencesApi(undefined, { remove: fn(async () => { throw new ApiError(403, "Not allowed."); }) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Remove reference DOORS: REQ-9" }));
    await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Remove this reference?" })).getByRole("button", { name: "Remove" }));
    await expect(await within(document.body).findByText("Could not remove the reference: Not allowed.")).toBeInTheDocument();
    await expect(canvas.getByText(/REQ-9/)).toBeInTheDocument();
  },
};

export const ReadOnlyForSomeoneWhoCannotChangeThem: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ can_edit: false })) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/DOORS:/)).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Edit reference|Remove reference|Add external reference/ })).not.toBeInTheDocument();
  },
};

export const NothingWhenThereAreNoneAndTheViewerCannotAdd: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ can_edit: false, references: [] })) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("group")).not.toBeInTheDocument();
  },
};

/** The server answers 404 while references are switched off for the record's type: the panel is not drawn. */
export const NothingWhileReferencesAreSwitchedOff: Story = {
  args: { api: buildReferencesApi(undefined, { get: fn(async () => { throw new ApiError(404, "External references are switched off here."); }) }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.get).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("group")).not.toBeInTheDocument();
  },
};

/** Someone who may add the first reference sees the control even when the record has none. */
export const AnEditorCanAddTheFirstReference: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ references: [] })) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("button", { name: "Add external reference" })).toBeInTheDocument();
  },
};

export const ExplainsReferencesInAHelpTooltip: Story = {
  args: { api: buildReferencesApi(buildRecordReferences({ references: [] })) },
  play: async ({ canvasElement }) => {
    await userEvent.hover(await within(canvasElement).findByRole("button", { name: "Help: External references" }));
    await expect(await within(document.body).findByText(/Items in outside systems/)).toBeInTheDocument();
  },
};
