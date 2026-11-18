import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { expectHeaderOrdersText } from "../../testing/sortHelpers";
import { buildRequest, buildRequestScheme, ORG_ID, ORG_USERS } from "./requestFixtures";
import { OrgRequestsPanel } from "./OrgRequestsPanel";

const meta: Meta<typeof OrgRequestsPanel> = {
  title: "Modules/ProductFeedback/OrgRequestsPanel",
  component: OrgRequestsPanel,
  args: { orgId: ORG_ID },
  decorators: [withStatefulAuth(buildUser({ id: "user-1" })), withRouter("/"), withToast()],
};
export default meta;

type Story = StoryObj<typeof OrgRequestsPanel>;

/** The inbox lists organisation-owned requests with their score but no demand or Pain Point warning. */
export const ListsInboxRequestsWithoutProjectOnlyColumns: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      const route = path.split("?")[0];
      if (route.endsWith("/records/enhancement_request/columns")) return buildRecordColumns({ label: "Enhancement requests" });
      if (route.includes("/scoring-schemes/enhancement_request")) return buildRequestScheme();
      if (route.endsWith("/product_feedback/access")) return { can_submit: true, can_triage: false };
      if (route.endsWith("/modules/product_feedback/requests")) return [buildRequest({ scope: "organization", project_id: null, organization_id: ORG_ID })];
      if (route.includes("/users")) return ORG_USERS;
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Request inbox" });
    await expect(within(table).getByText("Export the list to Excel")).toBeInTheDocument();
    await expect(within(table).getByText("High · 48")).toBeInTheDocument();
    await expect(within(table).queryByText("No Pain Point")).not.toBeInTheDocument();
    await expect(within(table).queryByRole("columnheader", { name: "Demand" })).not.toBeInTheDocument();
  },
};

/** An organisation that switched the inbox off sees a plain explanation, not an error screen. */
export const SaysSoWhenTheInboxIsSwitchedOff: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/modules/product_feedback/requests")) throw new ApiError(404, "Not found");
      if (path.includes("/scoring-schemes/")) return buildRequestScheme();
      return [] as never;
    });
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText(/inbox is switched off/)).toBeInTheDocument();
  },
};

/** The inbox has no Demand column to offer; Owner starts hidden and the Columns control shows it. */
export const TheInboxColumnsControlOffersOwnerButNotDemand: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      const route = path.split("?")[0];
      if (route.endsWith("/records/enhancement_request/columns")) return buildRecordColumns({ label: "Enhancement requests" });
      if (route.includes("/scoring-schemes/enhancement_request")) return buildRequestScheme();
      if (route.endsWith("/product_feedback/access")) return { can_submit: true, can_triage: false };
      if (route.endsWith("/modules/product_feedback/requests")) return [buildRequest({ scope: "organization", project_id: null, organization_id: ORG_ID })];
      if (route.includes("/users")) return ORG_USERS;
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Request inbox" });
    await expect(within(table).queryByRole("columnheader", { name: "Owner" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const popover = within(await within(document.body).findByRole("dialog"));
    await expect(popover.queryByRole("checkbox", { name: "Demand" })).not.toBeInTheDocument();
    await userEvent.click(popover.getByRole("checkbox", { name: "Owner" }));
    await expect(within(table).getByRole("columnheader", { name: "Owner" })).toBeInTheDocument();
  },
};

/** The Title header orders the inbox, ascending then descending. */
export const TitleHeaderSortsTheInbox: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      const route = path.split("?")[0];
      if (route.endsWith("/records/enhancement_request/columns")) return buildRecordColumns({ label: "Enhancement requests" });
      if (route.includes("/scoring-schemes/enhancement_request")) return buildRequestScheme();
      if (route.endsWith("/product_feedback/access")) return { can_submit: true, can_triage: false };
      if (route.endsWith("/modules/product_feedback/requests")) {
        return [
          buildRequest({ scope: "organization", project_id: null, organization_id: ORG_ID }),
          buildRequest({ id: "request-2", unique_code: "ENH-002", title: "Dark mode", scope: "organization", project_id: null, organization_id: ORG_ID }),
        ];
      }
      if (route.includes("/users")) return ORG_USERS;
      throw new Error(`Unmocked GET: ${path}`);
    });
  },
  play: async ({ canvasElement }) => {
    const table = await within(canvasElement).findByRole("table", { name: "Request inbox" });
    await expectHeaderOrdersText(table, "Title");
  },
};