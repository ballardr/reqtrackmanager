import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildPersona, buildStakeholder } from "./fixtures";
import { ParticipantsField } from "./ParticipantsField";
import type { AnonymousParticipantDraft } from "./types";

const STAKEHOLDERS = [buildStakeholder(), buildStakeholder({ id: "stakeholder-2", name: "Sam Client" })];
const loadTwo = async () => STAKEHOLDERS;
const loadNone = async () => [];
const loadFails = async () => {
  throw new Error("forbidden");
};

function Harness({ load }: { load: () => Promise<typeof STAKEHOLDERS> }) {
  const [value, setValue] = useState<string[]>([]);
  const [anonymous, setAnonymous] = useState<AnonymousParticipantDraft[]>([]);
  return <ParticipantsField projectId="project-1" value={value} onChange={setValue} anonymous={anonymous} onAnonymousChange={setAnonymous} load={load} />;
}

const meta: Meta<typeof ParticipantsField> = { title: "Modules/Stakeholders/ParticipantsField", component: ParticipantsField };
export default meta;

type Story = StoryObj<typeof ParticipantsField>;

export const ChoosesSeveralStakeholders: Story = {
  render: () => <Harness load={loadTwo} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Participants" }));
    await expect(canvas.getByText("No participants added.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Participant Pat Regulator" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Participant Sam Client" }));
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(canvas.getByRole("button", { name: "Remove Pat Regulator" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Remove Sam Client" })).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove Sam Client" }));
    await expect(canvas.queryByRole("button", { name: "Remove Sam Client" })).not.toBeInTheDocument();
  },
};

/** A project without Stakeholders gets an empty state naming the next step, not an empty dropdown. */
export const ExplainsAnEmptyProject: Story = {
  render: () => <Harness load={loadNone} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/No Stakeholders exist in this project yet\./)).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Add to Participants" })).not.toBeInTheDocument();
  },
};

/** When the Stakeholders cannot be read the field is not offered. */
export const IsHiddenWhenTheListCannotBeRead: Story = {
  render: () => <Harness load={loadFails} />,
  play: async ({ canvasElement }) => {
    await new Promise((resolve) => setTimeout(resolve, 50));
    await expect(within(canvasElement).queryByText("Participants")).not.toBeInTheDocument();
  },
};

const withResearchExtras = () => {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/projects/project-1/modules/stakeholders/subcomponents") {
      return [{ module_key: "stakeholders", subcomponent_key: "research_extras", name: "Research extras", effective_enabled: true }];
    }
    if (path === "/api/v1/projects/project-1/modules/stakeholders/personas") return [buildPersona()];
    return [];
  });
};

/** With the Research extras on, typing a name that is not a Stakeholder offers it as an anonymous participant, and a known name does not. */
export const TypedUnknownNamesBecomeAnonymousParticipants: Story = {
  beforeEach: withResearchExtras,
  render: () => <Harness load={loadTwo} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Participants" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add to Participants" }));
    const search = await within(document.body).findByRole("searchbox");
    await userEvent.type(search, "Sam Client");
    await expect(within(document.body).queryByRole("button", { name: /as an anonymous participant/ })).not.toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "Participant 3{Enter}");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(canvas.getByLabelText("Persona represented by Participant 3")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Persona represented by Participant 3"), "persona-1");
    await expect(canvas.getByLabelText("Persona represented by Participant 3")).toHaveValue("persona-1");
    await userEvent.click(canvas.getByRole("button", { name: "Remove Participant 3" }));
    await expect(canvas.queryByLabelText("Persona represented by Participant 3")).not.toBeInTheDocument();
  },
};

/** With the Research extras on, a project with no Stakeholders still offers the field, for anonymous participants. */
export const AnEmptyProjectStillTakesAnonymousParticipants: Story = {
  beforeEach: withResearchExtras,
  render: () => <Harness load={loadNone} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Add to Participants" }));
    await expect(canvas.queryByText(/No Stakeholders exist in this project yet\./)).not.toBeInTheDocument();
  },
};
