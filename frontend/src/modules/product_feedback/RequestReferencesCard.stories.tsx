import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildExternalRef } from "./requestFixtures";
import { RequestReferencesCard } from "./RequestReferencesCard";

const meta: Meta<typeof RequestReferencesCard> = {
  title: "Modules/ProductFeedback/RequestReferencesCard",
  component: RequestReferencesCard,
  args: {
    references: [
      buildExternalRef(),
      buildExternalRef({ id: "ref-2", system_id: "system-servicenow", system_name: "ServiceNow", key: "INC0012345", url: null, role: "origin" }),
    ],
    canEdit: true, onAdd: fn(), onEdit: fn(), onRemove: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof RequestReferencesCard>;

/** Each reference reads as system, item and role; a link opens in a new tab and a key without one is plain text. */
export const ListsReferencesWithSystemAndRole: Story = {
  play: async ({ canvasElement }) => {
    const table = within(within(canvasElement).getByRole("table", { name: "External references" }));
    const link = table.getByRole("link", { name: "PROJ-123" });
    await expect(link).toHaveAttribute("href", "https://jira.example.com/browse/PROJ-123");
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
    await expect(table.getByText("INC0012345")).toBeInTheDocument();
    await expect(table.queryByRole("link", { name: "INC0012345" })).not.toBeInTheDocument();
    await expect(table.getByText("Came from")).toBeInTheDocument();
    await expect(table.getByText("Delivered in")).toBeInTheDocument();
  },
};

/** A stored value that is not an http(s) URL is shown as text, never as a link. */
export const ANonWebLinkIsNeverClickable: Story = {
  args: { references: [buildExternalRef({ key: "", url: "javascript:alert(1)" })] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("javascript:alert(1)")).toBeInTheDocument();
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};

/** A triager adds, changes and removes; the buttons call back with the reference concerned. */
export const ATriagerCanAddEditAndRemove: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add reference" }));
    await expect(args.onAdd).toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: "Edit reference PROJ-123" }));
    await expect(args.onEdit).toHaveBeenCalledWith(args.references[0]);
    await userEvent.click(canvas.getByRole("button", { name: "Remove reference INC0012345" }));
    await expect(args.onRemove).toHaveBeenCalledWith(args.references[1]);
  },
};

/** Everyone else reads the list and sees no controls. */
export const AReaderSeesNoControls: Story = {
  args: { canEdit: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

export const EmptyExplainsWhatToAdd: Story = {
  args: { references: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText(/No outside tickets yet/)).toBeInTheDocument();
  },
};
