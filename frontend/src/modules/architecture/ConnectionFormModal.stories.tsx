import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildConnection, buildElement, CONNECTION_TYPES, DOMAINS, ELEMENT_TYPES, PROJECT_ID } from "./architectureFixtures";
import { ConnectionFormModal } from "./ConnectionFormModal";

const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
  buildElement({ id: "el-9", project_id: "project-2", shared: true, unique_code: "ELM-009", name: "Identity", ports: [] }),
  buildElement({ id: "el-8", unique_code: "ELM-008", name: "Old bus", status: "retired", ports: [] }),
];

const meta: Meta<typeof ConnectionFormModal> = {
  title: "Modules/Architecture/ConnectionFormModal",
  component: ConnectionFormModal,
  args: { connectionTypes: CONNECTION_TYPES, elementTypes: ELEMENT_TYPES, domains: DOMAINS, elements: ELEMENTS, projectId: PROJECT_ID, onCancel: fn(), onSave: fn() },
  beforeEach: () => { spyOn(api, "get").mockResolvedValue({ members: [], external: null } as never); },
};
export default meta;

type Story = StoryObj<typeof ConnectionFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsTypeAndTwoDifferentElements: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Connection type", "Source element", "Target element"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-1");
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-2");
    await userEvent.selectOptions(d.getByLabelText("Source port"), "port-1");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ connection_type_id: "ct-1", source_element_id: "el-1", source_port_id: "port-1", target_element_id: "el-2" }),
      { activate: false, quickLinks: [], tags: [] },
    );
  },
};

/** Retired elements are not offered, shared ones are marked, and changing an end clears its port (and hides the choice when the new end has none). */
export const PickerHidesRetiredMarksSharedAndClearsThePort: Story = {
  play: async () => {
    const d = dialog();
    const source = d.getByLabelText("Source element");
    await expect(within(source).queryByText(/Old bus/)).not.toBeInTheDocument();
    await expect(within(source).getByText(/Identity \(shared\)/)).toBeInTheDocument();
    await userEvent.selectOptions(source, "el-1");
    await userEvent.selectOptions(d.getByLabelText("Source port"), "port-1");
    await userEvent.selectOptions(source, "el-2");
    await expect(d.queryByLabelText("Source port")).not.toBeInTheDocument();
  },
};

/** A port choice is offered only for an end that has ports. */
export const PortChoicesAppearOnlyForElementsWithPorts: Story = {
  play: async () => {
    const d = dialog();
    await expect(d.queryByLabelText("Source port")).not.toBeInTheDocument();
    await expect(d.queryByLabelText("Target port")).not.toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-2");
    await expect(d.getByLabelText("Source port")).toBeInTheDocument();
    await expect(d.queryByLabelText("Target port")).not.toBeInTheDocument();
  },
};

export const EditHasNoActivateButton: Story = {
  args: { initial: buildConnection() },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Protocol")).toHaveValue("HTTPS/1.1");
    await expect(d.queryByRole("button", { name: "Save and activate" })).not.toBeInTheDocument();
  },
};

/** The type is chosen from the tree (a group is a usable type) and can be found by searching; I2C is hardware, so the
 * two services hide it until "Show all types" is on. */
export const TypeIsChosenFromTheTreeAndSearched: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-2");
    await userEvent.click(d.getByRole("switch", { name: "Show all types" }));
    await userEvent.click(d.getByRole("button", { name: "Connection type" }));
    const popover = within(document.body);
    await userEvent.type(popover.getByRole("searchbox", { name: "Search Connection type" }), "i2c");
    await userEvent.click(popover.getByRole("radio", { name: "I2C" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ connection_type_id: "ct-2" }), expect.anything());
  },
};

/** Two boards: the hardware types are offered, the software-only one is hidden, and the type the boards suggest comes first. */
export const HardwareEndsOfferHardwareTypesWithSuggestionsFirst: Story = {
  args: {
    elements: [
      buildElement({ id: "b-1", unique_code: "ELM-011", name: "Board A", element_type_id: "et-2", ports: [] }),
      buildElement({ id: "b-2", unique_code: "ELM-012", name: "Board B", element_type_id: "et-2", ports: [] }),
    ],
  },
  play: async () => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await expect(d.getByText("1 hidden")).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Connection type" }));
    const popover = within(document.body);
    await expect(popover.queryByRole("radio", { name: "REST API" })).not.toBeInTheDocument();
    const radios = popover.getAllByRole("radio").map((r) => r.getAttribute("aria-label"));
    await expect(radios.slice(0, 2)).toEqual(["Suggested", "I2C"]); // the group, then the suggestion
    await expect(radios).toContain("Serial bus");
  },
};

/** "Show all types" offers the hidden type; choosing it saves, with a warning that it does not fit. */
export const ChoosingATypeThatDoesNotFitWarnsButSaves: Story = {
  args: {
    elements: [
      buildElement({ id: "b-1", unique_code: "ELM-011", name: "Board A", element_type_id: "et-2", ports: [] }),
      buildElement({ id: "b-2", unique_code: "ELM-012", name: "Board B", element_type_id: "et-2", ports: [] }),
    ],
  },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await userEvent.click(d.getByRole("switch", { name: "Show all types" }));
    await userEvent.click(d.getByRole("button", { name: "Connection type" }));
    await userEvent.click(within(document.body).getAllByRole("radio", { name: "REST API" })[0]);
    await expect(d.getByRole("status")).toHaveTextContent(
      "REST API is in Software, but the source element (Board) is in Hardware and the target element (Board) is in Hardware. The connection can still be saved.",
    );
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ connection_type_id: "ct-1" }), expect.anything());
  },
};

/** A software service and a board: a type suggested for an end counts as a fit and raises no warning. */
export const ASuggestedTypeRaisesNoWarning: Story = {
  args: {
    elements: [
      buildElement({ id: "s-1", unique_code: "ELM-013", name: "Firmware service", element_type_id: "et-1", ports: [] }),
      buildElement({ id: "b-2", unique_code: "ELM-012", name: "Board B", element_type_id: "et-2", ports: [] }),
    ],
  },
  play: async () => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "s-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await userEvent.click(d.getByRole("button", { name: "Connection type" }));
    // REST API (software) does not fit the board by domain, but the service suggests it, so it is listed first.
    await userEvent.click(within(document.body).getAllByRole("radio", { name: "REST API" })[0]);
    await expect(d.queryByRole("status")).not.toBeInTheDocument();
  },
};

/** Editing keeps the connection's own type in the list even when the domain filter would hide it. */
export const EditKeepsAHiddenTypeInTheList: Story = {
  args: {
    initial: buildConnection({ connection_type_id: "ct-1", source_element_id: "b-1", target_element_id: "b-2" }),
    elements: [
      buildElement({ id: "b-1", unique_code: "ELM-011", name: "Board A", element_type_id: "et-2", ports: [] }),
      buildElement({ id: "b-2", unique_code: "ELM-012", name: "Board B", element_type_id: "et-2", ports: [] }),
    ],
  },
  play: async () => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Connection type" })).toHaveTextContent("REST API");
    await expect(d.queryByText("1 hidden")).not.toBeInTheDocument();
  },
};

const BOARDS = [
  buildElement({ id: "b-1", unique_code: "ELM-011", name: "Board A", element_type_id: "et-2", ports: [] }),
  buildElement({ id: "b-2", unique_code: "ELM-012", name: "Board B", element_type_id: "et-2", ports: [] }),
];

/** Chooses `name` in the type picker; "Show all types" is on first so a type that does not fit the ends can be reached. */
async function chooseType(name: string) {
  const d = dialog();
  const showAll = d.queryByRole("switch", { name: "Show all types" });
  if (showAll && showAll.getAttribute("aria-checked") !== "true") await userEvent.click(showAll);
  await userEvent.click(d.getByRole("button", { name: "Connection type" }));
  await userEvent.click(within(document.body).getAllByRole("radio", { name })[0]);
}

/** The type the two boards suggest (I2C) has a default protocol, so a new connection starts with it and saves it. */
export const ANewConnectionStartsWithTheTypesDefaultProtocol: Story = {
  args: { elements: BOARDS },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByLabelText("Protocol")).toHaveValue("");
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await expect(d.getByLabelText("Protocol")).toHaveValue("I2C 400 kHz");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ connection_type_id: "ct-2", protocol: "I2C 400 kHz" }), expect.anything(),
    );
  },
};

/** Changing the type while the protocol is empty or still the previous type's default replaces it with the new default. */
export const ChangingTheTypeReplacesAnEmptyOrDefaultProtocol: Story = {
  args: { elements: BOARDS },
  play: async () => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await expect(d.getByLabelText("Protocol")).toHaveValue("I2C 400 kHz");
    await chooseType("REST API"); // no default: the previous default goes
    await expect(d.getByLabelText("Protocol")).toHaveValue("");
    await chooseType("I2C"); // the protocol was empty: the new default fills it
    await expect(d.getByLabelText("Protocol")).toHaveValue("I2C 400 kHz");
  },
};

/** A protocol the person typed is never overwritten by a type change. */
export const ATypedProtocolSurvivesAChangeOfType: Story = {
  args: { elements: BOARDS },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await userEvent.clear(d.getByLabelText("Protocol"));
    await userEvent.type(d.getByLabelText("Protocol"), "I2C fast mode plus");
    await chooseType("Serial bus");
    await expect(d.getByLabelText("Protocol")).toHaveValue("I2C fast mode plus");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ connection_type_id: "ct-3", protocol: "I2C fast mode plus" }), expect.anything(),
    );
  },
};

/** Emptying the protocol is kept: the form never puts the default back on its own, so a connection can have none. */
export const AnEmptiedProtocolStaysEmpty: Story = {
  args: { elements: BOARDS },
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "b-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "b-2");
    await userEvent.clear(d.getByLabelText("Protocol"));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ protocol: "" }), expect.anything());
  },
};

/** Editing a connection never applies a default: its stored protocol stays until the type changes while it is a default. */
export const EditKeepsTheStoredProtocolWhenTheTypeStaysTheSame: Story = {
  args: { initial: buildConnection({ connection_type_id: "ct-2", protocol: "I2C 100 kHz" }), elements: BOARDS },
  play: async () => {
    await expect(dialog().getByLabelText("Protocol")).toHaveValue("I2C 100 kHz");
    await chooseType("REST API");
    await expect(dialog().getByLabelText("Protocol")).toHaveValue("I2C 100 kHz"); // typed, not the default, so kept
  },
};
