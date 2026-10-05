import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildPersona } from "./fixtures";
import { PersonaFormModal } from "./PersonaFormModal";

const TYPE_OPTIONS = [
  { value: "type-primary", label: "Primary" },
  { value: "type-secondary", label: "Secondary" },
];

const meta: Meta<typeof PersonaFormModal> = {
  title: "Modules/Stakeholders/PersonaFormModal",
  component: PersonaFormModal,
  args: { scopeLabel: "project", typeOptions: TYPE_OPTIONS, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof PersonaFormModal>;

// The modal portals to `document.body`.
const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsAName: Story = {
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "New Persona (project)" })).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeEnabled();
    await expect(dialog().queryByLabelText("Change note")).not.toBeInTheDocument();
  },
};

export const SavesEnteredValues: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await userEvent.type(dialog().getByLabelText("Goals"), "Zero incidents");
    await userEvent.selectOptions(dialog().getByLabelText("Type"), "type-secondary");
    await userEvent.type(dialog().getByLabelText("Importance weight"), "3.5");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Safety Officer", goals: "Zero incidents", persona_type_id: "type-secondary", weight: 3.5 }),
    );
  },
};

export const BlankWeightMeansNoWeight: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ weight: null, persona_type_id: null }));
  },
};

export const NonPositiveWeightBlocksSave: Story = {
  play: async () => {
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await userEvent.type(dialog().getByLabelText("Importance weight"), "0");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await expect(dialog().getByLabelText("Importance weight")).toHaveAttribute("aria-invalid", "true");
  },
};

export const EditPrefillsAndShowsChangeNote: Story = {
  args: { initial: buildPersona() },
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "Edit Field Technician" })).toBeInTheDocument();
    await expect(dialog().getByLabelText("Persona name")).toHaveValue("Field Technician");
    await expect(dialog().getByLabelText("Importance weight")).toHaveValue(2);
    await expect(dialog().getByLabelText("Change note")).toBeInTheDocument();
  },
};

export const EditKeepsDisabledCurrentTypeSelectable: Story = {
  args: { initial: buildPersona({ persona_type_id: "type-gone", persona_type_name: "Retired type" }) },
  play: async () => {
    await expect(dialog().getByRole("option", { name: "Retired type (disabled)" })).toBeInTheDocument();
  },
};

export const ShowsError: Story = {
  args: { error: "Could not create Persona." },
  play: async () => {
    await expect(dialog().getByText("Could not create Persona.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...CreateNeedsAName, globals: { theme: "dark" } };
