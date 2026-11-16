import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { mockArchitectureReads, ORG_ID, PROJECT_ID, SYMBOLS } from "./architectureFixtures";
import { SymbolPicker } from "./SymbolPicker";
import type { ArchitectureSymbol } from "./types";

const VIEW_KEY = "architecture.symbolPickerView";

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
    window.localStorage.removeItem(VIEW_KEY);
    const reads = mockArchitectureReads({ canManageTypes: false });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
};
export default meta;

type Story = StoryObj<typeof SymbolPicker>;

const body = () => within(document.body);

/** The list view is the default; a person who may not upload sees no upload control at all (not a disabled one). */
export const ListViewWithoutUpload: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Symbol"), "sym-2");
    await expect(args.onChange).toHaveBeenCalledWith("sym-2");
    await expect(await canvas.findByAltText("Preview of Vendor router")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/capabilities`));
    await expect(canvas.queryByText("Upload a symbol")).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
  },
};

/** A person who may change the library uploads from the picker: the symbol is chosen and the caller is told to reload. */
export const UploadChoosesTheNewSymbol: Story = {
  args: { onSymbolsChanged: fn() },
  beforeEach: () => {
    const reads = mockArchitectureReads({ canManageTypes: true });
    const stored: ArchitectureSymbol = { id: "sym-new", project_id: PROJECT_ID, organization_id: null, name: "Gateway", builtin_key: null, is_builtin: false, sort_order: 2 };
    const post = spyOn(api, "postFile").mockResolvedValue(stored);
    return () => { reads.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = await waitFor(() => {
      const found = canvasElement.querySelector("input[type=file]");
      if (!found) throw new Error("no upload control yet");
      return found as HTMLInputElement;
    });
    await userEvent.upload(input, new File(["<svg/>"], "gateway.svg", { type: "image/svg+xml" }));
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/symbols`, expect.any(File), undefined);
    await waitFor(() => expect(args.onChange).toHaveBeenCalledWith("sym-new"));
    await expect(args.onSymbolsChanged).toHaveBeenCalled();
    await expect(canvas.getByLabelText("Symbol")).toHaveValue("sym-new");
  },
};

/** A refused file shows the server's reason under the field and leaves the choice as it was. */
export const UploadRefusalLeavesTheChoice: Story = {
  args: { value: "sym-1" },
  beforeEach: () => {
    const reads = mockArchitectureReads({ canManageTypes: true });
    const post = spyOn(api, "postFile").mockRejectedValue(new Error("The file contains a script and cannot be used."));
    return () => { reads.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const input = await waitFor(() => {
      const found = canvasElement.querySelector("input[type=file]");
      if (!found) throw new Error("no upload control yet");
      return found as HTMLInputElement;
    });
    await userEvent.upload(input, new File(["<svg/>"], "bad.svg", { type: "image/svg+xml" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The file contains a script and cannot be used.");
    await expect(args.onChange).not.toHaveBeenCalled();
    await expect(canvas.getByLabelText("Symbol")).toHaveValue("sym-1");
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
    const input = await waitFor(() => {
      const found = canvasElement.querySelector("input[type=file]");
      if (!found) throw new Error("no upload control yet");
      return found as HTMLInputElement;
    });
    await userEvent.upload(input, new File(["<svg/>"], "switch.svg", { type: "image/svg+xml" }));
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols`, expect.any(File), undefined);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/capabilities`));
  },
};

/** The Gallery shows each symbol's drawing and a None tile; choosing a tile closes it and the choice is remembered as the view. */
export const GalleryChoosesATile: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Gallery" }));
    await expect(window.localStorage.getItem(VIEW_KEY)).toBe("gallery");
    await userEvent.click(canvas.getByRole("button", { name: /Use the type's symbol/ }));
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
    await userEvent.click(within(canvasElement).getByRole("button", { name: /Server/ }));
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
    const trigger = within(canvasElement).getByRole("button", { name: /Use the type's symbol/ });
    await userEvent.click(trigger);
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

    await userEvent.click(within(canvasElement).getByRole("button", { name: /Server/ }));
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
    await userEvent.click(within(canvasElement).getByRole("button", { name: /Use the type's symbol/ }));
    const filter = await body().findByLabelText("Filter symbols");
    await userEvent.type(filter, "vend");
    await expect(body().getAllByRole("radio").map((t) => t.getAttribute("aria-label"))).toEqual(["Use the type's symbol", "Vendor router"]);
    await userEvent.clear(filter);
    await userEvent.type(filter, "zzz");
    await expect(body().getAllByRole("radio")).toHaveLength(1);
    await expect(body().getByText("No symbols match.")).toBeInTheDocument();
  },
};

/** An empty library shows the empty state (and, for a person who may upload, the upload control). */
export const GalleryWithAnEmptyLibrary: Story = {
  args: { symbols: [] },
  beforeEach: () => {
    window.localStorage.setItem(VIEW_KEY, "gallery");
    const reads = mockArchitectureReads({ canManageTypes: true });
    return () => { reads.mockRestore(); window.localStorage.removeItem(VIEW_KEY); };
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /Use the type's symbol/ }));
    await expect(await body().findByText("The symbol library is empty.")).toBeInTheDocument();
    await expect(await body().findByText("Upload a symbol")).toBeInTheDocument();
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
    await userEvent.click(within(canvasElement).getByRole("button", { name: /Use the type's symbol/ }));
    await body().findByRole("radiogroup", { name: "Symbols" });
    await expect(body().getAllByRole("radio")).toHaveLength(201);
    await waitFor(() => expect((api.getForBlob as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThan(0));
    await expect((api.getForBlob as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeLessThan(60);
  },
};
