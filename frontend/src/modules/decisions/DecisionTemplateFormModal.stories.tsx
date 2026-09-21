import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DecisionTemplateFormModal } from "./DecisionTemplateFormModal";

const meta: Meta<typeof DecisionTemplateFormModal> = {
  title: "Modules/Decisions/DecisionTemplateFormModal",
  component: DecisionTemplateFormModal,
};
export default meta;

type Story = StoryObj<typeof DecisionTemplateFormModal>;

export const CreateNew: Story = {
  args: { onCancel: fn(), onSave: fn() },
  play: async ({ args }) => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "New decision template" })).toBeInTheDocument();
    await userEvent.type(body.getByLabelText("Template name"), "Nygard (Classic ADR)");
    await userEvent.type(body.getByLabelText("Context — prompt/guidance"), "What is the issue we're facing?");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Nygard (Classic ADR)", context_prompt: "What is the issue we're facing?" })
    ));
  },
};

export const EditExisting: Story = {
  args: {
    initial: {
      name: "MADR",
      description: "Markdown Architectural Decision Records.",
      context_prompt: "What is the issue?",
      options_considered_prompt: null,
      chosen_option_prompt: null,
      rationale_prompt: null,
      consequences_prompt: null,
      assumptions_prompt: null,
      constraints_prompt: null,
    },
    onCancel: fn(),
    onSave: fn(),
  },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit decision template" })).toBeInTheDocument();
    await expect(body.getByDisplayValue("MADR")).toBeInTheDocument();
  },
};

export const ShowsSaveError: Story = {
  args: { error: "A Decision Template with this name already exists.", onCancel: fn(), onSave: fn() },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByText("A Decision Template with this name already exists.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...CreateNew };
export const DarkTheme: Story = { ...CreateNew, globals: { theme: "dark" } };
