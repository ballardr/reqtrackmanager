import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ReportFont, ReportFontsPage } from "../api/types";
import { buildUser, withAuth, withToast } from "../testing/storybook-helpers";
import { ServerReportFontsTab } from "./ServerReportFontsTab";

const BUNDLED: ReportFont[] = [
  ["sans", "Sans", "Arial", "sans-serif"],
  ["serif", "Serif", "Times New Roman", "serif"],
  ["mono", "Mono", "Courier New", "monospace"],
  ["unicode", "Unicode Sans", "DejaVu Sans", "sans-serif"],
].map(([key, label, word_name, generic]) => ({
  key, label, word_name, generic: generic as ReportFont["generic"], bundled: true, enabled: true, missing: false, faces: [],
}));

function page(overrides: Partial<ReportFont> = {}, extra = true): ReportFontsPage {
  return {
    directory_configured: true,
    max_file_mb: 10,
    families: [
      ...BUNDLED,
      ...(extra
        ? [{
            key: "x-fira-sans", label: "Fira Sans", word_name: "Fira Sans", generic: "sans-serif" as const, bundled: false,
            enabled: true, missing: false,
            faces: [{ style: "regular" as const, permission: "Installable" }, { style: "bold" as const, permission: "Editable" }],
            ...overrides,
          }]
        : []),
    ],
    skipped: [{ file_name: "locked.ttf", reason: "its licence forbids embedding or subsetting (OS/2 fsType), so it cannot be drawn or embedded" }],
  };
}

function mockApis(initial: ReportFontsPage = page()) {
  spyOn(api, "get").mockResolvedValue(initial);
  const put = spyOn(api, "put").mockImplementation(async (_path: string, body?: unknown) => {
    const change = body as { word_name: string; generic: ReportFont["generic"]; enabled: boolean };
    return page({ ...change, word_name: change.word_name || "Fira Sans" });
  });
  const post = spyOn(api, "post").mockResolvedValue(page());
  return { put, post };
}

const meta: Meta<typeof ServerReportFontsTab> = {
  title: "Pages/ServerReportFontsTab",
  component: ServerReportFontsTab,
  decorators: [withAuth(buildUser({ is_server_admin: true })), withToast()],
};
export default meta;

type Story = StoryObj<typeof ServerReportFontsTab>;

/** Bundled fonts have no controls; a provided font lists its real faces and the licence permission of each. */
export const ListsBundledAndProvidedFonts: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Fira Sans")).toBeInTheDocument());
    await expect(canvas.getByText("Unicode Sans")).toBeInTheDocument();
    await expect(canvas.getByText(/Faces: Regular \(Installable\), Bold \(Editable\)/)).toBeInTheDocument();
    await expect(canvas.queryByRole("switch", { name: "Offered to authors: Sans" })).toBeNull();
    await expect(canvas.getByText("locked.ttf")).toBeInTheDocument();
    await expect(canvas.getByText(/forbids embedding or subsetting/)).toBeInTheDocument();
  },
};

/** Hiding a family from authors saves at once and ends in a toast. */
export const HideAFamily: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Offered to authors: Fira Sans" })).toBeChecked());
    await userEvent.click(canvas.getByRole("switch", { name: "Offered to authors: Fira Sans" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/report-fonts/x-fira-sans", {
      word_name: "Fira Sans", generic: "sans-serif", enabled: false,
    }));
    await waitFor(() => expect(within(document.body).getByText("Fira Sans saved.")).toBeInTheDocument());
    await expect(canvas.getByRole("switch", { name: "Offered to authors: Fira Sans" })).not.toBeChecked();
  },
};

/** The gear holds the Word name and generic fallback; the name has its own Save, and the fallback saves at once. */
export const ChangeTheWordNameAndFallback: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Settings: Fira Sans" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Settings: Fira Sans" }));
    const popover = within(document.body);
    const name = popover.getByRole("textbox", { name: "Name in Word and OpenDocument" });
    await expect(popover.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(name);
    await userEvent.type(name, "Fira Sans Book");
    // Leaving the field saves nothing; the Save button does.
    await userEvent.tab();
    await expect(api.put).not.toHaveBeenCalled();
    await userEvent.click(popover.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/report-fonts/x-fira-sans", {
      word_name: "Fira Sans Book", generic: "sans-serif", enabled: true,
    }));
    await userEvent.selectOptions(popover.getByRole("combobox", { name: "Generic fallback" }), "monospace");
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith("/api/v1/system/report-fonts/x-fira-sans", {
      word_name: "Fira Sans Book", generic: "monospace", enabled: true,
    }));
  },
};

/** Rescan reports how many provided families it found. */
export const Rescan: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Rescan" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Rescan" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/report-fonts/rescan", {}));
    await waitFor(() => expect(within(document.body).getByText("Rescanned: 1 provided family found.")).toBeInTheDocument());
  },
};

/** With no directory set up, the page says so and offers the bundled fonts only. */
export const NoDirectory: Story = {
  beforeEach: () => {
    mockApis({ ...page({}, false), directory_configured: false, skipped: [] });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/No font directory is set up/)).toBeInTheDocument());
    await expect(canvas.getByText("Mono")).toBeInTheDocument();
  },
};

/** A family whose files have gone from the directory is marked as missing. */
export const MissingFiles: Story = {
  beforeEach: () => {
    mockApis(page({ missing: true, faces: [] }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Files missing/)).toBeInTheDocument());
  },
};
