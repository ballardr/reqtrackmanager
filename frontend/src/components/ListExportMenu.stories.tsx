import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ListExportMenu } from "./ListExportMenu";
import { chooseMenuRow, findMenuRow } from "../testing/menuTree";

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
    for (const name of [/CSV/, /PDF/, /Word/, /ODT/, /ODS/]) await expect(await findMenuRow(name)).toBeInTheDocument();
    await chooseMenuRow(/PDF/);
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
