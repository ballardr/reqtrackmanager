import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { SEARCH_FIELDS } from "../testing/searchFixtures";
import { SearchFieldPicker } from "./SearchFieldPicker";

function Harness({ initial }: { initial: string[] }) {
  const [value, setValue] = useState(initial);
  return (
    <div className="stack">
      <SearchFieldPicker label="Fields searched" fields={SEARCH_FIELDS} value={value} onChange={setValue} />
      <output aria-label="selected">{value.join(",")}</output>
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/SearchFieldPicker",
  component: Harness,
  args: { initial: ["id", "title", "tags"] },
};
export default meta;
type Story = StoryObj<typeof Harness>;

/** ID and Title are always searched, so they are checked and cannot be unchecked; the others toggle. */
export const IdAndTitleAreLocked: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Fields searched" }));
    const group = within(document.body).getByRole("group", { name: "Fields searched" });
    await expect(within(group).getByRole("checkbox", { name: "ID" })).toBeChecked();
    await expect(within(group).getByRole("checkbox", { name: "ID" })).toBeDisabled();
    await expect(within(group).getByRole("checkbox", { name: "Title" })).toBeDisabled();
    await userEvent.click(within(group).getByRole("checkbox", { name: "Description" }));
    await expect(canvas.getByLabelText("selected")).toHaveTextContent("id,title,tags,description");
    await userEvent.click(within(group).getByRole("checkbox", { name: "Tags" }));
    await expect(canvas.getByLabelText("selected")).toHaveTextContent("id,title,description");
  },
};

/** A long list gets a filter box; each type-specific field names the few types that carry it. */
export const FilterBoxNarrowsALongList: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Fields searched" }));
    const group = within(document.body).getByRole("group", { name: "Fields searched" });
    await expect(within(group).getByText("(Risk)")).toBeInTheDocument();
    await userEvent.type(within(document.body).getByRole("searchbox", { name: "Filter Fields searched" }), "ration");
    await expect(within(group).getByRole("checkbox", { name: "Rationale" })).toBeInTheDocument();
    await expect(within(group).queryByRole("checkbox", { name: "Mitigation" })).not.toBeInTheDocument();
    await userEvent.clear(within(document.body).getByRole("searchbox", { name: "Filter Fields searched" }));
    await userEvent.type(within(document.body).getByRole("searchbox", { name: "Filter Fields searched" }), "nothing like this");
    await expect(within(group).getByText("Nothing matches.")).toBeInTheDocument();
  },
};

/** A saved key that is no longer offered is named so it can be removed instead of silently failing. */
export const AnUnavailableKeyIsNamedAndRemovable: Story = {
  args: { initial: ["id", "title", "gone_field"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/No longer available: gone_field/)).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove" }));
    await expect(canvas.getByLabelText("selected")).toHaveTextContent("id,title");
    await expect(canvas.queryByText(/No longer available/)).not.toBeInTheDocument();
  },
};

/** A long selection is summarised by count rather than listing every label. */
export const ManySelectedAreSummarisedByCount: Story = {
  args: { initial: ["id", "title", "tags", "description", "reasoning"] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Fields searched" })).toHaveTextContent("5 selected");
  },
};

/** Comments are offered but flagged as slower; they are a per-search choice. */
export const CommentsAreFlaggedAsSlower: Story = {
  render: () => {
    const fields = [...SEARCH_FIELDS, { key: "comments", label: "Comments", types: ["Requirement", "Risk", "Decision", "Persona"], default_allowed: false }];
    return <SearchFieldPicker label="Fields searched" fields={fields} value={["id", "title"]} onChange={() => undefined} />;
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Fields searched" }));
    const group = within(document.body).getByRole("group", { name: "Fields searched" });
    await expect(within(group).getByRole("checkbox", { name: "Comments" })).not.toBeChecked();
    await expect(within(group).getByText("(slower: reads every discussion)")).toBeInTheDocument();
  },
};
