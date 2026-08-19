import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { expect, userEvent, within } from "storybook/test";

import { ResourceMenu, type ResourceMenuGroupDef } from "./ResourceMenu";

type GroupKey = "overview" | "people" | "settings";

const GROUPS: ResourceMenuGroupDef<GroupKey>[] = [
  { key: "overview", label: "Overview", href: "/demo/overview" },
  { key: "people", label: "People", href: "/demo/people" },
  { key: "settings", label: "Settings", href: "/demo/settings" },
];

/** Reads the active group straight from the route (`:group`), the same way
 * `OrgAdminPage` does — this is what makes the menu's selection a real
 * navigation rather than client-only state. */
function Demo() {
  const { group } = useParams<{ group?: string }>();
  const active = GROUPS.find((g) => g.key === group)?.key ?? "overview";
  return (
    <ResourceMenu title="Acme Corp" subtitle="Organisation admin" ariaLabel="Demo sections" groups={GROUPS} active={active}>
      {active === "overview" && <div className="card">Overview panel</div>}
      {active === "people" && <div className="card">People panel</div>}
      {active === "settings" && <div className="card">Settings panel</div>}
    </ResourceMenu>
  );
}

const meta: Meta<typeof Demo> = {
  title: "Components/ResourceMenu",
  component: Demo,
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={["/demo/overview"]}>
        <Routes>
          <Route path="/demo/:group" element={<Story />} />
        </Routes>
      </MemoryRouter>
    ),
  ],
};
export default meta;

type Story = StoryObj<typeof Demo>;

export const ClickSwitchesGroup: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByText("Overview panel")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "People" }));
    await expect(canvas.getByRole("link", { name: "People" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByText("People panel")).toBeInTheDocument();
    // Non-active groups' content is unmounted, not just hidden — matching
    // CollapsibleSection's own collapsed-state behaviour elsewhere in this
    // codebase.
    await expect(canvas.queryByText("Overview panel")).not.toBeInTheDocument();
  },
};

/** Only the active group's link carries `aria-current="page"` — a real
 * link-list semantic, not `aria-selected` from the ARIA "tab" pattern,
 * since each group is a real URL rather than client-only state. */
export const OnlyActiveGroupHasAriaCurrent: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByRole("link", { name: "People" })).not.toHaveAttribute("aria-current");
    await expect(canvas.getByRole("link", { name: "Settings" })).not.toHaveAttribute("aria-current");
  },
};

/** Vertical arrow-key navigation (`ArrowUp`/`ArrowDown`, plus `Home`/`End`)
 * — modelled on Tabs.tsx's own automatic-activation keyboard pattern, just
 * adapted from internal state to real routing: moving focus with an arrow
 * key also navigates, wrapping past the last item back to the first. */
export const ArrowKeysNavigateAndActivate: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const overviewLink = canvas.getByRole("link", { name: "Overview" });
    const peopleLink = canvas.getByRole("link", { name: "People" });
    const settingsLink = canvas.getByRole("link", { name: "Settings" });

    overviewLink.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(peopleLink).toHaveFocus();
    await expect(peopleLink).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByText("People panel")).toBeInTheDocument();

    await userEvent.keyboard("{End}");
    await expect(settingsLink).toHaveFocus();
    await expect(settingsLink).toHaveAttribute("aria-current", "page");

    // Wraps past the last group back to the first.
    await userEvent.keyboard("{ArrowDown}");
    await expect(overviewLink).toHaveFocus();

    await userEvent.keyboard("{Home}");
    await expect(overviewLink).toHaveFocus();
  },
};

/** The `title`/`subtitle` (the entity actually being administered) render
 * once, above the menu+content grid, and — unlike the per-group content
 * panels — stay in the document across a group switch, since they're not
 * part of any one group's own content. Regression coverage for the org/
 * project admin pages having no visible indication of which org/project
 * was being edited (2026-08 UX audit follow-up). */
export const ShowsTitleAndSubtitle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 1, name: "Acme Corp" })).toBeInTheDocument();
    await expect(canvas.getByText("Organisation admin")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "People" }));
    await expect(canvas.getByRole("heading", { level: 1, name: "Acme Corp" })).toBeInTheDocument();
    await expect(canvas.getByText("Organisation admin")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ClickSwitchesGroup, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ClickSwitchesGroup, globals: { theme: "dark" } };
