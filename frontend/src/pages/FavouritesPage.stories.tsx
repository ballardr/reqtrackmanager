import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

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
    // The server now does the favourite/search filtering (`favorite_only`
    // on `GET /projects`) rather than the page fetching every project and
    // filtering client-side — the mock only ever needs to return what's
    // already favourited.
    spyOn(api, "getPage").mockResolvedValue({
      items: [buildProjectListItem({ id: "p1", name: "Atlas Platform", is_favorite: true })],
      total: 1,
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
  },
};

export const Unfavorite: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [buildProjectListItem({ id: "p1", name: "Atlas Platform", is_favorite: true })],
      total: 1,
    });
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Remove from favourites" }));
    await expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/p1/favorite");
  },
};

export const SearchNarrowsTheList: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [buildProjectListItem({ id: "p1", name: "Atlas Platform", is_favorite: true })],
      total: 1,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Atlas Platform")).toBeInTheDocument();
    await userEvent.type(canvas.getByPlaceholderText("Search projects"), "atlas");
    await waitFor(() =>
      expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("search=atlas"))
    );
  },
};

export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: Array.from({ length: 30 }, (_, i) => buildProjectListItem({ id: `p${i}`, name: `Project ${i}`, is_favorite: true })),
      total: 35,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: /30\/35/ })).toBeInTheDocument();
  },
};

export const Empty: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No projects to show.")).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...FavouritedProjects, globals: { theme: "light" } };
export const DarkTheme: Story = { ...FavouritedProjects, globals: { theme: "dark" } };
