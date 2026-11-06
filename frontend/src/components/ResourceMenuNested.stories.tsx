import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { expect, userEvent, within } from "storybook/test";

import { ResourceMenu, type ResourceMenuGroupDef } from "./ResourceMenu";

/** Two-level menu: a group with sub-pages is a disclosure button; the active page's group is open, the others closed. */
type NestedKey = "overview" | "risk" | "risk-types" | "risk-scoring" | "feedback" | "feedback-scoring" | "feedback-channels";

const NESTED_GROUPS: ResourceMenuGroupDef<NestedKey>[] = [
  { key: "overview", label: "Overview", href: "/nested/overview" },
  {
    key: "risk",
    label: "Risk Management",
    href: "/nested/risk/risk-types",
    children: [
      { key: "risk-types", label: "Risk Types", href: "/nested/risk/risk-types" },
      { key: "risk-scoring", label: "Risk Scoring", href: "/nested/risk/risk-scoring" },
    ],
  },
  {
    key: "feedback",
    label: "Product Feedback",
    href: "/nested/feedback/feedback-scoring",
    children: [
      { key: "feedback-scoring", label: "Request Scoring", href: "/nested/feedback/feedback-scoring" },
      { key: "feedback-channels", label: "Request Channels", href: "/nested/feedback/feedback-channels" },
    ],
  },
];

function NestedDemo() {
  const { group, section } = useParams<{ group?: string; section?: string }>();
  const active = (section ?? group ?? "overview") as NestedKey;
  return (
    <ResourceMenu ariaLabel="Nested sections" groups={NESTED_GROUPS} active={active}>
      <div className="card">{`Panel: ${active}`}</div>
    </ResourceMenu>
  );
}

const meta: Meta<typeof NestedDemo> = {
  title: "Components/ResourceMenu/Two levels",
  component: NestedDemo,
  decorators: [
    (Story) => (
      <MemoryRouter initialEntries={["/nested/risk/risk-types"]}>
        <Routes>
          <Route path="/nested/:group?/:section?" element={<Story />} />
        </Routes>
      </MemoryRouter>
    ),
  ],
};
export default meta;
type Story = StoryObj<typeof NestedDemo>;

export const NestedGroupOpensWithActivePage: Story = {
  render: () => <NestedDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Risk Management" })).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("link", { name: "Risk Types" })).toHaveAttribute("aria-current", "page");
    await expect(canvas.getByRole("link", { name: "Risk Scoring" })).not.toHaveAttribute("aria-current");
    await expect(canvas.getByRole("button", { name: "Product Feedback" })).toHaveAttribute("aria-expanded", "false");
    await expect(canvas.queryByRole("link", { name: "Request Scoring" })).not.toBeInTheDocument();
  },
};

export const NestedHeaderExpandsAndCollapsesWithoutNavigating: Story = {
  render: () => <NestedDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Product Feedback" }));
    await expect(canvas.getByRole("button", { name: "Product Feedback" })).toHaveAttribute("aria-expanded", "true");
    await expect(canvas.getByRole("link", { name: "Request Channels" })).toBeInTheDocument();
    // Expanding another group leaves the page unchanged.
    await expect(canvas.getByText("Panel: risk-types")).toBeInTheDocument();

    // The active page's group can be collapsed too.
    await userEvent.click(canvas.getByRole("button", { name: "Risk Management" }));
    await expect(canvas.queryByRole("link", { name: "Risk Types" })).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("link", { name: "Request Channels" }));
    await expect(canvas.getByText("Panel: feedback-channels")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Request Channels" })).toHaveAttribute("aria-current", "page");
  },
};

/** Arrow keys move through the rows shown (headers and open groups' sub-pages); a header only takes focus. */
export const NestedArrowKeysSkipClosedGroups: Story = {
  render: () => <NestedDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const overview = canvas.getByRole("link", { name: "Overview" });
    overview.focus();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("button", { name: "Risk Management" })).toHaveFocus();
    // Moving onto a header does not navigate.
    await expect(canvas.getByText("Panel: risk-types")).toBeInTheDocument();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("link", { name: "Risk Types" })).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}{ArrowDown}");
    await expect(canvas.getByRole("button", { name: "Product Feedback" })).toHaveFocus();
    // The closed group has no sub-pages to visit; the next row wraps to the first.
    await userEvent.keyboard("{ArrowDown}");
    await expect(overview).toHaveFocus();
    await expect(canvas.getByText("Panel: overview")).toBeInTheDocument();
  },
};
