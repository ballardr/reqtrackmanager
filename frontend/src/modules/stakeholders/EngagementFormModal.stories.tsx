import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildEngagement } from "./fixtures";
import { EngagementFormModal } from "./EngagementFormModal";

const meta: Meta<typeof EngagementFormModal> = {
  title: "Modules/Stakeholders/EngagementFormModal",
  component: EngagementFormModal,
  args: { onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof EngagementFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateRequiresATitle: Story = {
  play: async () => {
    await waitFor(() => dialog().getByLabelText("Engagement title"));
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Engagement title"), "Kick-off call");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeEnabled();
  },
};

export const ChannelsUseTheirLabels: Story = {
  play: async () => {
    await waitFor(() => dialog().getByLabelText("Channel"));
    const channel = dialog().getByLabelText("Channel");
    await expect(within(channel).getByRole("option", { name: "Focus group" })).toBeInTheDocument();
    await expect(within(channel).getByRole("option", { name: "Usability test" })).toBeInTheDocument();
    await expect(within(channel).queryByRole("option", { name: "focus_group" })).not.toBeInTheDocument();
  },
};

export const SavePassesTheValues: Story = {
  play: async ({ args }) => {
    await waitFor(() => dialog().getByLabelText("Engagement title"));
    await userEvent.type(dialog().getByLabelText("Engagement title"), "  Workshop  ");
    await userEvent.selectOptions(dialog().getByLabelText("Channel"), "workshop");
    await userEvent.clear(dialog().getByLabelText("Date"));
    await userEvent.type(dialog().getByLabelText("Date"), "2026-04-02");
    await userEvent.type(dialog().getByLabelText("Summary"), "Mapped the journey.");
    await userEvent.click(dialog().getByLabelText("Consent recorded"));
    await userEvent.type(dialog().getByLabelText("Retain until"), "2027-04-02");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      title: "Workshop", channel: "workshop", engagement_date: "2026-04-02", purpose: "", summary: "Mapped the journey.",
      notes: "", consent_recorded: true, retain_until: "2027-04-02",
    }, []);
  },
};

export const EditPrefillsTheForm: Story = {
  args: { initial: buildEngagement({ retain_until: "2027-01-01" }) },
  play: async () => {
    await waitFor(() => within(document.body).getByRole("dialog", { name: "Edit Quarterly review with the regulator" }));
    await expect(dialog().getByLabelText("Engagement title")).toHaveValue("Quarterly review with the regulator");
    await expect(dialog().getByLabelText("Channel")).toHaveValue("meeting");
    await expect(dialog().getByLabelText("Date")).toHaveValue("2026-03-12");
    await expect(dialog().getByLabelText("Consent recorded")).toBeChecked();
    await expect(dialog().getByLabelText("Retain until")).toHaveValue("2027-01-01");
  },
};

/** The quick add keeps only the four fields a one-line contact needs. */
export const CompactShowsOnlyTheQuickFields: Story = {
  args: { compact: true, heading: "Log contact with Pat Regulator", defaults: { title: "Contact with Pat Regulator", channel: "email" } },
  play: async () => {
    await waitFor(() => within(document.body).getByRole("dialog", { name: "Log contact with Pat Regulator" }));
    await expect(dialog().getByLabelText("Engagement title")).toHaveValue("Contact with Pat Regulator");
    await expect(dialog().getByLabelText("Channel")).toHaveValue("email");
    await expect(dialog().getByLabelText("Summary")).toBeInTheDocument();
    await expect(dialog().queryByLabelText("Notes")).not.toBeInTheDocument();
    await expect(dialog().queryByLabelText("Consent recorded")).not.toBeInTheDocument();
    await expect(dialog().queryByLabelText("Retain until")).not.toBeInTheDocument();
  },
};

export const ShowsASaveError: Story = {
  args: { error: "Only an Engagement Owner may do this." },
  play: async () => {
    await waitFor(() => expect(dialog().getByText("Only an Engagement Owner may do this.")).toBeInTheDocument());
  },
};

export const DarkTheme: Story = { ...CreateRequiresATitle, globals: { theme: "dark" } };
