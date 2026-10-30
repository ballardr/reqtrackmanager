import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import type { FileNameExample, FileNameExampleRequest } from "../api/reportFileNames";
import { FileNameField } from "./FileNameField";

/** A stand-in for the server: fills two placeholders, refuses `{{record.…}}`, and lists what the place allows. */
const PLACEHOLDERS = ["{{report_title}}", "{{project_code}}", "{{generated_on}}", "{{var.team}}"];
async function fakeExample(request: FileNameExampleRequest): Promise<FileNameExample> {
  if (request.template.includes("{{record.")) {
    return { example: null, problems: ["A file has no current record."], placeholders: PLACEHOLDERS };
  }
  const name = request.template.replace("{{report_title}}", "Quarterly review").replace("{{project_code}}", "ACME").replace("{{generated_on}}", "2026-10-29");
  return { example: request.template === "" ? null : `${name}.${request.extension}`, problems: [], placeholders: PLACEHOLDERS };
}

function Host({ initial = "", disabled = false, kind = "layout" as const, onValue }: { initial?: string; disabled?: boolean; kind?: "layout" | "organization"; onValue?: (v: string) => void }) {
  const [value, setValue] = useState(initial);
  return (
    <FileNameField
      label="File name" value={value} kind={kind} variables={["team"]} disabled={disabled} help="What a download is called."
      fetchExample={fakeExample} onChange={(next) => { setValue(next); onValue?.(next); }}
    />
  );
}

/** A file name template with an Insert list of the placeholders valid in that place and a live example from the server. */
const meta: Meta<typeof Host> = { title: "Components/Reports/FileNameField", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const ShowsTheExampleTheServerGives: Story = {
  args: { initial: "{{project_code}}-{{report_title}}" },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("Example: ACME-Quarterly review.pdf")).toBeInTheDocument();
  },
};

export const TypingUpdatesTheExample: Story = {
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText("Example: the default name")).toBeInTheDocument();
    await userEvent.type(view.getByRole("textbox", { name: "File name" }), "{{{{report_title}}-{{{{generated_on}}", { delay: null });
    await expect(await view.findByText("Example: Quarterly review-2026-10-29.pdf")).toBeInTheDocument();
  },
};

/** The Insert list holds what the server says is valid here, and choosing one appends it. */
export const InsertingAPlaceholderAppendsIt: Story = {
  args: { initial: "report-", onValue: fn() },
  play: async ({ canvasElement, args }) => {
    const view = within(canvasElement);
    const insert = await view.findByRole("combobox", { name: "Insert placeholder" });
    await waitFor(() => expect(within(insert).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(insert, "{{var.team}}");
    await waitFor(() => expect(args.onValue).toHaveBeenLastCalledWith("report-{{var.team}}"));
    await expect(view.getByRole("textbox", { name: "File name" })).toHaveValue("report-{{var.team}}");
  },
};

export const AProblemIsShownInPlaceOfTheExample: Story = {
  args: { initial: "{{record.code}}" },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("alert")).toHaveTextContent("A file has no current record.");
  },
};

export const ReadOnlyHasNoInsertList: Story = {
  args: { initial: "{{report_title}}", disabled: true },
  play: async ({ canvasElement }) => {
    const view = within(canvasElement);
    await expect(await view.findByText("Example: Quarterly review.pdf")).toBeInTheDocument();
    await expect(view.queryByRole("combobox", { name: "Insert placeholder" })).toBeNull();
    await expect(view.getByRole("textbox", { name: "File name" })).toBeDisabled();
  },
};
