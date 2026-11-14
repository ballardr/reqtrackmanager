import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { withToast } from "../../testing/storybook-helpers";
import { PROJECT_ID } from "./architectureFixtures";
import { InterchangeImportDialog } from "./InterchangeImportDialog";

const meta: Meta<typeof InterchangeImportDialog> = {
  title: "Modules/Architecture/InterchangeImportDialog",
  component: InterchangeImportDialog,
  args: { projectId: PROJECT_ID, onClose: fn(), onImported: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof InterchangeImportDialog>;

const dialog = () => within(within(document.body).getByRole("dialog"));
const file = (text = '{"format":"reqtrack-architecture","version":"1.0","data":{}}') => new File([text], "architecture.json", { type: "application/json" });

/** The file is the one required field, and Import stays unavailable until a preview has been read. */
export const AsksForAFileAndImportsNothingBeforeAPreview: Story = {
  play: async () => {
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["File"]);
    await expect(dialog().getByRole("button", { name: "Import" })).toBeDisabled();
  },
};

/** Choosing a file previews it: the rows it adds by kind and what it could not resolve; Import then applies it. */
export const PreviewsTheFileThenImportsIt: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue({
      created: { elements: 3, connections: 1, states: 0 },
      warnings: ["Connection CON-002 skipped — one of its elements is not available."],
    } as never);
  },
  play: async ({ args }) => {
    await userEvent.upload(dialog().getByLabelText("File", { exact: false }), file());
    await expect(await dialog().findByText("Elements")).toBeInTheDocument();
    await expect(dialog().getByText("Connections")).toBeInTheDocument();
    await expect(dialog().queryByText("States")).not.toBeInTheDocument();
    await expect(dialog().getByText(/CON-002 skipped/)).toBeInTheDocument();
    await userEvent.click(dialog().getByRole("button", { name: "Import" }));
    await waitFor(() => expect(args.onImported).toHaveBeenCalled());
    await expect(api.post).toHaveBeenLastCalledWith(expect.stringContaining("/interchange/json"), expect.anything());
  },
};

/** A file that is not JSON is refused in the browser, with nothing sent. */
export const RefusesAFileThatIsNotJson: Story = {
  beforeEach: () => { spyOn(api, "post"); },
  play: async () => {
    await userEvent.upload(dialog().getByLabelText("File", { exact: false }), file("not json"));
    await expect(await dialog().findByText("The file is not valid JSON.")).toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
    await expect(dialog().getByRole("button", { name: "Import" })).toBeDisabled();
  },
};

/** The server's refusal (an unsupported version) is shown in the dialog. */
export const ShowsTheServersRefusal: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockRejectedValue(new ApiError(422, "Version 2.0 is not supported; this server reads version 1.x."));
  },
  play: async () => {
    await userEvent.upload(dialog().getByLabelText("File", { exact: false }), file());
    await expect(await dialog().findByText(/Version 2.0 is not supported/)).toBeInTheDocument();
  },
};

/** A file that adds nothing cannot be imported. */
export const AFileThatAddsNothingCannotBeImported: Story = {
  beforeEach: () => { spyOn(api, "post").mockResolvedValue({ created: {}, warnings: [] } as never); },
  play: async () => {
    await userEvent.upload(dialog().getByLabelText("File", { exact: false }), file());
    await expect(await dialog().findByText("The file adds nothing.")).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Import" })).toBeDisabled();
  },
};
