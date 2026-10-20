import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization, OrgModuleEntitlement, ServerModuleDefault } from "../api/types";
import { buildUser, withAuth, withToast } from "../testing/storybook-helpers";
import { ServerModulesTab } from "./ServerModulesTab";

const DEFAULTS: ServerModuleDefault[] = [
  {
    module_key: "alpha", name: "Alpha module", description: "Does alpha things.",
    org_enabled: true, project_default_enabled: true, has_override: true,
  },
  {
    module_key: "beta", name: "Beta module", description: "Does beta things.",
    org_enabled: false, project_default_enabled: false, has_override: false,
  },
];

const ORG = {
  id: "org-1", name: "Acme Corp", code: "ACME",
} as Organization;

function orgModules(entitledBeta: boolean): OrgModuleEntitlement[] {
  return [
    {
      module_key: "alpha", name: "Alpha module", entitled: true, has_override: false, default_policy_used: true,
      enabled: true, default_project_enabled: true, enabled_source: "server_default",
    },
    {
      module_key: "beta", name: "Beta module", entitled: entitledBeta, has_override: !entitledBeta,
      default_policy_used: entitledBeta, enabled: false, default_project_enabled: false, enabled_source: "registry",
    },
  ];
}

function mockApis() {
  let entitledBeta = true;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/system/module-entitlement-policy") return { default_module_entitlement_policy: "open" };
    if (path === "/api/v1/system/module-defaults") return DEFAULTS;
    if (path === "/api/v1/orgs") return [ORG];
    if (path === "/api/v1/system/orgs/org-1/module-entitlements") return orgModules(entitledBeta);
    throw new Error(`unmocked path: ${path}`);
  });
  const put = spyOn(api, "put").mockImplementation(async (path: string, body?: unknown) => {
    if (path.startsWith("/api/v1/system/module-defaults/")) {
      const key = path.split("/").pop();
      return { ...DEFAULTS.find((d) => d.module_key === key), ...(body as object), has_override: true };
    }
    if (path.includes("/module-entitlements/")) {
      entitledBeta = (body as { entitled: boolean }).entitled;
      return {};
    }
    return {};
  });
  const post = spyOn(api, "post").mockResolvedValue({ organizations_changed: 2, rows_written: 3 });
  return { put, post };
}

const meta: Meta<typeof ServerModulesTab> = {
  title: "Pages/ServerModulesTab",
  component: ServerModulesTab,
  decorators: [withAuth(buildUser({ is_server_admin: true })), withToast()],
};
export default meta;

type Story = StoryObj<typeof ServerModulesTab>;

/** A default shows where it comes from, and changing one saves at once. */
export const ChangeADefault: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alpha module")).toBeInTheDocument());
    await expect(canvas.getByText("Built-in default, not yet set on this server.")).toBeInTheDocument();
    await expect(canvas.getByText("Set on this server.")).toBeInTheDocument();

    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Beta module default" }), "default_on");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith("/api/v1/system/module-defaults/beta", {
      org_enabled: true, project_default_enabled: true,
    }));
    await waitFor(() => expect(within(document.body).getByText("Beta module default saved.")).toBeInTheDocument());
  },
};

/** Applying the defaults overwrites other organisations' choices, so it needs the typed confirmation. */
export const ApplyToAllNeedsTypedConfirmation: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alpha module")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Apply to all organisations" }));
    const dialog = within(document.body).getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Apply to all" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByRole("textbox"), "Apply");
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/system/module-defaults/apply", {}));
    await waitFor(() => expect(within(document.body).getByText("Applied: 3 setting(s) changed across 2.")).toBeInTheDocument());
  },
};

/** Picking an organisation shows each module's effective state and which tier decided it. */
export const WithdrawAModuleFromAnOrganisation: Story = {
  beforeEach: () => {
    mockApis();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("combobox", { name: /^Organi[sz]ation$/ })).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: /^Organi[sz]ation$/ }), "org-1");
    await waitFor(() => expect(canvas.getByText(/Enabled \(server default\)/)).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("switch", { name: "Beta module available" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      "/api/v1/system/orgs/org-1/module-entitlements/beta", { entitled: false },
    ));
    await waitFor(() => expect(canvas.getByRole("switch", { name: "Beta module available" })).not.toBeChecked());
    await expect(within(document.body).getByText("Beta module withdrawn.")).toBeInTheDocument();
  },
};
