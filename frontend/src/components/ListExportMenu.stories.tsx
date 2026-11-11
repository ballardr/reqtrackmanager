import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ListExportMenu } from "./ListExportMenu";

const meta: Meta<typeof ListExportMenu> = {
  title: "Components/ListExportMenu",
  component: ListExportMenu,
  args: { label: "Project history", exportFile: fn(async () => new Blob(["x"], { type: "text/csv" })) },
};
export default meta;

type Story = StoryObj<typeof ListExportMenu>;

/** Download shown items lists every format; choosing one asks for that file. */
export const DownloadShownItems: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "List actions" }));
    const body = within(document.body);
    await userEvent.click(await body.findByRole("menuitem", { name: "Download shown items" }));
    const submenu = within(await body.findByRole("menu", { name: "Download shown items" }));
    for (const name of [/CSV/, /PDF/, /Word/, /ODT/, /ODS/]) await expect(submenu.getByRole("menuitem", { name })).toBeInTheDocument();
    await userEvent.click(submenu.getByRole("menuitem", { name: /PDF/ }));
    await waitFor(() => expect(args.exportFile).toHaveBeenCalledWith("pdf"));
  },
};

/** A note (personal data left out) sits under the items. */
export const WithNote: Story = {
  args: { note: "The Person column is left out." },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "List actions" }));
    await expect(await within(document.body).findByText("The Person column is left out.")).toBeInTheDocument();
  },
};
