import type { Meta, StoryObj } from "@storybook/react-vite";
import { useId, useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { tabPanelProps } from "./Tabs";
import { DesignerSidePanel } from "./DesignerSidePanel";

type TabKey = "block" | "preview" | "fields";

/** The panel with the caller-held state the designer keeps: the active tab and whether it is folded. */
function Harness({ startFolded = false }: { startFolded?: boolean }) {
  const idPrefix = useId();
  const [active, setActive] = useState<TabKey>("block");
  const [collapsed, setCollapsed] = useState(startFolded);
  const [typed, setTyped] = useState("");
  return (
    <DesignerSidePanel<TabKey>
      label="Designer tools" idPrefix={idPrefix} active={active} onChange={setActive} collapsed={collapsed} onCollapsedChange={setCollapsed}
      tabs={[{ key: "block", label: "Block" }, { key: "preview", label: "Preview" }, { key: "fields", label: "Fields" }]}
    >
      <div {...tabPanelProps(idPrefix, "block")} hidden={active !== "block"}>
        <input aria-label="Heading" value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>
      <div {...tabPanelProps(idPrefix, "preview")} hidden={active !== "preview"}>Preview panel</div>
      <div {...tabPanelProps(idPrefix, "fields")} hidden={active !== "fields"}>Fields panel</div>
    </DesignerSidePanel>
  );
}

/**
 * The report designer's right-hand panel: tabs over the tools of the view being edited, folded to a rail with the same toggle
 * the detail page's aside uses. Below 1100px it stacks under the editor and has no toggle.
 */
const meta: Meta<typeof Harness> = {
  title: "Components/DesignerSidePanel",
  component: Harness,
};
export default meta;

type Story = StoryObj<typeof Harness>;

export const ShowsTheActiveTabAndHidesTheOthers: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("complementary", { name: "Designer tools" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Block" })).toHaveAttribute("aria-selected", "true");
    await expect(canvas.getByRole("textbox", { name: "Heading" })).toBeVisible();
    await expect(canvas.getByText("Preview panel")).not.toBeVisible();
    await userEvent.click(canvas.getByRole("tab", { name: "Preview" }));
    await expect(canvas.getByText("Preview panel")).toBeVisible();
    await expect(canvas.getByRole("textbox", { name: "Heading", hidden: true })).not.toBeVisible();
  },
};

/** A tab that is not showing stays mounted, so what was typed in it is still there when it comes back. */
export const ATabKeepsItsStateWhileAnotherShows: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Heading" }), "Kept");
    await userEvent.click(canvas.getByRole("tab", { name: "Fields" }));
    await userEvent.click(canvas.getByRole("tab", { name: "Block" }));
    await expect(canvas.getByRole("textbox", { name: "Heading" })).toHaveValue("Kept");
  },
};

/** Folding hides the body but keeps it mounted; the toggle (wide layout only) brings it back. */
export const FoldsToARailAndExpands: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Heading" }), "Kept");
    const hide = canvas.queryByRole("button", { name: "Hide designer panel" });
    // The toggle only exists in the wide layout; skip the interaction in a narrow viewport.
    if (!hide) return;
    await expect(hide).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(hide);
    await expect(canvas.queryByRole("tab", { name: "Block" })).not.toBeInTheDocument();
    const show = canvas.getByRole("button", { name: "Show designer panel" });
    await expect(show).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(show);
    await expect(canvas.getByRole("textbox", { name: "Heading" })).toHaveValue("Kept");
  },
};

export const StartsFoldedWhenToldTo: Story = {
  args: { startFolded: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const show = canvas.queryByRole("button", { name: "Show designer panel" });
    if (!show) return;
    await expect(canvas.queryByRole("tab", { name: "Preview" })).not.toBeInTheDocument();
  },
};
