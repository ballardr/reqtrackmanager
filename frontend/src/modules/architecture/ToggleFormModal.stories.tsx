import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { CONNECTION_TYPES, DOMAINS, ELEMENT_TYPES } from "./architectureFixtures";
import { ToggleFormModal } from "./ToggleFormModal";

const meta: Meta<typeof ToggleFormModal> = {
  title: "Modules/Architecture/ToggleFormModal",
  component: ToggleFormModal,
  args: {
    elementTypes: ELEMENT_TYPES, connectionTypes: CONNECTION_TYPES, domains: DOMAINS, elements: [], connections: [],
    onCancel: fn(), onSave: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ToggleFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** The rule's Domains choice lists the project's domains and stores the chosen ones by id. */
export const TheRuleMatchesByTheProjectsDomains: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Hardware only");
    await userEvent.click(d.getByRole("button", { name: /Domains/ }));
    await expect(within(document.body).getByRole("checkbox", { name: "Match domain Software" })).toBeInTheDocument();
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Match domain Hardware" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({
      name: "Hardware only", rule: expect.objectContaining({ domain_ids: ["dm-2"] }),
    }));
  },
};

/** A stored rule shows the domain it names ticked, and unticking it removes it from the rule. */
export const AStoredDomainShowsTickedAndCanBeRemoved: Story = {
  args: {
    initial: {
      id: "tg-1", name: "Software", default_on: true, element_ids: [], connection_ids: [],
      rule: { element_type_ids: [], connection_type_ids: [], domain_ids: ["dm-1"], tags: [] },
    },
  },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.click(d.getByRole("button", { name: /Domains/ }));
    const software = within(document.body).getByRole("checkbox", { name: "Match domain Software" });
    await expect(software).toBeChecked();
    await userEvent.click(software);
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ rule: expect.objectContaining({ domain_ids: [] }) }));
  },
};
