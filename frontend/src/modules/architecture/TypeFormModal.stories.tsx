import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { CONNECTION_TYPES, DOMAINS, ELEMENT_TYPES, mockArchitectureReads, SYMBOLS } from "./architectureFixtures";
import { TypeFormModal } from "./TypeFormModal";

const meta: Meta<typeof TypeFormModal> = {
  title: "Modules/Architecture/TypeFormModal",
  component: TypeFormModal,
  args: { kind: "element", domains: DOMAINS, symbols: SYMBOLS, symbolUrl: (id) => `/symbols/${id}`, onCancel: fn(), onSave: fn() },
  beforeEach: () => { mockArchitectureReads(); },
};
export default meta;

type Story = StoryObj<typeof TypeFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const ElementTypeNeedsANameAndSavesShapeAndSymbol: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Name"), "Sensor");
    await userEvent.selectOptions(d.getByLabelText("Shape"), "hexagon");
    await userEvent.click(d.getByRole("button", { name: /^Symbol:/ }));
    await userEvent.click(await within(document.body).findByRole("option", { name: "Server" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Sensor", domain_ids: [], shape: "hexagon", color_light: null, color_dark: null, symbol_id: "sym-1",
      suggested_connection_type_ids: [],
    });
  },
};

export const ConnectionTypeSavesLineStyleAndDirection: Story = {
  args: { kind: "connection", initial: CONNECTION_TYPES[1] },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.queryByLabelText("Shape")).not.toBeInTheDocument();
    await expect(d.getByLabelText("Line style")).toHaveValue("dashed");
    await userEvent.selectOptions(d.getByLabelText("Line style"), "dotted");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({
      name: "I2C", domain_ids: ["dm-2"], line_style: "dotted", directional: false, color_light: "#065f46", color_dark: "#6ee7b7",
    }));
  },
};

/** A type is in any number of domains: none chosen fits every domain, and the choice is made from the owner's list. */
export const ATypeIsInSeveralDomainsOrNone: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Domains" })).toHaveTextContent("Any domain");
    await userEvent.type(d.getByLabelText("Name"), "Gateway");
    await userEvent.click(d.getByRole("button", { name: "Domains" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Software" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Hardware" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Gateway", domain_ids: ["dm-1", "dm-2"] }));
  },
};

/** Editing shows the stored domains, and unticking every one puts the type in none again. */
export const EditShowsTheStoredDomainsAndCanClearThem: Story = {
  args: { initial: ELEMENT_TYPES[0] },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Domains" })).toHaveTextContent("Software");
    await userEvent.click(d.getByRole("button", { name: "Domains" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Software" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ domain_ids: [] }));
  },
};

export const EditKeepsTheStoredColours: Story = {
  args: { initial: ELEMENT_TYPES[0] },
  play: async () => {
    await expect(dialog().getByLabelText("Colour (light theme) (hex code)")).toHaveValue("#dbeafe");
  },
};

export const ConnectionTypeChoosesItsParentsFromTheTree: Story = {
  args: { kind: "connection", initial: undefined, connectionTypes: CONNECTION_TYPES },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "SMBus");
    await userEvent.click(d.getByRole("button", { name: "Sits under" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Serial bus" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "SMBus", parent_ids: ["ct-3"] }));
  },
};

/** A type cannot be placed under itself or anything beneath it: those nodes are shown but cannot be chosen. */
export const ParentsOfAGroupExcludeItsOwnBranch: Story = {
  args: { kind: "connection", initial: CONNECTION_TYPES[2], connectionTypes: CONNECTION_TYPES },
  play: async () => {
    const d = dialog();
    await userEvent.click(d.getByRole("button", { name: "Sits under" }));
    await expect(within(document.body).getByRole("checkbox", { name: "Serial bus" })).toBeDisabled();
    await expect(within(document.body).getByRole("checkbox", { name: "I2C" })).toBeDisabled();
    await expect(within(document.body).getByRole("checkbox", { name: "REST API" })).toBeEnabled();
  },
};

/** An element type names the connection types a connection picker lists first; they are chosen from the tree, groups included. */
export const ElementTypeChoosesItsSuggestedConnectionTypes: Story = {
  args: { kind: "element", initial: undefined, connectionTypes: CONNECTION_TYPES },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Sensor");
    await userEvent.click(d.getByRole("button", { name: "Suggested connection types" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "I2C" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Serial bus" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Sensor", suggested_connection_type_ids: ["ct-2", "ct-3"] }));
  },
};

/** Editing shows the stored suggestions and a connection type's dialog has no such field. */
export const EditShowsTheStoredSuggestions: Story = {
  args: { initial: ELEMENT_TYPES[0], connectionTypes: CONNECTION_TYPES },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Suggested connection types" })).toHaveTextContent("REST API");
  },
};

export const ConnectionTypeHasNoSuggestions: Story = {
  args: { kind: "connection", initial: CONNECTION_TYPES[0], connectionTypes: CONNECTION_TYPES },
  play: async () => {
    await expect(dialog().queryByRole("button", { name: "Suggested connection types" })).not.toBeInTheDocument();
  },
};

/** A connection type has a Default protocol (trimmed when saved); an element type has no such field. */
export const ConnectionTypeSavesATrimmedDefaultProtocol: Story = {
  args: { kind: "connection", initial: CONNECTION_TYPES[1] },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByLabelText("Default protocol")).toHaveValue("I2C 400 kHz");
    await userEvent.clear(d.getByLabelText("Default protocol"));
    await userEvent.type(d.getByLabelText("Default protocol"), "  SPI mode 0  ");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "I2C", default_protocol: "SPI mode 0" }));
  },
};

export const ANewConnectionTypeHasNoDefaultProtocolAndAnElementTypeHasNoField: Story = {
  args: { kind: "connection" },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByLabelText("Default protocol")).toHaveValue("");
    await userEvent.type(d.getByLabelText("Name"), "Bus");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ name: "Bus", default_protocol: "" }));
  },
};

export const ElementTypeHasNoDefaultProtocol: Story = {
  play: async () => {
    await expect(dialog().queryByLabelText("Default protocol")).not.toBeInTheDocument();
  },
};
