import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildNeed, buildPersona } from "./fixtures";
import { NeedsPage } from "./NeedsPage";
import { PeoplePage } from "./PeoplePage";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;
const PEOPLE = "/projects/:projectId/modules/stakeholders/people";
const NEEDS = "/projects/:projectId/modules/stakeholders/needs";

function mockApis(disabled: string[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const [route] = path.split("?");
    if (route === `/api/v1/projects/${PROJECT_ID}/enabled-modules`) {
      return [{ module_key: "stakeholders", name: "Stakeholders & Personas", frontend_manifest: null, disabled_sub_components: disabled }];
    }
    if (route === `${BASE}/needs`) return [buildNeed()];
    if (route === `${BASE}/personas`) return [buildPersona()];
    if (route.endsWith("-types") || route === `${BASE}/stakeholders` || route === `${BASE}/stakeholder-groups`) return [];
    if (route === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return {};
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/** Shows where the router ended up. */
function Where() {
  const { pathname, search } = useLocation();
  return <p data-testid="where">{pathname + search}</p>;
}

/** Both pages and a marker, mounted at `start`, so a story can follow a redirect or a tab. */
function Harness({ start }: { start: string }) {
  return (
    <MemoryRouter initialEntries={[start]}>
      <Routes>
        <Route path={PEOPLE} element={<PeoplePage />} />
        <Route path={NEEDS} element={<NeedsPage />} />
      </Routes>
      <Where />
    </MemoryRouter>
  );
}

const meta: Meta<typeof Harness> = { title: "Modules/Stakeholders/PeopleAndNeedsTabs", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

const PEOPLE_PATH = `/projects/${PROJECT_ID}/modules/stakeholders/people`;
const NEEDS_PATH = `/projects/${PROJECT_ID}/modules/stakeholders/needs`;

/** The retired Need kind on People (an old bookmark) lands on the Needs tab. */
export const TheNeedKindOnPeopleRedirectsToNeeds: Story = {
  args: { start: `${PEOPLE_PATH}?kind=need` },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(NEEDS_PATH));
    await waitFor(() => expect(canvas.getByRole("table", { name: "Stakeholder Needs" })).toBeInTheDocument());
  },
};

/** The nav's People entry of a project with only Needs on lands on the Needs tab. */
export const PeopleWithOnlyNeedsOnRedirectsToNeeds: Story = {
  args: { start: PEOPLE_PATH },
  beforeEach: () => mockApis(["persona", "stakeholder"]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByTestId("where")).toHaveTextContent(NEEDS_PATH));
  },
};

/** The tabs move between the two pages in both directions. */
export const TheTabsNavigateBetweenThePages: Story = {
  args: { start: NEEDS_PATH },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("tab", { name: "People" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(PEOPLE_PATH));
    await userEvent.click(await canvas.findByRole("tab", { name: "Needs" }));
    await waitFor(() => expect(canvas.getByTestId("where")).toHaveTextContent(NEEDS_PATH));
  },
};
