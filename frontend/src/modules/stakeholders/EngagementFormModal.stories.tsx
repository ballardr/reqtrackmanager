import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";

import { buildEngagement, buildPersona, buildStakeholder } from "./fixtures";
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
    }, [], []);
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

/** A new engagement can name its participants; they are sent as `stakeholder_ids`, and an edit never offers the field. */
export const CreateNamesParticipants: Story = {
  args: { projectId: "project-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/projects/project-1/modules/stakeholders/stakeholders") {
        return [buildStakeholder(), buildStakeholder({ id: "stakeholder-2", name: "Sam Client" })];
      }
      return [];
    });
  },
  play: async ({ args }) => {
    await waitFor(() => dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.type(dialog().getByLabelText("Engagement title"), "Workshop");
    await userEvent.click(dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Participant Sam Client" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ title: "Workshop", stakeholder_ids: ["stakeholder-2"] }), [], []);
  },
};

/** With the research extras on, text typed in Participants that is not a Stakeholder is added as an anonymous participant, whose Persona is then chosen. */
export const CreateAddsAnonymousParticipants: Story = {
  args: { projectId: "project-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/projects/project-1/modules/stakeholders/subcomponents") {
        return [{ module_key: "stakeholders", subcomponent_key: "research_extras", name: "Research extras", effective_enabled: true }];
      }
      if (path === "/api/v1/projects/project-1/modules/stakeholders/personas") return [buildPersona()];
      if (path === "/api/v1/projects/project-1/modules/stakeholders/stakeholders") return [buildStakeholder()];
      return [];
    });
  },
  play: async ({ args }) => {
    await waitFor(() => dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.type(dialog().getByLabelText("Engagement title"), "Focus group");
    await userEvent.click(dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.type(await within(document.body).findByRole("searchbox"), "Participant 1");
    await userEvent.click(within(document.body).getByRole("button", { name: "Add “Participant 1” as an anonymous participant" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => dialog().getByLabelText("Persona represented by Participant 1"));
    await userEvent.selectOptions(dialog().getByLabelText("Persona represented by Participant 1"), "persona-1");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Focus group", anonymous_participants: [{ label: "Participant 1", persona_id: "persona-1" }] }), [], [],
    );
  },
};

/** While the research extras are off typed text matching no Stakeholder offers nothing to add, since the request would be refused. */
export const AnonymousParticipantsNeedTheResearchExtras: Story = {
  args: { projectId: "project-1" },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) =>
      path === "/api/v1/projects/project-1/modules/stakeholders/stakeholders" ? [buildStakeholder()] : [],
    );
  },
  play: async () => {
    await waitFor(() => dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.type(await within(document.body).findByRole("searchbox"), "Participant 1");
    await expect(within(document.body).queryByRole("button", { name: /as an anonymous participant/ })).not.toBeInTheDocument();
  },
};

/** An edit given no recorded participants (they could not be read) has no Participants field, so a save cannot wipe them. */
export const EditWithoutRecordedParticipantsOffersNone: Story = {
  args: { initial: buildEngagement(), projectId: "project-1" },
  play: async () => {
    await waitFor(() => dialog().getByLabelText("Engagement title"));
    await expect(dialog().queryByRole("button", { name: "Add to Participants" })).not.toBeInTheDocument();
  },
};

/** An edit starts from the recorded participants, lets a late arrival or a newly known Persona be added, and returns the complete lists. */
export const EditChangesTheRecordedParticipants: Story = {
  args: {
    initial: buildEngagement(),
    projectId: "project-1",
    initialParticipants: {
      stakeholderIds: ["stakeholder-1"],
      anonymous: [{ id: "ap1", label: "Participant 1", persona_id: null, persona_name: null }],
    },
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path === "/api/v1/projects/project-1/modules/stakeholders/subcomponents") {
        return [{ module_key: "stakeholders", subcomponent_key: "research_extras", name: "Research extras", effective_enabled: true }];
      }
      if (path === "/api/v1/projects/project-1/modules/stakeholders/personas") return [buildPersona()];
      if (path === "/api/v1/projects/project-1/modules/stakeholders/stakeholders") return [buildStakeholder(), buildStakeholder({ id: "stakeholder-2", name: "Sam Client" })];
      return [];
    });
  },
  play: async ({ args }) => {
    await waitFor(() => dialog().getByLabelText("Persona represented by Participant 1"));
    await expect(dialog().getByRole("button", { name: "Remove Pat Regulator" })).toBeInTheDocument();
    await userEvent.selectOptions(dialog().getByLabelText("Persona represented by Participant 1"), "persona-1");
    await userEvent.click(dialog().getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Participant Sam Client" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        stakeholder_ids: ["stakeholder-1", "stakeholder-2"],
        anonymous_participants: [expect.objectContaining({ id: "ap1", label: "Participant 1", persona_id: "persona-1" })],
      }), [], [],
    );
  },
};
