import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";
import { MessageSquareText, Pencil, Plus, Trash2 } from "lucide-react";

import { Badge } from "./Badge";
import { iconSizeGeometry, iconSizeViolations } from "../testing/iconSizes";

/**
 * Icon sizes (style guide "Pattern: button sizes" and "Icons"): the container decides the icon's size in
 * CSS, 16px in a medium button, 14px in a small one and 12px in a pill, whatever `size` the icon was
 * given; a long nav-rail label must not squeeze its icon.
 */
const meta: Meta = { title: "Patterns/Button icons" };
export default meta;

type Story = StoryObj;

const sizes = (root: HTMLElement) => iconSizeGeometry(root).measurements.map((m) => `${m.context}:${m.widthPx}`);

/** Medium buttons, text and icon-only, hold a 16px icon. */
export const MediumButtons: Story = {
  render: () => (
    <div className="row">
      <button className="btn"><Plus />Add</button>
      <button className="btn btn-icon" aria-label="Edit" title="Edit"><Pencil /></button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["btn:16", "btn:16"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** Small buttons hold a 14px icon. */
export const SmallButtons: Story = {
  render: () => (
    <div className="row">
      <button className="btn btn-sm"><Plus />Add</button>
      <button className="btn btn-sm btn-icon" aria-label="Delete" title="Delete"><Trash2 /></button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["btn-sm:14", "btn-sm:14"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** A `size` prop on the icon cannot override the button: this is the drift the CSS rule exists to stop. */
export const SizePropIsOverriddenByTheButton: Story = {
  render: () => (
    <div className="row">
      <button className="btn"><Plus size={24} />Add</button>
      <button className="btn btn-sm"><Plus size={24} />Add</button>
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["btn:16", "btn-sm:14"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** The check itself fails when an icon is forced to the wrong size, so it cannot pass vacuously. */
export const CheckDetectsAWrongSize: Story = {
  render: () => (
    <button className="btn" aria-label="Add"><Plus style={{ width: 20, height: 20 }} /></button>
  ),
  play: async ({ canvasElement }) => {
    await expect(iconSizeViolations(canvasElement)).toHaveLength(1);
  },
};

/** Pills hold a 12px icon. */
export const PillIcons: Story = {
  render: () => <Badge icon={<MessageSquareText size={20} />}>Clarified</Badge>,
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["badge:12"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** The collapsed (icon-only) rail uses 14px icons. */
export const CollapsedNavLinkIcon: Story = {
  render: () => (
    <nav className="nav-rail nav-rail-icons" style={{ position: "static" }}>
      <a className="nav-link" href="#x" aria-label="Plus"><Plus size={16} /></a>
    </nav>
  ),
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["nav:14"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};

/** A label too long for the rail shrinks; the icon stays a whole 16px. */
export const NavLinkIconIsNotSqueezed: Story = {
  render: () => (
    <nav className="nav-rail" style={{ width: 160, position: "static" }}>
      <a className="nav-link" href="#long">
        <Plus size={16} /><span className="nav-label">A navigation label far too long for this rail</span>
      </a>
    </nav>
  ),
  play: async ({ canvasElement }) => {
    await expect(sizes(canvasElement)).toEqual(["nav:16"]);
    await expect(iconSizeViolations(canvasElement)).toEqual([]);
  },
};
