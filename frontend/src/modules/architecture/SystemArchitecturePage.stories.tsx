import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { Route, Routes, useLocation } from "react-router-dom";

import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildConnection, buildDiagram, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { ArchitectureListRedirect, SystemArchitecturePage } from "./SystemArchitecturePage";

const PATH = "/projects/:projectId/modules/architecture";

/** Shows the address so a story can assert which tab and filters it holds. */
function Address() {
  const { pathname, search } = useLocation();
  return <p data-testid="address">{`${pathname}${search}`}</p>;
}

const meta: Meta<typeof SystemArchitecturePage> = {
  title: "Modules/Architecture/SystemArchitecturePage",
  component: SystemArchitecturePage,
  decorators: [
    withAuth(buildUser({ id: "user-1" })),
    withToast(),
  ],
  beforeEach: () => { sessionStorage.clear(); localStorage.clear(); },
  render: () => (
    <>
      <Address />
      <Routes>
        <Route path={PATH} element={<SystemArchitecturePage />} />
        <Route path={`${PATH}/elements`} element={<ArchitectureListRedirect tab="elements" />} />
        <Route path={`${PATH}/diagrams`} element={<ArchitectureListRedirect tab="diagrams" />} />
      </Routes>
    </>
  ),
};
export default meta;

type Story = StoryObj<typeof SystemArchitecturePage>;

export const OpensOnDiagramsAndNamesTheTabInTheAddress: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture`, "*")],
  beforeEach: () => { mockArchitectureReads(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("heading", { level: 1, name: "System Architecture" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Diagrams", selected: true })).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByTestId("address")).toHaveTextContent(`${PATH.replace(":projectId", PROJECT_ID)}?tab=diagrams`));
  },
};

export const OpensOnTheTabLastChosenOnTheStrip: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture?tab=diagrams`, "*")],
  beforeEach: () => { mockArchitectureReads(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "Connections" }));
    await expect(localStorage.getItem("architecture-last-tab")).toBe("connections");
  },
};

export const ARememberedTabOpensWithoutATabInTheAddress: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture`, "*")],
  beforeEach: () => { localStorage.setItem("architecture-last-tab", "connections"); mockArchitectureReads(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("tab", { name: "Connections", selected: true })).toBeInTheDocument();
    await expect(canvas.getByTestId("address")).toHaveTextContent("tab=connections");
  },
};

export const ALinkNamingATabDoesNotChangeTheRememberedTab: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture?tab=elements`, "*")],
  beforeEach: () => { localStorage.setItem("architecture-last-tab", "connections"); mockArchitectureReads(); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("tab", { name: "Elements", selected: true })).toBeInTheDocument();
    await expect(localStorage.getItem("architecture-last-tab")).toBe("connections");
  },
};

export const SwitchingTabsShowsEachListAndKeepsItsFilters: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture?tab=connections&q=client`, "*")],
  beforeEach: () => { mockArchitectureReads({ connections: [buildConnection()], diagrams: [buildDiagram()] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Connections" });
    await userEvent.click(canvas.getByRole("tab", { name: "Diagrams" }));
    await canvas.findByRole("table", { name: "Diagrams" });
    await expect(canvas.getByTestId("address")).toHaveTextContent("tab=diagrams");
    await userEvent.click(canvas.getByRole("tab", { name: "Connections" }));
    await canvas.findByRole("table", { name: "Connections" });
    await expect(canvas.getByTestId("address")).toHaveTextContent("tab=connections&q=client");
  },
};

export const ATabForADisabledSubComponentIsNotOffered: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture?tab=diagrams`, "*")],
  beforeEach: () => { mockArchitectureReads({ disabledSubComponents: ["architecture_diagram"] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.queryByRole("tab", { name: "Diagrams" })).not.toBeInTheDocument());
    await expect(await canvas.findByRole("tab", { name: "Elements", selected: true })).toBeInTheDocument();
    await expect(canvas.getByTestId("address")).toHaveTextContent("tab=elements");
  },
};

export const AnEarlierListAddressRedirectsToItsTab: Story = {
  decorators: [withRouter(`/projects/${PROJECT_ID}/modules/architecture/diagrams?status=active`, "*")],
  beforeEach: () => { mockArchitectureReads({ diagrams: [buildDiagram()] }); },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Diagrams" });
    await expect(canvas.getByTestId("address")).toHaveTextContent(`${PATH.replace(":projectId", PROJECT_ID)}?status=active&tab=diagrams`);
  },
};
