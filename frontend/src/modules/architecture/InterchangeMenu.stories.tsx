import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { PROJECT_ID } from "./architectureFixtures";
import { InterchangeMenu } from "./InterchangeMenu";

const meta: Meta<typeof InterchangeMenu> = {
  title: "Modules/Architecture/InterchangeMenu",
  component: InterchangeMenu,
  args: { projectId: PROJECT_ID, onImported: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof InterchangeMenu>;

const menu = () => within(within(document.body).getByRole("menu", { name: "Interchange" }));

/** The menu offers the two exports and the import. */
export const OffersTwoExportsAndAnImport: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Interchange" }));
    for (const name of ["Export JSON file", "Export Structurizr DSL", "Import JSON file…"]) {
      await expect(menu().getByRole("menuitem", { name })).toBeInTheDocument();
    }
  },
};

/** Each export asks the server for its own file and saves it. */
export const ExportsEachFileFromItsEndpoint: Story = {
  beforeEach: () => {
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["x"]));
    spyOn(URL, "createObjectURL").mockReturnValue("blob:test");
    spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  },
  play: async ({ canvasElement }) => {
    const button = () => within(canvasElement).getByRole("button", { name: "Interchange" });
    await userEvent.click(button());
    await userEvent.click(menu().getByRole("menuitem", { name: "Export JSON file" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/\/interchange\/json$/)));
    await userEvent.click(button());
    await userEvent.click(menu().getByRole("menuitem", { name: "Export Structurizr DSL" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/\/interchange\/structurizr$/)));
    await expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
  },
};

/** Import opens the dialog. */
export const ImportOpensTheDialog: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Interchange" }));
    await userEvent.click(menu().getByRole("menuitem", { name: "Import JSON file…" }));
    await expect(await within(document.body).findByRole("dialog", { name: "Import JSON file" })).toBeInTheDocument();
  },
};
