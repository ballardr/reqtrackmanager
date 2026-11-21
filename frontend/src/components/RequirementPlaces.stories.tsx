import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import {
  ALIAS_PROJECT_ID, buildAliasSettings, buildAliasedRequirement, buildAliasesApi, buildIndependentResult, buildOptionsApi,
  buildTreeApi,
} from "../testing/requirementAliasFixtures";
import { RequirementPlaces } from "./RequirementPlaces";

/**
 * The requirement page's "Components and codes" section: each place with its code, and for a further place the actions
 * to remove it, make it the own place or make it independent.
 */
const meta: Meta<typeof RequirementPlaces> = {
  title: "Components/RequirementPlaces",
  component: RequirementPlaces,
  args: {
    projectId: ALIAS_PROJECT_ID, requirement: buildAliasedRequirement(), canPlace: true, canEdit: true, onChanged: fn(),
    api: buildAliasesApi(), placementsApi: buildTreeApi(), linksApi: buildOptionsApi(),
  },
  decorators: [(Story) => <MemoryRouter><Story /></MemoryRouter>],
};
export default meta;

type Story = StoryObj<typeof RequirementPlaces>;

async function openMenu(canvas: ReturnType<typeof within>) {
  await userEvent.click(await canvas.findByRole("button", { name: "Actions for HW-COOL-002" }));
}

export const ListsEachPlaceWithItsCode: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Software / Performance")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Code SW-PERF-001")).toBeInTheDocument();
    await expect(canvas.getByText("Own place")).toBeInTheDocument();
    // The place also reads in the picker's summary below the list.
    await expect(canvas.getAllByText("Hardware / Cooling").length).toBeGreaterThan(0);
    await expect(canvas.getByLabelText("Code HW-COOL-002")).toBeInTheDocument();
    await expect(canvas.getByText("Alias")).toBeInTheDocument();
  },
};

export const RemovingAPlaceRetiresItsCode: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas);
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Remove from this component" }));
    await userEvent.click(await within(document.body).findByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.api!.retire).toHaveBeenCalledWith(ALIAS_PROJECT_ID, "req-1", "alias-1"));
    await expect(args.onChanged).toHaveBeenCalled();
  },
};

export const MakingAPlaceTheOwnSwapsTheCodes: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas);
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Make this the own place" }));
    await expect(await within(document.body).findByText(/keeps SW-PERF-001 as an alias/)).toBeInTheDocument();
    await userEvent.click(await within(document.body).findByRole("button", { name: "Make own place" }));
    await waitFor(() => expect(args.api!.promote).toHaveBeenCalledWith(ALIAS_PROJECT_ID, "req-1", "alias-1"));
  },
};

export const MakingAPlaceTheOwnIsUnavailableWhileApproved: Story = {
  args: { requirement: buildAliasedRequirement({}, true) },
  play: async ({ canvasElement }) => {
    await openMenu(within(canvasElement));
    await expect(await within(document.body).findByRole("menuitem", { name: "Make this the own place" })).toBeDisabled();
  },
};

export const MakingAnAliasIndependentNeedsTheCodeTypedThenReportsWhatWasNotCopied: Story = {
  args: {
    api: buildAliasesApi(undefined, {
      makeIndependent: fn(async () => buildIndependentResult({
        skipped: [{ kind: "link", label: "DEC-003 Use a bus", reason: "An approved requirement is involved and this project requires links to be added via a change request." }],
      })),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas);
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Make independent" }));
    const body = within(document.body);
    const confirm = await body.findByRole("button", { name: "Make independent" });
    await waitFor(() => expect(confirm).toBeDisabled());
    await userEvent.type(await body.findByLabelText('Type "HW-COOL-002" to confirm'), "HW-COOL-002");
    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    await waitFor(() => expect(args.api!.makeIndependent).toHaveBeenCalledWith(ALIAS_PROJECT_ID, "req-1", "alias-1", undefined));
    await expect(await body.findByText(/DEC-003 Use a bus/)).toBeInTheDocument();
    await expect(body.getByRole("link", { name: "Open the new requirement" })).toHaveAttribute("href", `/projects/${ALIAS_PROJECT_ID}/requirements/req-2`);
  },
};

export const AsksForALinkTypeWhenThereIsNoRelatedTo: Story = {
  args: { linksApi: buildOptionsApi(true) },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas);
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Make independent" }));
    const body = within(document.body);
    await userEvent.type(await body.findByLabelText('Type "HW-COOL-002" to confirm'), "HW-COOL-002");
    const confirm = await body.findByRole("button", { name: "Make independent" });
    await expect(confirm).toBeDisabled();
    await userEvent.selectOptions(await body.findByLabelText(/Link type joining the two requirements/), "lt-derives");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.api!.makeIndependent).toHaveBeenCalledWith(ALIAS_PROJECT_ID, "req-1", "alias-1", "lt-derives"));
  },
};

export const AddingAPlaceAsksTheServerForTheWholeSet: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Components and categories" }));
    await userEvent.click(await within(document.body).findByRole("checkbox", { name: "Hardware / Power" }));
    await waitFor(() => expect(args.api!.setPlaces).toHaveBeenCalledWith(ALIAS_PROJECT_ID, "req-1", [
      { component_id: "c-hw", category_id: "k-cool" }, { component_id: "c-hw", category_id: "k-power" },
    ]));
  },
};

export const ReadOnlyForSomeoneWhoCannotPlace: Story = {
  args: { canPlace: false, canEdit: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Hardware / Cooling")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Actions for HW-COOL-002" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Components and categories" })).not.toBeInTheDocument();
  },
};

export const NothingWithoutAliasesWhenNewOnesAreDisabled: Story = {
  args: {
    requirement: buildAliasedRequirement({ aliases: [] }),
    api: buildAliasesApi(buildAliasSettings({ mode: "disabled", alias_count: 0 })),
  },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.api!.settings).toHaveBeenCalled());
    await expect(within(canvasElement).queryByRole("heading", { name: "Components and codes" })).not.toBeInTheDocument();
  },
};
