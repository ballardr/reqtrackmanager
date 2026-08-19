import type { Meta, StoryObj } from "@storybook/react-vite";
import { useId, useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { Tabs, tabPanelProps } from "./Tabs";

type TabKey = "overview" | "stages" | "reports";

function Interactive() {
  // A fresh id per mounted instance, not a hardcoded string — Storybook
  // may keep more than one story's DOM around at once, and a shared
  // literal idPrefix would let document.getElementById (used for the
  // arrow-key focus move) resolve to a different story's element instead
  // of this one's.
  const idPrefix = useId();
  const [active, setActive] = useState<TabKey>("overview");
  const tabs = [
    { key: "overview" as const, label: "Overview" },
    { key: "stages" as const, label: "Stages" },
    { key: "reports" as const, label: "Reports" },
  ];
  return (
    <div className="stack">
      <Tabs idPrefix={idPrefix} tabs={tabs} active={active} onChange={setActive} />
      {active === "overview" && (
        <div {...tabPanelProps(idPrefix, "overview")} className="card">
          Overview panel
        </div>
      )}
      {active === "stages" && (
        <div {...tabPanelProps(idPrefix, "stages")} className="card">
          Stages panel
        </div>
      )}
      {active === "reports" && (
        <div {...tabPanelProps(idPrefix, "reports")} className="card">
          Reports panel
        </div>
      )}
    </div>
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/Tabs",
  component: Interactive,
};
export default meta;

type Story = StoryObj<typeof Interactive>;

export const ClickSwitchesTab: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("tab", { name: "Overview", selected: true })).toBeInTheDocument();
    await expect(canvas.getByText("Overview panel")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("tab", { name: "Stages" }));
    await expect(canvas.getByRole("tab", { name: "Stages", selected: true })).toBeInTheDocument();
    await expect(canvas.getByText("Stages panel")).toBeInTheDocument();
    await expect(canvas.queryByText("Overview panel")).not.toBeInTheDocument();
  },
};

/** The tablist/tabpanel relationship is real, not just visual — each
 * panel's `aria-labelledby` points at its tab's own `id`, and vice versa
 * via `aria-controls`. */
export const PanelsAreLabelledByTheirTab: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const tab = canvas.getByRole("tab", { name: "Overview" });
    const panel = canvas.getByRole("tabpanel");
    await expect(tab.getAttribute("aria-controls")).toBe(panel.id);
    await expect(panel.getAttribute("aria-labelledby")).toBe(tab.id);
  },
};

/** Only the active tab is in the Tab-key order (roving tabindex) —
 * arrow keys are how you move between tabs, matching the WAI-ARIA APG
 * "Tabs with automatic activation" pattern. */
export const ArrowKeysNavigateAndActivate: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const overviewTab = canvas.getByRole("tab", { name: "Overview" });
    const stagesTab = canvas.getByRole("tab", { name: "Stages" });
    const reportsTab = canvas.getByRole("tab", { name: "Reports" });

    await expect(overviewTab).toHaveAttribute("tabindex", "0");
    await expect(stagesTab).toHaveAttribute("tabindex", "-1");

    overviewTab.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(stagesTab).toHaveFocus();
    await expect(stagesTab).toHaveAttribute("aria-selected", "true");
    await expect(canvas.getByText("Stages panel")).toBeInTheDocument();

    await userEvent.keyboard("{End}");
    await expect(reportsTab).toHaveFocus();
    await expect(reportsTab).toHaveAttribute("aria-selected", "true");

    // Wraps past the last tab back to the first.
    await userEvent.keyboard("{ArrowRight}");
    await expect(overviewTab).toHaveFocus();

    await userEvent.keyboard("{Home}");
    await expect(overviewTab).toHaveFocus();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
