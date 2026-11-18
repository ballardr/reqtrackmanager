import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";
import { Download, Pencil } from "lucide-react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { contrastRatio } from "../utils/color";
import { ActionMenu } from "./ActionMenu";

const meta: Meta<typeof ActionMenu> = {
  title: "Components/ActionMenu",
  component: ActionMenu,
  args: {
    triggerLabel: "Acme Corp actions",
    items: [
      { label: "Rename", icon: <Pencil size={14} />, onSelect: fn() },
      { label: "Export Acme Corp bundle", icon: <Download size={14} />, onSelect: fn() },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof ActionMenu>;

/** The trigger is a single icon-only kebab button, named by `triggerLabel`
 * (Principle 8 — every interactive control has a real name) rather than a
 * generic, unnamed "More actions". Clicking it reveals both items as
 * `role="menuitem"` rows inside a `role="menu"` container. */
export const OpensMenuWithBothActions: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Acme Corp actions" });
    await expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument();

    await userEvent.click(trigger);
    const menu = within(document.body).getByRole("menu", { name: "Acme Corp actions" });
    await expect(within(menu).getByRole("menuitem", { name: "Rename" })).toBeInTheDocument();
    await expect(within(menu).getByRole("menuitem", { name: "Export Acme Corp bundle" })).toBeInTheDocument();
  },
};

/** Selecting an item closes the menu and calls that item's own `onSelect`
 * — callers don't have to close the menu themselves. */
export const SelectingAnItemClosesMenuAndFires: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Acme Corp actions" });

    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rename" }));
    await expect(args.items[0].onSelect).toHaveBeenCalledOnce();
    await expect(args.items[1].onSelect).not.toHaveBeenCalled();
    await expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument();
  },
};

/** Shared `Popover` outside-click-close behaviour — this component doesn't
 * reimplement it. */
export const OutsideClickClosesTheMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    await expect(within(document.body).getByRole("menu")).toBeInTheDocument();

    await userEvent.click(document.body);
    await expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument();
  },
};

/** `disabled` disables the trigger itself — used by `OrgAdminPage` while an
 * export triggered from this same menu is already in flight. */
export const Disabled: Story = {
  args: { disabled: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Acme Corp actions" })).toBeDisabled();
  },
};

/** An item is inserted ahead of the others while the menu is open (Org
 * Admin adds "Rename" once its settings load). Each button must keep its
 * own action: with index keys, clicking "Export" ran Rename (2026-10-04). */
export const ItemsChangeWhileOpen: Story = {
  render: () => {
    function Harness() {
      const [loaded, setLoaded] = useState(false);
      const [ran, setRan] = useState("");
      useEffect(() => {
        const timer = setTimeout(() => setLoaded(true), 300);
        return () => clearTimeout(timer);
      }, []);
      return (
        <>
          <ActionMenu
            triggerLabel="Organisation actions"
            items={[
              ...(loaded ? [{ label: "Rename", onSelect: () => setRan("rename") }] : []),
              { label: "Export", onSelect: () => setRan("export") },
            ]}
          />
          <output>{ran}</output>
        </>
      );
    }
    return <Harness />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Organisation actions" }));
    const body = within(document.body);
    const exportItem = await body.findByRole("menuitem", { name: "Export" });
    // "Rename" appears ahead of it while the menu is open.
    await body.findByRole("menuitem", { name: "Rename" });
    await userEvent.click(exportItem);
    await expect(canvas.getByRole("status")).toHaveTextContent("export");
  },
};

/** A menu taller than the window (the Add block menu grows with every block type) is capped to the room and
 * scrolls inside: scrolling it must stay put (the popover once re-measured on its own scroll and reset it to the
 * top), so the last entry can be reached and stays in view when it takes focus. */
export const AMenuTallerThanTheWindowScrollsToItsLastEntry: Story = {
  args: {
    items: Array.from({ length: 30 }, (_, i) => ({ label: `Entry ${String(i + 1)}`, onSelect: fn() })),
  },
  decorators: [(Story) => <div style={{ height: 300, overflow: "hidden" }}><Story /></div>],
  parameters: { viewport: { defaultViewport: "mobile1" } },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
    const popover = within(document.body).getByRole("dialog", { name: "Acme Corp actions" });
    const menu = within(popover).getByRole("menu");
    const last = within(menu).getByRole("menuitem", { name: "Entry 30" });
    await waitFor(() => expect(popover.scrollHeight).toBeGreaterThan(popover.clientHeight));
    await expect(popover.getBoundingClientRect().bottom).toBeLessThanOrEqual(window.innerHeight);

    last.focus();
    await waitFor(() => expect(popover.scrollTop).toBeGreaterThan(0));
    const scrolled = popover.scrollTop;
    // Let the scroll event (and any re-measure it wrongly triggers) settle, then check the offset held.
    await new Promise((resolve) => setTimeout(resolve, 100));
    await expect(popover.scrollTop).toBe(scrolled);
    const rect = last.getBoundingClientRect();
    await expect(rect.bottom).toBeLessThanOrEqual(window.innerHeight);
    await expect(rect.top).toBeGreaterThanOrEqual(0);
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };

const submenuItems = () => [
  { label: "Rename", onSelect: fn() },
  {
    label: "Download items",
    onSelect: fn(),
    children: [
      { label: "CSV", hint: "re-imports", onSelect: fn() },
      { label: "ODT", title: "OpenDocument text", onSelect: fn() },
    ],
  },
  { label: "Delete", danger: true, onSelect: fn() },
];

/** An item with `children` is a parent row: `aria-expanded`, opened and closed by a click, its rows in a labelled group
 * beneath it, and its own `onSelect` is never called. The first parent starts open. Choosing a child closes the whole
 * menu and calls the child's `onSelect`. */
export const AParentExpandsInPlaceAndItsItemRunsInsteadOfTheParent: Story = {
  args: { items: submenuItems() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
    const body = within(document.body);
    const parent = body.getByRole("menuitem", { name: "Download items" });
    await expect(parent).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(parent);
    await expect(parent).toHaveAttribute("aria-expanded", "false");
    await expect(body.queryByRole("group", { name: "Download items" })).not.toBeInTheDocument();
    await userEvent.click(parent);
    const group = within(await body.findByRole("group", { name: "Download items" }));
    await userEvent.click(group.getByRole("menuitem", { name: "ODT" }));
    const parentItem = args.items[1];
    await expect(parentItem.children?.[1].onSelect).toHaveBeenCalledOnce();
    await expect(parentItem.onSelect).not.toHaveBeenCalled();
    await expect(body.queryByRole("menu")).not.toBeInTheDocument();
  },
};

/** Arrow keys move through the visible rows and Home/End jump; Right opens a parent on its first row, Left returns to
 * the parent and closes its level, and Escape closes only that level (the menu stays), then the menu. */
export const ATreeIsOperableFromTheKeyboard: Story = {
  args: { items: submenuItems() },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
    const body = within(document.body);
    body.getByRole("menuitem", { name: "Rename" }).focus();
    await userEvent.keyboard("{End}");
    await expect(body.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    await expect(body.getByRole("menuitem", { name: "ODT" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    await expect(body.getByRole("menuitem", { name: "Download items" })).toHaveFocus();
    await expect(body.queryByRole("group", { name: "Download items" })).not.toBeInTheDocument();
    await userEvent.keyboard("{ArrowRight}");
    await waitFor(() => expect(body.getByRole("menuitem", { name: /^CSV/ })).toHaveFocus());
    await userEvent.keyboard("{Escape}");
    await expect(body.getByRole("menuitem", { name: "Download items" })).toHaveFocus();
    await expect(body.getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await expect(body.queryByRole("menu")).not.toBeInTheDocument();
  },
};

/** Tab leaves the menu: it closes and focus returns to the trigger. */
export const TabClosesTheMenu: Story = {
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Acme Corp actions" });
    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("menu")).toBeInTheDocument();
    await userEvent.keyboard("{Tab}");
    await expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument();
    await expect(trigger).toHaveFocus();
  },
};

/** Items sharing a `group` become a parent row named for the group (a lone grouped item keeps the name as a heading);
 * every row is a plain text row, never a `btn`. */
export const GroupsBecomeParentsAndRowsAreNotButtons: Story = {
  args: {
    items: [
      { label: "Service", group: "New software element", onSelect: fn() },
      { label: "Module", group: "New software element", onSelect: fn() },
      { label: "Board", group: "New hardware element", onSelect: fn() },
      { label: "Chip", group: "New hardware element", onSelect: fn() },
      { label: "Set up", group: "Settings", onSelect: fn() },
    ],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
    const body = within(document.body);
    // The first group starts open, the second is closed, the lone item sits flat under its heading.
    await expect(body.getByRole("menuitem", { name: "New software element" })).toHaveAttribute("aria-expanded", "true");
    await expect(body.getByRole("menuitem", { name: "Service" })).toBeInTheDocument();
    await expect(body.getByRole("menuitem", { name: "New hardware element" })).toHaveAttribute("aria-expanded", "false");
    await expect(body.queryByRole("menuitem", { name: "Board" })).not.toBeInTheDocument();
    await expect(body.getByText("Settings")).toBeInTheDocument();
    await userEvent.click(body.getByRole("menuitem", { name: "New hardware element" }));
    await expect(await body.findByRole("menuitem", { name: "Board" })).toBeInTheDocument();
    for (const row of body.getAllByRole("menuitem")) await expect(row).not.toHaveClass("btn");
  },
};

/** A tree nests to three levels: a group, an item with children, and the items under it. */
export const ATreeNestsToThreeLevels: Story = {
  args: {
    items: [
      { label: "Export", onSelect: fn(), children: [{ label: "Documents", onSelect: fn(), children: [{ label: "PDF", onSelect: fn() }] }] },
    ],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
    const body = within(document.body);
    await userEvent.click(body.getByRole("menuitem", { name: "Documents" }));
    await expect(await body.findByRole("menuitem", { name: "PDF" })).toBeInTheDocument();
  },
};

/** A click on a surface that stops `mousedown` before it reaches the document (React Flow's pane and boxes do, through
 * d3) still closes a menu opened over it. The menu once stayed open because it listened on the bubbling `mousedown`. */
export const AClickOnASurfaceThatStopsMouseDownClosesTheMenu: Story = {
  decorators: [
    (Story) => (
      <div>
        <Story />
        <div
          data-testid="swallows"
          style={{ width: 200, height: 80 }}
          ref={(el) => el?.addEventListener("mousedown", (e) => e.stopPropagation())}
        >
          Pane
        </div>
      </div>
    ),
  ],
  play: async ({ canvasElement }) => {
    const trigger = within(canvasElement).getByRole("button", { name: "Acme Corp actions" });
    await userEvent.click(trigger);
    await expect(within(document.body).getByRole("menu")).toBeInTheDocument();
    await userEvent.click(within(canvasElement).getByTestId("swallows"));
    await waitFor(() => expect(within(document.body).queryByRole("menu")).not.toBeInTheDocument());
    await expect(trigger).toHaveFocus();
  },
};

/** A computed `rgb(r, g, b)` colour as `#rrggbb`, for `contrastRatio`. */
function rgbToHex(rgb: string): string {
  const parts = rgb.match(/\d+/g)?.slice(0, 3).map(Number) ?? [0, 0, 0];
  return `#${parts.map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

/** The colour a token resolves to on the page, as `#rrggbb`. */
function tokenHex(name: string): string {
  const probe = document.createElement("span");
  probe.style.color = `var(${name})`;
  document.body.appendChild(probe);
  const hex = rgbToHex(getComputedStyle(probe).color);
  probe.remove();
  return hex;
}

/** The open entry of a tree takes the product's selected-state colour (the primary slate, in a heavier weight), never
 * the green accent, and is readable on the menu's surface in the active theme. */
async function expectOpenEntryUsesPrimary(canvasElement: HTMLElement): Promise<void> {
  await userEvent.click(within(canvasElement).getByRole("button", { name: "Acme Corp actions" }));
  const parent = within(document.body).getByRole("menuitem", { name: "Download items" });
  await expect(parent).toHaveAttribute("aria-expanded", "true");
  const colour = rgbToHex(getComputedStyle(parent).color);
  await expect(colour).toBe(tokenHex("--color-primary"));
  await expect(colour).not.toBe(tokenHex("--color-accent"));
  await expect(Number(getComputedStyle(parent).fontWeight)).toBeGreaterThanOrEqual(600);
  const surface = rgbToHex(getComputedStyle(parent.closest(".popover-menu") ?? document.body).backgroundColor);
  await expect(contrastRatio(colour, surface)).toBeGreaterThanOrEqual(4.5);
}

export const TheOpenEntryTakesTheProductColourInLightTheme: Story = {
  args: { items: submenuItems() },
  globals: { theme: "light" },
  play: async ({ canvasElement }) => expectOpenEntryUsesPrimary(canvasElement),
};

export const TheOpenEntryTakesTheProductColourInDarkTheme: Story = {
  args: { items: submenuItems() },
  globals: { theme: "dark" },
  play: async ({ canvasElement }) => expectOpenEntryUsesPrimary(canvasElement),
};
