import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildProject, withToast } from "../testing/storybook-helpers";
import { RequirementReportPanel } from "./RequirementReportPanel";

const project = buildProject({ id: "project-1", organization_id: "org-1", name: "Atlas Platform" });

const meta: Meta<typeof RequirementReportPanel> = {
  title: "Components/RequirementReportPanel",
  component: RequirementReportPanel,
  args: { project },
  decorators: [withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
    spyOn(api, "postForBlob").mockResolvedValue(new Blob(["x"]));
    // The browser's download needs no real URL in a story.
    spyOn(URL, "createObjectURL").mockReturnValue("blob:story");
    spyOn(URL, "revokeObjectURL").mockReturnValue(undefined);
  },
};
export default meta;

type Story = StoryObj<typeof RequirementReportPanel>;

/** PDF is the primary button; every other format the report is rendered in is under More formats, named like everywhere else. */
export const MoreFormatsOffersEveryOtherFormat: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "More formats" }));
    const menu = within(await within(document.body).findByRole("dialog", { name: "Export" }));
    for (const name of ["Word", "ODT", "HTML", "CSV", "Excel", "ODS"]) {
      await expect(menu.getByRole("button", { name: `Download ${name} report` })).toBeInTheDocument();
    }
  },
};

/** A document format sends the chapter layout; a table format (CSV, Excel, ODS) sends none, since it has no chapters. */
export const OnlyDocumentFormatsSendTheChapterLayout: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "More formats" });
    await userEvent.selectOptions(canvas.getByRole("combobox"), "true");
    for (const [name, kind, chapters] of [["ODT", "odt", true], ["ODS", "ods", null]] as const) {
      await userEvent.click(canvas.getByRole("button", { name: "More formats" }));
      await userEvent.click(within(await within(document.body).findByRole("dialog", { name: "Export" })).getByRole("button", { name: `Download ${name} report` }));
      await waitFor(() =>
        expect(api.postForBlob).toHaveBeenCalledWith("/api/v1/projects/project-1/reports", {
          format: kind, resource_file_ids: [], chapters_per_component: chapters,
        }),
      );
    }
  },
};
