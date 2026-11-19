import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { isolateSymbolPickerView, mockArchitectureReads, ORG_ID, PROJECT_ID, SYMBOL_PICKER_VIEW_KEY as VIEW_KEY, SYMBOLS } from "./architectureFixtures";
import { SymbolPicker } from "./SymbolPicker";
import type { ArchitectureSymbol } from "./types";

/** A picker with the state a form gives it, so a choice shows. */
function Harness(args: React.ComponentProps<typeof SymbolPicker>) {
  const [value, setValue] = useState<string | null>(args.value);
  return <SymbolPicker {...args} value={value} onChange={(next) => { setValue(next); args.onChange(next); }} />;
}

const meta: Meta<typeof SymbolPicker> = {
  title: "Modules/Architecture/SymbolPicker",
  component: SymbolPicker,
  decorators: [withToast()],
  render: (args) => <Harness {...args} />,
  args: {
    label: "Symbol", help: "Which drawing the element uses.", symbols: SYMBOLS, value: null, onChange: fn(),
    urlFor: (id) => `/symbols/${id}`, emptyLabel: "Use the type's symbol", scope: { kind: "project", projectId: PROJECT_ID },
  },
  beforeEach: () => {
    const restoreStorage = isolateSymbolPickerView();
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); restoreStorage(); };
  },
};
export default meta;

type Story = StoryObj<typeof SymbolPicker>;

const body = () => within(document.body);

/** Opens the picker's panel from its field button (named for the choice it shows). */
async function openPanel(canvasElement: HTMLElement, choice: RegExp | string = /Use the type's symbol/) {
  await userEvent.click(within(canvasElement).getByRole("button", { name: choice }));
}

/** Chooses a view from the buttons below the symbols. */
async function chooseView(name: "List" | "Gallery" | "Upload") {
  const group = await body().findByRole("group", { name: "Symbol view" });
  await userEvent.click(await within(group).findByRole("button", { name }));
}

/** Waits for the upload file input of the panel's Upload view. */
const uploadInput = () => waitFor(() => {
  const found = document.body.querySelector("input[type=file]");
  if (!found) throw new Error("no upload control yet");
  return found as HTMLInputElement;
});

/** The field is one button; the list, the filter and the view buttons are all inside its panel, and a person who may not upload has no Upload button. */
export const TheViewsAreButtonsInsideThePanel: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Nothing but the field's button sits beside the caption.
    await expect(canvas.queryByRole("button", { name: "List" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Gallery" })).not.toBeInTheDocument();
    await expect(canvas.queryByText("Upload a symbol")).not.toBeInTheDocument();
    await openPanel(canvasElement);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/capabilities`));
    const group = await body().findByRole("group", { name: "Symbol view" });
    await expect(within(group).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["List", "Gallery"]);
    await expect(within(group).getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    // The filter has the focus, so typing searches at once.
    await expect(body().getByLabelText("Filter symbols")).toHaveFocus();
  },
};

/** The List view lists the names with None first, filters by name, and choosing a row closes the panel and shows the choice. */
export const ListViewChoosesARow: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openPanel(canvasElement);
    const list = await body().findByRole("listbox", { name: "Symbols" });
    await expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["Use the type's symbol", "Server", "Vendor router"]);
    await expect(within(list).getByRole("option", { name: "Use the type's symbol" })).toHaveAttribute("aria-selected", "true");
    await userEvent.type(body().getByLabelText("Filter symbols"), "vend");
    await expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["Use the type's symbol", "Vendor router"]);
    await userEvent.click(within(list).getByRole("option", { name: "Vendor router" }));
    await expect(args.onChange).toHaveBeenCalledWith("sym-2");
    await waitFor(() => expect(body().queryByRole("listbox")).not.toBeInTheDocument());
    await expect(await canvas.findByAltText("Preview of Vendor router")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Symbol: Vendor router" })).toBeInTheDocument();
  },
};

/** Arrow keys move between rows, Enter chooses, and Escape closes the panel with focus back on the field. */
export const ListKeyboardModel: Story = {
  play: async ({ canvasElement, args }) => {
    await openPanel(canvasElement);
    const list = await body().findByRole("listbox", { name: "Symbols" });
    const [none, server, router] = within(list).getAllByRole("option");
    await expect([none, server, router].map((o) => o.tabIndex)).toEqual([0, -1, -1]);
    none.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(server).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}{ArrowUp}");
    await expect(router).toHaveFocus();
    await userEvent.keyboard("{Home}");
    await expect(none).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    await expect(args.onChange).toHaveBeenCalledWith("sym-1");
    await waitFor(() => expect(body().queryByRole("listbox")).not.toBeInTheDocument());
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: /Server/ })).toHaveFocus());

    await openPanel(canvasElement, /Server/);
    await body().findByRole("listbox", { name: "Symbols" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body().queryByRole("listbox")).not.toBeInTheDocument());
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: /Server/ })).toHaveFocus());
  },
};

/** A person who may change the library uploads from the panel's Upload view: the symbol is chosen and the caller is told to reload. */
export const UploadChoosesTheNewSymbol: Story = {
  args: { onSymbolsChanged: fn() },
  beforeEach: () => {
    const reads = mockArchitectureReads({ canManageTypes: true });
    const stored: ArchitectureSymbol = { id: "sym-new", project_id: PROJECT_ID, organization_id: null, name: "Gateway", builtin_key: null, is_builtin: false, sort_order: 2 };
    const post = spyOn(api, "postFile").mockResolvedValue(stored);
    return () => { reads.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement, args }) => {
    await openPanel(canvasElement);
    await chooseView("Upload");
    // The filter has nothing to filter in the Upload view.
    await expect(body().queryByLabelText("Filter symbols")).not.toBeInTheDocument();
    await userEvent.upload(await uploadInput(), new File(["<svg/>"], "gateway.svg", { type: "image/svg+xml" }));
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/symbols`, expect.any(File), undefined);
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith("sym-new"));
    await expect(args.onSymbolsChanged).toHaveBeenCalled();
    await expect(await within(canvasElement).findByRole("button", { name: "Symbol: Gateway" })).toBeInTheDocument();
    await waitFor(() => expect(body().queryByRole("group", { name: "Symbol view" })).not.toBeInTheDocument());
  },
};

/** A refused file shows the server's reason in the Upload view and leaves the choice as it was. */
export const UploadRefusalLeavesTheChoice: Story = {
  args: { value: "sym-1" },
  beforeEach: () => {
    const reads = mockArchitectureReads({ canManageTypes: true });
    const post = spyOn(api, "postFile").mockRejectedValue(new Error("The file contains a script and cannot be used."));
    return () => { reads.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement, args }) => {
    await openPanel(canvasElement, /Server/);
    await chooseView("Upload");
    await userEvent.upload(await uploadInput(), new File(["<svg/>"], "bad.svg", { type: "image/svg+xml" }));
    await expect(await body().findByRole("alert")).toHaveTextContent("The file contains a script and cannot be used.");
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(within(canvasElement).getByRole("button", { name: "Symbol: Server" })).toBeInTheDocument();
  },
};

/** Upload is not remembered as the view: the panel opens at the remembered List or Gallery again. */
export const UploadIsNotTheRememberedView: Story = {
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: true });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement }) => {
    await openPanel(canvasElement);
    await chooseView("Upload");
    await expect(window.localStorage.getItem(VIEW_KEY)).toBe("gallery");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body().queryByRole("group", { name: "Symbol view" })).not.toBeInTheDocument());
    await openPanel(canvasElement);
    await expect(await body().findByRole("radiogroup", { name: "Symbols" })).toBeInTheDocument();
  },
};

/** An organisation's picker reads the organisation's capabilities and uploads to the organisation's library. */
export const OrganisationPickerUploadsToTheOrganisation: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID } },
  beforeEach: () => {
    const reads = mockArchitectureReads({ canManageTypes: true });
    const post = spyOn(api, "postFile").mockResolvedValue({ ...SYMBOLS[0], id: "sym-org", name: "Switch", builtin_key: null, is_builtin: false });
    return () => { reads.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/capabilities`));
    await openPanel(canvasElement);
    await chooseView("Upload");
    await userEvent.upload(await uploadInput(), new File(["<svg/>"], "switch.svg", { type: "image/svg+xml" }));
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols`, expect.any(File), undefined);
  },
};

/** The Gallery button shows each symbol's drawing and a None tile; choosing a tile closes the panel, and Gallery is remembered as the view. */
export const GalleryChoosesATile: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openPanel(canvasElement);
    await chooseView("Gallery");
    await expect(window.localStorage.getItem(VIEW_KEY)).toBe("gallery");
    const group = await body().findByRole("radiogroup", { name: "Symbols" });
    const tiles = within(group).getAllByRole("radio");
    await expect(tiles.map((t) => t.getAttribute("aria-label"))).toEqual(["Use the type's symbol", "Server", "Vendor router"]);
    await expect(tiles[0]).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(group).getByRole("radio", { name: "Vendor router" }));
    await expect(args.onChange).toHaveBeenCalledWith("sym-2");
    await waitFor(() => expect(body().queryByRole("radiogroup")).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: /Vendor router/ })).toBeInTheDocument();
  },
};

/** The None tile clears the choice; the current choice is marked. */
export const GalleryNoneTileClearsTheChoice: Story = {
  args: { value: "sym-1" },
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement, args }) => {
    await openPanel(canvasElement, /Server/);
    const group = await body().findByRole("radiogroup", { name: "Symbols" });
    await expect(within(group).getByRole("radio", { name: "Server" })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(within(group).getByRole("radio", { name: "Use the type's symbol" }));
    await expect(args.onChange).toHaveBeenCalledWith(null);
  },
};

/** Arrow keys move between tiles, Enter chooses, and Escape closes the grid with focus back on the field. */
export const GalleryKeyboardModel: Story = {
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement, args }) => {
    await openPanel(canvasElement);
    const group = await body().findByRole("radiogroup", { name: "Symbols" });
    const [none, server, router] = within(group).getAllByRole("radio");
    // One tile is in the Tab order (the chosen one: None).
    await expect([none, server, router].map((t) => t.tabIndex)).toEqual([0, -1, -1]);
    none.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(server).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    await expect(none).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(router).toHaveFocus();
    await userEvent.keyboard("{Home}");
    await expect(none).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}{Enter}");
    await expect(args.onChange).toHaveBeenCalledWith("sym-1");
    await waitFor(() => expect(body().queryByRole("radiogroup")).not.toBeInTheDocument());
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: /Server/ })).toHaveFocus());

    await openPanel(canvasElement, /Server/);
    await body().findByRole("radiogroup", { name: "Symbols" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(body().queryByRole("radiogroup")).not.toBeInTheDocument());
    await waitFor(() => expect(within(canvasElement).getByRole("button", { name: /Server/ })).toHaveFocus());
  },
};

/** A filter narrows the tiles by name; with no match the grid says so, and the None tile stays. */
export const GalleryFilterWithNoMatch: Story = {
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement }) => {
    await openPanel(canvasElement);
    const filter = await body().findByLabelText("Filter symbols");
    await userEvent.type(filter, "vend");
    await expect(body().getAllByRole("radio").map((t) => t.getAttribute("aria-label"))).toEqual(["Use the type's symbol", "Vendor router"]);
    await userEvent.clear(filter);
    await userEvent.type(filter, "zzz");
    await expect(body().getAllByRole("radio")).toHaveLength(1);
    await expect(body().getByText("No symbols match.")).toBeInTheDocument();
  },
};

/** An empty library shows the empty state (and, for a person who may upload, the Upload button). */
export const GalleryWithAnEmptyLibrary: Story = {
  args: { symbols: [] },
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: true });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement }) => {
    await openPanel(canvasElement);
    await expect(await body().findByText("The symbol library is empty.")).toBeInTheDocument();
    await expect(await within(await body().findByRole("group", { name: "Symbol view" })).findByRole("button", { name: "Upload" })).toBeInTheDocument();
  },
};

const MANY: ArchitectureSymbol[] = Array.from({ length: 200 }, (_, i) => ({
  id: `many-${i}`, project_id: PROJECT_ID, organization_id: null,
  name: i === 0 ? "A symbol with a very long name that wraps inside its tile and stays readable" : `Symbol ${i}`,
  builtin_key: null, is_builtin: false, sort_order: i,
}));

/** A library of 200 opens without 200 requests: a tile reads its drawing only once it scrolls into view. */
export const GalleryOf200ReadsOnlyTheVisibleDrawings: Story = {
  args: { symbols: MANY },
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement }) => {
    await openPanel(canvasElement);
    await body().findByRole("radiogroup", { name: "Symbols" });
    await expect(body().getAllByRole("radio")).toHaveLength(201);
    await waitFor(() => expect((api.getForBlob as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThan(0));
    await expect((api.getForBlob as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeLessThan(60);
  },
};
