import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildFileAsset } from "../testing/storybook-helpers";
import { ResourcePickerModal } from "./ResourcePickerModal";

const meta: Meta<typeof ResourcePickerModal> = {
  title: "Components/ResourcePickerModal",
  component: ResourcePickerModal,
};
export default meta;

type Story = StoryObj<typeof ResourcePickerModal>;

const orgResourcesSource = {
  id: "org-resources",
  label: "Acme Corp shared resources",
  loadFiles: async () => [
    buildFileAsset({ id: "res-1", filename: "safety-spec.pdf", is_org_resource: true }),
    buildFileAsset({ id: "res-2", filename: "onboarding-checklist.docx", is_org_resource: true }),
  ],
};

/** Selecting files and pressing "Attach selected" calls `onAttach` with
 * every checked file id, then closes — the core flow first wired up on
 * `RequirementDetailPage.tsx`'s Attachments card. */
export const SelectAndAttach: Story = {
  args: {
    title: "Link from shared resources",
    sources: [orgResourcesSource],
    onClose: fn(),
    onAttach: fn(async () => {}),
  },
  play: async ({ args }) => {
    // Rendered through a portal into document.body, not canvasElement — see Modal.stories.tsx.
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("safety-spec.pdf")).toBeInTheDocument());
    const attachButton = body.getByRole("button", { name: "Attach selected" });
    await expect(attachButton).toBeDisabled();

    await userEvent.click(body.getByRole("checkbox", { name: "safety-spec.pdf" }));
    await expect(body.getByRole("button", { name: "Attach 1 selected" })).toBeEnabled();
    await userEvent.click(body.getByRole("button", { name: "Attach 1 selected" }));

    await waitFor(() => expect(args.onAttach).toHaveBeenCalledWith(["res-1"]));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** Multiple sources: the left pane lists every source, switching reloads
 * the right pane's files for the newly-active one — built pluggable
 * (`sources: ResourcePickerSource[]`) so a future source (a report
 * chapter's image pool, a project's own uploads) is a new array entry,
 * not a rewrite. */
export const MultipleSources: Story = {
  args: {
    title: "Link from shared resources",
    sources: [
      orgResourcesSource,
      {
        id: "project-uploads",
        label: "This project's own uploads",
        loadFiles: async () => [buildFileAsset({ id: "res-3", filename: "risk-register.xlsx" })],
      },
    ],
    onClose: fn(),
    onAttach: fn(async () => {}),
  },
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("safety-spec.pdf")).toBeInTheDocument());
    await expect(body.queryByText("risk-register.xlsx")).not.toBeInTheDocument();

    await userEvent.click(body.getByRole("button", { name: "This project's own uploads" }));
    await waitFor(() => expect(body.getByText("risk-register.xlsx")).toBeInTheDocument());
    await expect(body.queryByText("safety-spec.pdf")).not.toBeInTheDocument();
  },
};

export const EmptySource: Story = {
  args: {
    title: "Link from shared resources",
    sources: [{ id: "org-resources", label: "Acme Corp shared resources", loadFiles: async () => [] }],
    onClose: fn(),
    onAttach: fn(async () => {}),
  },
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("No files available in this source.")).toBeInTheDocument());
  },
};

/** A failed attach (e.g. the requirement became locked mid-flow) shows an
 * inline error and leaves the dialog open, rather than closing on a
 * rejected promise. */
export const AttachErrorStaysOpen: Story = {
  args: {
    title: "Link from shared resources",
    sources: [orgResourcesSource],
    onClose: fn(),
    onAttach: fn(async () => {
      throw new Error("This requirement is approved; new attachments must be added via a change request.");
    }),
  },
  play: async ({ args }) => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("safety-spec.pdf")).toBeInTheDocument());
    await userEvent.click(body.getByRole("checkbox", { name: "safety-spec.pdf" }));
    await userEvent.click(body.getByRole("button", { name: "Attach 1 selected" }));

    await waitFor(() =>
      expect(
        body.getByText("This requirement is approved; new attachments must be added via a change request.")
      ).toBeInTheDocument()
    );
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

export const LightTheme: Story = { ...SelectAndAttach, globals: { theme: "light" } };
export const DarkTheme: Story = { ...SelectAndAttach, globals: { theme: "dark" } };
