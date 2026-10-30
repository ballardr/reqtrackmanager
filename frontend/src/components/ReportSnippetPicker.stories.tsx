import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import type { ReportSnippet } from "../api/reportLayouts";
import {
  buildBlockCatalogue, buildImageLibrary, buildLayoutApi, buildOutlineTree, buildSnippets, fakeApplySnippet, treeOf,
} from "../testing/reportLayoutFixtures";
import { requiredCaptions } from "../testing/requiredMarkers";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ReportSnippetPicker } from "./ReportSnippetPicker";

const IMAGES = { library: buildImageLibrary(), scope: "project" as const };
const END = { container: "nodes", index: null, label: "Inserting at the end of the layout" };

/**
 * The snippet picker: search and categories on the left, the selected snippet's formats, block outline and parameter form on the
 * right. A snippet for the other layout family is disabled with the reason; a refusal from the server is shown and the dialog stays open.
 */
const meta: Meta<typeof ReportSnippetPicker> = {
  title: "Components/Reports/ReportSnippetPicker",
  component: ReportSnippetPicker,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: {
    api: buildLayoutApi(), family: "document", blockTypes: buildBlockCatalogue().blocks, tree: buildOutlineTree(), images: IMAGES, places: [END],
    onClose: fn(), onInserted: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof ReportSnippetPicker>;

const dialog = async () => within(await screen.findByRole("dialog", { name: "Insert snippet" }));
const choose = async (d: ReturnType<typeof within>, name: string) => userEvent.click(await d.findByRole("button", { name: `Select ${name}` }));

export const ListsTheSnippetsAndFiltersThemBySearchAndCategory: Story = {
  play: async () => {
    const d = await dialog();
    await expect(await d.findByRole("button", { name: "Select Cover page" })).toBeInTheDocument();
    await expect(d.getAllByRole("button", { name: /^Select / })).toHaveLength(4);
    await userEvent.type(d.getByRole("searchbox", { name: "Search snippets" }), "logo");
    await expect(d.getAllByRole("button", { name: /^Select / })).toHaveLength(1);
    await userEvent.clear(d.getByRole("searchbox", { name: "Search snippets" }));
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Category" }), "Records");
    await expect(d.getAllByRole("button", { name: /^Select / }).map((b) => b.getAttribute("aria-label"))).toEqual(["Select Record images"]);
    await userEvent.type(d.getByRole("searchbox", { name: "Search snippets" }), "zzz");
    await expect(d.getByText("No snippet matches.")).toBeInTheDocument();
  },
};

export const ASnippetWithNoParametersInsertsAtTheStatedPlace: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await expect(d.getByRole("button", { name: "Insert" })).toBeDisabled();
    await choose(d, "Cover page");
    await expect(d.getByRole("status")).toHaveTextContent("Inserting at the end of the layout");
    // The formats it is true in, and an outline of its blocks.
    const formats = within(d.getByRole("group", { name: "Output formats" }));
    await expect(formats.getAllByText(/HTML|PDF|Word|OpenDocument/)).toHaveLength(4);
    await expect(d.getByRole("list", { name: "Blocks in Cover page" })).toHaveTextContent("Heading – {{project_name}}");
    await expect(d.getByRole("list", { name: "Blocks in Cover page" })).toHaveTextContent("Page break");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(args.onInserted).toHaveBeenCalledWith(expect.objectContaining({ ok: true, count: 3 }), expect.objectContaining({ key: "cover_page" })));
    await expect(args.api.applySnippet).toHaveBeenCalledWith(
      "cover_page", expect.objectContaining({ parameters: {}, target: { container: "nodes", index: null } }),
    );
  },
};

export const APictureParameterIsRequiredAndChosenFromTheLibrary: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d, "Logo, top right of the first page");
    await expect(requiredCaptions(document.body)).toEqual(["Logo"]);
    await expect(d.getByRole("button", { name: "Insert" })).toBeDisabled();
    await userEvent.click(d.getByRole("button", { name: "Choose image…" }));
    const library = within(await screen.findByRole("dialog", { name: "Image library" }));
    await userEvent.click(await library.findByRole("button", { name: "Select site-logo.png" }));
    await userEvent.click(library.getByRole("button", { name: "Use image" }));
    await waitFor(() => expect(d.getByRole("button", { name: "Insert" })).toBeEnabled());
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(args.api.applySnippet).toHaveBeenCalledWith(
      "cover_logo", expect.objectContaining({ parameters: { logo: "image-1" } }),
    ));
  },
};

export const ARecordTypeIsChosenAndATextWithADefaultIsOptional: Story = {
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d, "Record images");
    await expect(requiredCaptions(document.body)).toEqual(["Record type"]);
    // The caption already has a default, so only the record type blocks Insert.
    await expect(d.getByRole("textbox", { name: "Caption" })).toHaveValue("{{file_name}}");
    await expect(d.getByRole("button", { name: "Insert" })).toBeDisabled();
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Record type" }), "Pain point");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(args.api.applySnippet).toHaveBeenCalledWith(
      "record_images", expect.objectContaining({ parameters: { record_type: "pain_point", caption: "{{file_name}}" } }),
    ));
  },
};

export const ASnippetForTheOtherFamilyIsDisabledWithTheReason: Story = {
  play: async () => {
    const d = await dialog();
    const table = await d.findByRole("button", { name: "Select Landscape table section" });
    await expect(table).toBeDisabled();
    await expect(d.getByText("For table layouts; this is a document layout.")).toBeInTheDocument();
  },
};

export const ARefusalIsShownAndTheDialogStaysOpen: Story = {
  args: {
    onInserted: fn(),
    api: buildLayoutApi([], {
      applySnippet: fn(async () => ({
        ok: false, tree: null, changes: [], inserted_at: null, count: 0, problems_elsewhere: 0,
        errors: [{ path: "parameters.logo", message: "That picture is in a project's library; an organisation layout cannot use it." }],
      })),
    }),
  },
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d, "Cover page");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await expect(await d.findByRole("alert")).toHaveTextContent("an organisation layout cannot use it");
    await expect(args.onInserted).not.toHaveBeenCalled();
    await expect(d.getByRole("button", { name: "Insert" })).toBeEnabled();
  },
};

export const SeveralPlacesAreChosenBetween: Story = {
  args: { places: [END, { container: "nodes", index: 0, label: "Inserting at the start of the layout" }] },
  play: async ({ args }) => {
    const d = await dialog();
    await choose(d, "Cover page");
    await userEvent.selectOptions(d.getByRole("combobox", { name: "Where to insert the snippet" }), "Inserting at the start of the layout");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(args.api.applySnippet).toHaveBeenCalledWith("cover_page", expect.objectContaining({ target: { container: "nodes", index: 0 } })));
  },
};

export const TheLastCategoryIsRemembered: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { report_snippet_category: "Tables" } }))],
  args: { family: "table", tree: treeOf("@layout table\n", "table") },
  play: async () => {
    const d = await dialog();
    await waitFor(() => expect(d.getByRole("combobox", { name: "Category" })).toHaveValue("Tables"));
    await expect(d.getAllByRole("button", { name: /^Select / })).toHaveLength(1);
  },
};

export const NoSnippets: Story = {
  args: { api: buildLayoutApi([], { snippets: fn(async () => []) }) },
  play: async () => {
    await expect(await (await dialog()).findByText("There are no snippets to insert.")).toBeInTheDocument();
  },
};

export const AFailedLoadIsReported: Story = {
  args: { api: buildLayoutApi([], { snippets: fn(async () => { throw new Error("down"); }) }) },
  play: async () => {
    await expect(await (await dialog()).findByRole("alert")).toHaveTextContent("The snippets could not be loaded.");
  },
};

/** Many snippets and a long parameter form scroll inside the dialog body, with Insert pinned in the header. */
const MANY: ReportSnippet[] = Array.from({ length: 30 }, (_, i) => ({
  ...buildSnippets()[0], key: `many-${i}`, name: `Snippet number ${i + 1}`, description: `Does the ${i + 1}th thing, in a sentence long enough to wrap in a narrow list.`,
}));
export const ManySnippetsScrollWithInsertStillReachable: Story = {
  args: { api: buildLayoutApi([], { snippets: fn(async () => MANY), applySnippet: fn(async (key, body) => fakeApplySnippet(MANY, key, body)) }) },
  play: async () => {
    const d = await dialog();
    await expect(await d.findAllByRole("button", { name: /^Select Snippet number/ })).toHaveLength(30);
    await choose(d, "Snippet number 30");
    await expect(d.getByRole("button", { name: "Insert" })).toBeVisible();
  },
};

/** In a narrow dialog the list and the detail stack, and nothing makes the page scroll sideways. */
const narrowDialog: Decorator = (Story) => (
  <>
    <style>{".dialog-card { max-width: 340px !important; }"}</style>
    <Story />
  </>
);
export const ANarrowDialogStacksTheListAndTheDetail: Story = {
  decorators: [narrowDialog],
  play: async () => {
    const d = await dialog();
    await choose(d, "Cover page");
    const list = d.getByRole("list", { name: "Snippets" }).getBoundingClientRect();
    const detail = d.getByRole("region", { name: "Snippet details" }).getBoundingClientRect();
    await expect(detail.top).toBeGreaterThanOrEqual(list.bottom - 1);
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
  },
};

/** A snippet an author saved says where it comes from in the list, and inserts like any other. */
const SAVED: ReportSnippet[] = [
  ...buildSnippets(),
  {
    key: "saved-1", name: "House risk table", description: "Heading and a table of risks.", category: "House style", family: "document",
    formats: ["html", "pdf", "docx", "odt"], module_key: null, saved_id: "snippet-1", origin: "organization", parameters: [],
    blocks: [{ type: "heading", text: "Risks", level: 2 }],
  },
];
export const ASavedSnippetShowsWhereItComesFromAndInsertsLikeAnyOther: Story = {
  args: { api: buildLayoutApi([], { snippets: fn(async () => SAVED), applySnippet: fn(async (key, body) => fakeApplySnippet(SAVED, key, body)) }) },
  play: async ({ args }) => {
    const d = await dialog();
    const saved = await d.findByRole("button", { name: "Select House risk table" });
    await expect(saved).toHaveTextContent("Saved · The organisation");
    await expect(d.getByRole("button", { name: "Select Cover page" })).not.toHaveTextContent("Saved ·");
    await userEvent.click(saved);
    await expect(d.getByRole("list", { name: "Blocks in House risk table" })).toHaveTextContent("Heading – Risks");
    await userEvent.click(d.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(args.onInserted).toHaveBeenCalled());
  },
};
