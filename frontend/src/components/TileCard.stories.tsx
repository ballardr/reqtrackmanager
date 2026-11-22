import type { Meta, StoryObj } from "@storybook/react-vite";
import { Star } from "lucide-react";
import { expect, within } from "storybook/test";

import { withRouter } from "../testing/storybook-helpers";
import { Badge } from "./Badge";
import { TileCard, TileGrid } from "./TileCard";

const meta: Meta<typeof TileCard> = {
  title: "Components/TileCard",
  component: TileCard,
  decorators: [withRouter("/", "*")],
};
export default meta;

type Story = StoryObj<typeof TileCard>;

/** A project card and a Compliance standard card in one grid: the same chrome, the title the link. */
function ProjectAndStandard() {
  return (
    <TileGrid>
      <TileCard
        title="Payments Platform"
        to="/projects/project-1"
        titleBadges={<Badge>Template</Badge>}
        actions={<button className="btn" aria-label="Remove from favourites"><Star fill="currentColor" /></button>}
      >
        <div className="text-muted" style={{ fontSize: "0.8rem" }}>Acme Corp</div>
        <div className="text-muted" style={{ fontSize: "0.85rem" }}>Requirements: 24</div>
      </TileCard>
      <TileCard title="ISO 27001" to="/standards/std-1">
        <div className="text-muted" style={{ fontSize: "0.85rem" }}>ISO-27001</div>
        <div className="text-muted" style={{ fontSize: "0.8rem" }}>Acme Corp</div>
        <div className="text-muted" style={{ fontSize: "0.8rem" }}>Active</div>
      </TileCard>
    </TileGrid>
  );
}

export const ProjectAndStandardCards: Story = {
  render: () => <ProjectAndStandard />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // The title is the link, and only the title: the favourite star beside it is its own control.
    await expect(canvas.getByRole("link", { name: "Payments Platform" })).toHaveAttribute("href", "/projects/project-1");
    await expect(canvas.getByRole("link", { name: "ISO 27001" })).toHaveAttribute("href", "/standards/std-1");
    await expect(canvas.getAllByRole("link")).toHaveLength(2);
    await expect(canvas.getByRole("button", { name: "Remove from favourites" })).toBeInTheDocument();
    await expect(canvas.getByText("Template")).toBeInTheDocument();
  },
};

export const ProjectAndStandardCardsDark: Story = {
  render: () => <ProjectAndStandard />,
  globals: { theme: "dark" },
};

/** A card the person cannot open (a project they are not a member of) is muted text, not a link. */
export const MutedWithoutLink: Story = {
  args: { title: "Restricted Project", muted: true, children: <Badge>Not a member</Badge> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Restricted Project")).toBeInTheDocument();
    await expect(canvas.queryByRole("link")).not.toBeInTheDocument();
  },
};

/** A record card: an entity accent stripe and an eyebrow row (the record code) above the title. */
export const WithAccentAndEyebrow: Story = {
  args: {
    title: "Passwords are stored hashed",
    to: "/projects/project-1/requirements/req-1",
    accentColor: "#2563eb",
    eyebrow: <span className="text-muted" style={{ fontSize: "0.8rem" }}>REQ-001</span>,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("REQ-001")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Passwords are stored hashed" })).toBeInTheDocument();
    await expect(canvasElement.querySelector(".entity-accent-card")).not.toBeNull();
  },
};

/** A long title is cut with an ellipsis and keeps its full text as the tooltip, so the actions stay in view. */
export const LongTitle: Story = {
  render: () => (
    <div style={{ width: 280 }}>
      <TileCard
        title="A very long standard title that cannot fit on one line of a narrow card"
        to="/standards/std-1"
        actions={<button className="btn" aria-label="Remove from favourites"><Star /></button>}
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("link")).toHaveAttribute("title", expect.stringContaining("A very long standard title"));
    await expect(canvas.getByRole("button", { name: "Remove from favourites" })).toBeVisible();
  },
};
