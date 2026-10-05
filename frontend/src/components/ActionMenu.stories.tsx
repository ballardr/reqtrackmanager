import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState } from "react";
import { Download, Pencil } from "lucide-react";
import { expect, fn, userEvent, within } from "storybook/test";

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

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
