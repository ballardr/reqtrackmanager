import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

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

/** The loader resolves with only the current entity (or an empty list) —
 * there's nothing to switch to, so the chevron never renders at all,
 * rather than appearing and immediately disappearing once loading
 * resolves. */
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

/** More than a handful of siblings — a filter input appears above the
 * list, narrowing it as the user types (`UserAutocomplete`'s own
 * lowercase/substring-filter idiom, reused here rather than the component
 * itself). */
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
    await userEvent.click(within(document.body).getByRole("link", { name: "Globex Corporation" }));
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
