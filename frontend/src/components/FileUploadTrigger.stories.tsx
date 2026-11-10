import type { Meta, StoryObj } from "@storybook/react-vite";
import { Paperclip } from "lucide-react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ServerSettings } from "../api/types";
import { BrandingProvider } from "../context/BrandingContext";
import { withThemeProvider } from "../testing/storybook-helpers";
import { FileUploadTrigger } from "./FileUploadTrigger";

const meta: Meta<typeof FileUploadTrigger> = {
  title: "Components/FileUploadTrigger",
  component: FileUploadTrigger,
  args: { onSelect: fn() },
};
export default meta;

type Story = StoryObj<typeof FileUploadTrigger>;

export const IconAndText: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Attach a file")).toBeInTheDocument();
  },
};

/** Selecting a file fires `onSelect` with the chosen `File` and resets the
 * underlying input's value, so choosing the same filename again still
 * fires a change event (see `CommentThread`'s repeated-attachment case). */
export const SelectingAFileCallsOnSelect: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  play: async ({ canvasElement, args }) => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    const input = canvasElement.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await expect(args.onSelect).toHaveBeenCalledWith(file);
    await expect(input.value).toBe("");
  },
};

export const Disabled: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</>, disabled: true },
  play: async ({ canvasElement }) => {
    const input = canvasElement.querySelector('input[type="file"]') as HTMLInputElement;
    await expect(input).toBeDisabled();
  },
};

/** `showTrigger={false}` mounts only the (still hidden) input — used by
 * `CsvImportWizard` when a split-button elsewhere opens the file picker
 * itself via a forwarded ref, rather than rendering its own visible
 * trigger a second time on the same screen. */
export const HiddenTriggerStillMountsInput: Story = {
  args: { children: <><Paperclip size={14} /> Attach a file</>, showTrigger: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByText("Attach a file")).not.toBeInTheDocument();
    await expect(canvasElement.querySelector('input[type="file"]')).not.toBeNull();
  },
};

export const LightTheme: Story = { ...IconAndText, globals: { theme: "light" } };
export const DarkTheme: Story = { ...IconAndText, globals: { theme: "dark" } };

const UPLOADS_DISABLED_SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null,
  logo_band_color_hex: null, logo_band_text_color_hex: null, footer_position: "after_content",
  default_login_background_file_id: null, email_footer_company_name: null, email_footer_website: null,
  email_footer_address: null, footer_prefix: null, company_id_label: null, company_id: null, org_label_singular: null, org_label_plural: null, file_uploads_enabled: false,
};

/** While the server administrator has disabled file uploads the trigger stays visible but unavailable, its input
 * cannot be used, and a tooltip says why. */
export const UnavailableWhileUploadsAreDisabled: Story = {
  decorators: [
    (Story) => <BrandingProvider projectId={null}><Story /></BrandingProvider>,
    withThemeProvider(),
  ],
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string): Promise<never> => {
      if (path.includes("/system/branding")) return UPLOADS_DISABLED_SETTINGS as never;
      return [] as never;
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", { name: /Attach a file/ });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-disabled", "true"));
    await expect(canvasElement.querySelector('input[type="file"]')).toBeDisabled();
    await userEvent.hover(trigger);
    await expect(await within(canvasElement.ownerDocument.body).findByText(/File uploads are disabled on this deployment/)).toBeInTheDocument();
  },
};

const ORGANISATION_UPLOADS_DISABLED = {
  id: "org-1", name: "Acme", logo_file_id: null, header_title: null, accent_color_hex: null, file_uploads_enabled: false,
};

/** While only the organisation's own switch is off the trigger is unavailable too, and the tooltip names the
 * organisation as the reason. */
export const UnavailableWhileTheOrganisationHasUploadsDisabled: Story = {
  decorators: [
    (Story) => <BrandingProvider projectId={null}><Story /></BrandingProvider>,
    withThemeProvider(),
  ],
  args: { children: <><Paperclip size={14} /> Attach a file</> },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string): Promise<never> => {
      if (path.includes("/system/branding")) return { ...UPLOADS_DISABLED_SETTINGS, file_uploads_enabled: true } as never;
      if (path.endsWith("/api/v1/orgs")) return [ORGANISATION_UPLOADS_DISABLED] as never;
      return [] as never;
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", { name: /Attach a file/ });
    await waitFor(() => expect(trigger).toHaveAttribute("aria-disabled", "true"));
    await userEvent.hover(trigger);
    await expect(await within(canvasElement.ownerDocument.body).findByText(/File uploads are disabled for this organisation/)).toBeInTheDocument();
  },
};
