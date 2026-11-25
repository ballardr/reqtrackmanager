import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { expectTextRows } from "../testing/menuRows";
import { withRouter } from "../testing/storybook-helpers";
import { EntitySwitcher, type EntitySwitcherOption } from "./EntitySwitcher";

function resolvedLoader(options: EntitySwitcherOption[]) {
  return () => Promise.resolve(options);
}

const MANY_OPTIONS: EntitySwitcherOption[] = [
  { id: "org-1", label: "Current Org", href: "/orgs/org-1/overview" },
  ...Array.from({ length: 10 }, (_, i) => ({
    id: `org-${i + 2}`,
    label: `Organisation ${i + 2}`,
    href: `/orgs/org-${i + 2}/overview`,
  })),
];

const meta: Meta<typeof EntitySwitcher> = {
  title: "Components/EntitySwitcher",
  component: EntitySwitcher,
  decorators: [withRouter("/orgs/org-1/overview", "/orgs/:orgId/overview")],
  args: {
    label: "Switch organisation",
    currentId: "org-1",
    loadOptions: resolvedLoader(MANY_OPTIONS),
  },
};
export default meta;

type Story = StoryObj<typeof EntitySwitcher>;

/** The loader resolves with only the current entity (or nothing): there is nothing to switch to, so the chevron
 * never renders. */
export const NoSiblingsRendersNothing: Story = {
  args: {
    loadOptions: resolvedLoader([{ id: "org-1", label: "Acme Corp", href: "/orgs/org-1/overview" }]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Give the loader's microtask a turn before asserting absence.
    await new Promise((r) => setTimeout(r, 0));
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
};

/** A single sibling — the chevron renders, opens onto exactly one link,
 * and (below the filtering threshold) shows no filter input. */
export const SingleSibling: Story = {
  args: {
    loadOptions: resolvedLoader([
      { id: "org-1", label: "Acme Corp", href: "/orgs/org-1/overview" },
      { id: "org-2", label: "Globex Corporation", href: "/orgs/org-2/overview" },
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });
    await userEvent.click(trigger);

    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getByRole("link", { name: "Globex Corporation" })).toBeInTheDocument();
    await expect(within(dialog).queryByRole("textbox")).not.toBeInTheDocument();
  },
};

/** With more than a handful of siblings a filter input appears above the list, narrowing it as the user types. */
export const ManyEntitiesWithFiltering: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });
    await userEvent.click(trigger);

    const dialog = within(document.body).getByRole("dialog", { name: "Switch organisation" });
    await expect(within(dialog).getAllByRole("link")).toHaveLength(10);

    await userEvent.type(within(dialog).getByPlaceholderText("Filter…"), "Organisation 7");
    const links = within(dialog).getAllByRole("link");
    await expect(links).toHaveLength(1);
    await expect(links[0]).toHaveTextContent("Organisation 7");
  },
};

/** Picking a sibling closes the popover and navigates to its `href` — a
 * plain link click, nothing bespoke. */
export const SelectingASiblingClosesThePopover: Story = {
  args: {
    loadOptions: resolvedLoader([
      { id: "org-1", label: "Acme Corp", href: "/orgs/org-1/overview" },
      { id: "org-2", label: "Globex Corporation", href: "/orgs/org-2/overview" },
    ]),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Switch organisation" }));
    // The destinations are plain text rows like every menu, never standard buttons.
    await expectTextRows(within(document.body).getByRole("dialog", { name: "Switch organisation" }));
    await userEvent.click(within(document.body).getByRole("link", { name: "Globex Corporation" }));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** The trigger is borderless and transparent at rest, not a bordered `.btn` chip beside the entity name;
 * `theme.css` adds a background on hover and focus. The hover rule is not asserted (pseudo-classes are not
 * reliably observable through `userEvent.hover`); the class and border assertions guard the chrome. */
export const ChevronChromeIsBorderless: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = await canvas.findByRole("button", { name: "Switch organisation" });

    await expect(trigger).toHaveClass("entity-switcher-trigger");
    await expect(trigger).not.toHaveClass("btn");
    const atRest = getComputedStyle(trigger);
    await expect(atRest.borderStyle === "none" || atRest.borderWidth === "0px").toBe(true);
    await expect(atRest.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  },
};

/** The caller's options gain a sibling after mount (e.g. a version created
 * while the page was open): changing `reloadKey` refetches, so the switcher
 * appears instead of keeping its first, sibling-less list. */
export const ReloadKeyPicksUpNewSiblings: Story = {
  render: function Render(args) {
    const [options, setOptions] = useState<EntitySwitcherOption[]>([
      { id: "org-1", label: "Current Org", href: "/orgs/org-1/overview" },
    ]);
    return (
      <div className="row">
        <EntitySwitcher {...args} loadOptions={resolvedLoader(options)} reloadKey={options.map((o) => o.id).join(",")} />
        <button
          className="btn"
          onClick={() => setOptions((prev) => [...prev, { id: "org-2", label: "New Org", href: "/orgs/org-2/overview" }])}
        >
          Add sibling
        </button>
      </div>
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Switch organisation" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Add sibling" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "Switch organisation" })).toBeInTheDocument());
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
