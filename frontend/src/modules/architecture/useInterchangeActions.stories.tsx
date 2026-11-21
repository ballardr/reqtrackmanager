import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ActionMenu } from "../../components/ActionMenu";
import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { PROJECT_ID } from "./architectureFixtures";
import { useInterchangeActions } from "./useInterchangeActions";

/** The hook's rows in an actions menu, as the Elements page draws them. */
function Host({ onImported }: { onImported: () => void }) {
  const { menuItems, dialog } = useInterchangeActions(PROJECT_ID, onImported);
  return <><ActionMenu triggerLabel="List actions" items={menuItems} />{dialog}</>;
}

const meta: Meta<typeof Host> = {
  title: "Modules/Architecture/InterchangeActions",
  component: Host,
  args: { onImported: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof Host>;

const body = () => within(document.body);

/** Opens the menu; the one parent row starts open, so its three rows are listed at once. */
async function openInterchange(canvasElement: HTMLElement) {
  await userEvent.click(within(canvasElement).getByRole("button", { name: "List actions" }));
  await expect(await body().findByRole("menuitem", { name: "Interchange" })).toBeInTheDocument();
}

/** One parent row opens to the two exports and the import. */
export const OffersTwoExportsAndAnImport: Story = {
  play: async ({ canvasElement }) => {
    await openInterchange(canvasElement);
    for (const name of ["Export JSON file", "Export Structurizr DSL", "Import JSON file…"]) {
      await expect(await body().findByRole("menuitem", { name })).toBeInTheDocument();
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
    await openInterchange(canvasElement);
    await userEvent.click(await body().findByRole("menuitem", { name: "Export JSON file" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/\/interchange\/json$/)));
    await openInterchange(canvasElement);
    await userEvent.click(await body().findByRole("menuitem", { name: "Export Structurizr DSL" }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/\/interchange\/structurizr$/)));
    await expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
  },
};

/** Import opens the dialog. */
export const ImportOpensTheDialog: Story = {
  play: async ({ canvasElement }) => {
    await openInterchange(canvasElement);
    await userEvent.click(await body().findByRole("menuitem", { name: "Import JSON file…" }));
    await expect(await body().findByRole("dialog", { name: "Import JSON file" })).toBeInTheDocument();
  },
};
