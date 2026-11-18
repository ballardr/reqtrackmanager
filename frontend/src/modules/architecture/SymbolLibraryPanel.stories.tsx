import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { mockArchitectureReads, ORG_ID, PROJECT_ID } from "./architectureFixtures";
import { SymbolLibraryPanel } from "./SymbolLibraryPanel";

const meta: Meta<typeof SymbolLibraryPanel> = {
  title: "Modules/Architecture/SymbolLibraryPanel",
  component: SymbolLibraryPanel,
  decorators: [withToast()],
  beforeEach: () => {
    const get = mockArchitectureReads();
    return () => get.mockRestore();
  },
};
export default meta;

type Story = StoryObj<typeof SymbolLibraryPanel>;

/** Built-in and organisation symbols cannot be renamed in a project; the project's own can. */
export const ProjectListsSymbolsWithTheirDrawing: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByLabelText("Symbol name", { selector: "input:not([placeholder])" })).toHaveLength(2));
    const names = canvas.getAllByLabelText("Symbol name", { selector: "input:not([placeholder])" }) as HTMLInputElement[];
    await expect(names.map((n) => [n.value, n.disabled])).toEqual([["Server", true], ["Vendor router", false]]);
    await expect(canvas.getByText("Built-in")).toBeInTheDocument();
    await expect(await canvas.findByAltText("Drawing of Server")).toBeInTheDocument();
  },
};

/** An upload goes to the server's sanitiser; a refusal is shown in the panel. */
export const UploadRefusalIsShown: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID } },
  beforeEach: () => {
    const post = spyOn(api, "postFile").mockRejectedValue(new Error("The file contains a script and cannot be used."));
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = (await canvas.findByText("Choose a file")).closest("label")?.querySelector("input[type=file]")
      ?? canvasElement.querySelector("input[type=file]");
    await userEvent.upload(input as HTMLInputElement, new File(["<svg/>"], "bad.svg", { type: "image/svg+xml" }));
    await expect(await canvas.findByRole("alert")).toHaveTextContent("The file contains a script and cannot be used.");
    await expect(api.postFile).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/architecture/symbols`, expect.any(File), undefined);
  },
};
