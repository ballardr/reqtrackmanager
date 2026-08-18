import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { FileAsset } from "../api/types";
import { RichTextEditor } from "./RichTextEditor";

function Interactive({ organizationId }: { organizationId?: string }) {
  const [value, setValue] = useState("Some **existing** body text.");
  return <RichTextEditor value={value} onChange={setValue} organizationId={organizationId} />;
}

const meta: Meta<typeof Interactive> = {
  title: "Components/RichTextEditor",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const MarkdownMode: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByDisplayValue(/existing/)).toBeInTheDocument();
    // No organizationId passed — the image-insert button must be hidden.
    await expect(canvas.queryByLabelText("Insert image")).not.toBeInTheDocument();
  },
};

export const SwitchToRichText: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Rich text" }));
    await expect(canvas.getByLabelText("Bold")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Bullet list")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Markdown" }));
    await expect(canvas.queryByLabelText("Bold")).not.toBeInTheDocument();
  },
};

/** `organizationId` set: enables the image-insert toolbar button and its
 * picker, backed by the org's shared image resources. */
export const ImagePickerWithOrgImages: Story = {
  args: { organizationId: "org-1" },
  beforeEach: () => {
    const images: FileAsset[] = [
      {
        id: "file-1", organization_id: "org-1", filename: "diagram.png", content_type: "image/png",
        size_bytes: 2048, uploaded_by: "user-1", is_org_resource: true, created_at: "2026-01-01T00:00:00Z",
      },
    ];
    spyOn(api, "get").mockResolvedValue(images);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByLabelText("Insert image"));
    await waitFor(() => expect(canvas.getByTitle("diagram.png")).toBeInTheDocument());
  },
};

export const ImagePickerLoadError: Story = {
  args: { organizationId: "org-1" },
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Could not load images."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByLabelText("Insert image"));
    await waitFor(() => expect(canvas.getByText("Could not load images.")).toBeInTheDocument());
  },
};

/** The link toolbar button opens the app's own Modal rather than the
 * browser's native `window.prompt()` (2026-08 UX audit finding — this was
 * the one native-prompt usage in the app) — portalled to `document.body`,
 * same as every other Modal usage in this codebase. */
export const InsertLink: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Rich text" }));
    await userEvent.click(canvas.getByLabelText("Link"));

    const modal = within(document.body).getByRole("dialog");
    await expect(within(modal).getByText("Insert link")).toBeInTheDocument();
    const insertButton = within(modal).getByRole("button", { name: "Insert" });
    await expect(insertButton).toBeDisabled();

    await userEvent.type(within(modal).getByLabelText("Link URL"), "https://example.com");
    await expect(insertButton).toBeEnabled();
    await userEvent.click(insertButton);
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
