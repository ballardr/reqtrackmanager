import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildThirdPartyNotices, mockLicenceFetch, MIT_TEXT, OFL_TEXT } from "../testing/licenceFixtures";
import { LicencesSection } from "./LicencesPanel";

/** The sections of the Licences group on the Policies page: product licence, third-party components and fonts. */
const meta: Meta<typeof LicencesSection> = { title: "Components/LicencesPanel", component: LicencesSection };
export default meta;

type Story = StoryObj<typeof LicencesSection>;

/** The product licence needs no data: it names the licence and links to its text and the source code. */
export const Product: Story = {
  args: { section: "product" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { name: "Product licence" })).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Source code" })).toHaveAttribute("target", "_blank");
  },
};

/** The components section lists programs, base images and libraries, and the note about optional services. */
export const Components: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("table", { name: "Libraries" })).toBeInTheDocument();
    await expect(canvas.getByText("3 libraries and 1 programs are included in the published images.")).toBeInTheDocument();
    await expect(within(canvas.getByRole("table", { name: "Programs in the images" })).getByText("Ghostscript")).toBeInTheDocument();
    await expect(within(canvas.getByRole("table", { name: "Base images" })).getByText("python:3.15-slim")).toBeInTheDocument();
    await expect(canvas.getByText(/optional services/)).toBeInTheDocument();
  },
};

/** The search narrows the library table by name or licence and says so when nothing matches. */
export const SearchNarrowsTheLibraries: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Libraries" });
    await expect(within(table).getAllByRole("row")).toHaveLength(4);
    await userEvent.type(canvas.getByRole("textbox", { name: "Search libraries" }), "lgpl");
    await waitFor(() => expect(within(canvas.getByRole("table", { name: "Libraries" })).getAllByRole("row")).toHaveLength(2));
    await expect(within(canvas.getByRole("table", { name: "Libraries" })).getByText("svglib")).toBeInTheDocument();
    await userEvent.clear(canvas.getByRole("textbox", { name: "Search libraries" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Search libraries" }), "no such package");
    await expect(await canvas.findByText("No library matches the search.")).toBeInTheDocument();
  },
};

/** A header click sorts the libraries by that column. */
export const SortByLicence: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Libraries" });
    await userEvent.click(within(table).getByRole("button", { name: /Licence/ }));
    await expect(within(canvas.getByRole("table", { name: "Libraries" })).getAllByRole("row")[1]).toHaveTextContent("svglib");
    await userEvent.click(within(canvas.getByRole("table", { name: "Libraries" })).getByRole("button", { name: /Licence/ }));
    await expect(within(canvas.getByRole("table", { name: "Libraries" })).getAllByRole("row")[1]).toHaveTextContent("react");
  },
};

/** Opening a library shows its licence and where it is used; the licence text is read only when opened. */
export const LibraryDetailLoadsTheTextOnDemand: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Libraries" });
    await expect(window.fetch).not.toHaveBeenCalledWith(expect.stringMatching(/third-party-texts/), expect.anything());
    await userEvent.click(within(table).getByRole("button", { name: "react" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "react 19.2.0: licence" });
    await expect(within(dialog).getByText("Front-end application (bundled)")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Licence text" }));
    await expect(await within(dialog).findByText(/Permission is hereby granted/)).toBeInTheDocument();
    await expect(dialog).toHaveTextContent(MIT_TEXT.split("\n")[0]);
  },
};

/** A library under library copyleft shows why it is allowed, and one with no bundled text says so. */
export const CopyleftLibraryShowsItsReason: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Libraries" });
    await userEvent.click(within(table).getByRole("button", { name: "svglib" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "svglib 1.6.0: licence" });
    await expect(within(dialog).getByText("Used unmodified and replaceable by the operator.")).toBeInTheDocument();
    await expect(within(dialog).getByText(/No licence file is bundled/)).toBeInTheDocument();
  },
};

/** A program shows why it is allowed in the product and links to its source. */
export const ProgramDetail: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Programs in the images" });
    await userEvent.click(within(table).getByRole("button", { name: "Ghostscript" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Ghostscript: licence" });
    await expect(within(dialog).getByText("Separate program, not linked into the product")).toBeInTheDocument();
    await expect(within(dialog).getByRole("link", { name: "https://ghostscript.com/releases/" })).toHaveAttribute("rel", "noopener noreferrer");
  },
};

/** A source address that is not http or https is plain text, never a link. */
export const UnsafeSourceIsNotALink: Story = {
  args: { section: "components" },
  beforeEach: () => {
    const notices = buildThirdPartyNotices();
    notices.system_components[0].source = "javascript:alert(1)";
    mockLicenceFetch(notices);
  },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Programs in the images" });
    await userEvent.click(within(table).getByRole("button", { name: "Ghostscript" }));
    const dialog = await within(document.body).findByRole("dialog", { name: "Ghostscript: licence" });
    await expect(within(dialog).getByText("javascript:alert(1)")).toBeInTheDocument();
    await expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
  },
};

/** Each font shows its licence, where it is used and its licence text on request. */
export const Fonts: Story = {
  args: { section: "fonts" },
  beforeEach: () => mockLicenceFetch(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const liberation = await canvas.findByRole("article", { name: "Liberation Sans" });
    await expect(within(liberation).getByText("backend: report fonts")).toBeInTheDocument();
    await userEvent.click(within(liberation).getByRole("button", { name: "Licence text" }));
    await expect(await within(liberation).findByText(/SIL OPEN FONT LICENSE/)).toBeInTheDocument();
    await expect(liberation).toHaveTextContent(OFL_TEXT.split("\n")[0]);
    await expect(within(canvas.getByRole("article", { name: "KaTeX fonts" })).getByText(/No licence file is bundled/)).toBeInTheDocument();
  },
};

/** A failed read of the inventory says so instead of showing an empty table. */
export const LoadFailure: Story = {
  args: { section: "components" },
  beforeEach: () => mockLicenceFetch(null),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("Could not load the licence information.");
  },
};
