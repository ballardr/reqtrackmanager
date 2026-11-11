import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { NavLabelItem } from "../api/types";
import { withToast } from "../testing/storybook-helpers";
import { NavLabelsPanel } from "./NavLabelsPanel";

const ITEMS: NavLabelItem[] = [
  { key: "overview", label: "Overview", path: "/projects/project-1" },
  { key: "requirements", label: "Requirements", path: "/projects/project-1/requirements" },
  { key: "decisions:", label: "Decisions", path: "/projects/project-1/modules/decisions", module_key: "decisions" },
];

/** Navigation names for one tier, shared by Organisation Admin and Project Admin. */
const meta: Meta<typeof NavLabelsPanel> = {
  title: "Components/NavLabelsPanel",
  component: NavLabelsPanel,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof NavLabelsPanel>;

/** Each entry shows its built-in name; a name inherited from the organisation is the placeholder and says where it comes from. */
export const ProjectShowsInheritedNamesAsPlaceholders: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({
      items: ITEMS.map((item) => (item.key === "decisions:"
        ? { ...item, inherited: "ADRs", inherited_from: "organisation", effective: "ADRs" }
        : item)),
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const input = await canvas.findByRole("textbox", { name: "Name for Decisions" });
    await expect(input).toHaveValue("");
    await expect(input).toHaveAttribute("placeholder", "ADRs");
    await expect(canvas.getByText("Organisation default")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Save names" })).toBeDisabled();
  },
};

/** Editing a name and saving sends the whole set of own names; restoring a row removes it from the set. */
export const SavingSendsTheOwnNamesAndRestoreClearsARow: Story = {
  args: { scope: { kind: "project", projectId: "project-1" } },
  beforeEach: () => {
    // The server's copy of the own names: a save replaces it, and the panel reloads from it.
    let names: Record<string, string> = { requirements: "Needs" };
    const items = () => ITEMS.map((item) => (names[item.key] ? { ...item, own: names[item.key], effective: names[item.key] } : item));
    spyOn(api, "get").mockImplementation(async () => ({ items: items() }));
    spyOn(api, "put").mockImplementation(async (_path: string, body: unknown) => {
      names = (body as { names: Record<string, string> }).names;
      return { items: items() };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("textbox", { name: "Name for Requirements" })).toHaveValue("Needs");
    await userEvent.type(canvas.getByRole("textbox", { name: "Name for Decisions" }), "ADRs");
    await userEvent.click(canvas.getByRole("button", { name: "Save names" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/projects/project-1/nav-labels", { names: { requirements: "Needs", "decisions:": "ADRs" } }));

    await userEvent.click(canvas.getByRole("button", { name: "Restore the default name of Requirements" }));
    await expect(canvas.getByRole("textbox", { name: "Name for Requirements" })).toHaveValue("");
    await userEvent.click(canvas.getByRole("button", { name: "Save names" }));
    await waitFor(() => expect(api.put).toHaveBeenLastCalledWith("/api/v1/projects/project-1/nav-labels", { names: { "decisions:": "ADRs" } }));
  },
};

/** The organisation tier writes its defaults to the organisation endpoint. */
export const OrganisationTierSavesDefaults: Story = {
  args: { scope: { kind: "organisation", organizationId: "org-1" } },
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ items: ITEMS.map(({ path: _path, ...rest }) => rest) });
    spyOn(api, "put").mockResolvedValue({ items: ITEMS });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "Name for Decisions" }), "ADRs");
    await userEvent.click(canvas.getByRole("button", { name: "Save names" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/orgs/org-1/nav-labels", { names: { "decisions:": "ADRs" } }));
  },
};
