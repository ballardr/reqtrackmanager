import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { api } from "../api/client";
import { buildProjectListItem, withRouter } from "../testing/storybook-helpers";
import { FavouritesPage } from "./FavouritesPage";

const meta: Meta<typeof FavouritesPage> = {
  title: "Pages/FavouritesPage",
  component: FavouritesPage,
  decorators: [withRouter("/favourites")],
};
export default meta;

type Story = StoryObj<typeof FavouritesPage>;

export const FavouritedProjects: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([
      buildProjectListItem({ id: "p1", name: "Atlas Platform", is_favorite: true }),
      buildProjectListItem({ id: "p2", name: "Beacon Mobile", is_favorite: false }),
    ]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Only the favourited project shows — the non-favourite is filtered client-side.
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    await expect(canvas.queryByText("Beacon Mobile")).not.toBeInTheDocument();
  },
};

export const Unfavorite: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([buildProjectListItem({ id: "p1", name: "Atlas Platform", is_favorite: true })]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove from favourites" }));
    await expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/p1/favorite");
  },
};

export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue([]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No projects to show.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...FavouritedProjects, globals: { theme: "light" } };
export const DarkTheme: Story = { ...FavouritedProjects, globals: { theme: "dark" } };
