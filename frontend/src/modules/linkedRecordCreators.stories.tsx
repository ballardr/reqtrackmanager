import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {
  buildActionType, buildCategory, buildComponent, buildProject, buildRequirement, buildScoringScheme, buildStage, buildUser,
  withRouter, withStatefulAuth, withToast,
} from "../testing/storybook-helpers";
import { buildOption } from "../testing/artefactLinksFixtures";
import creatableRecordTypes from "./creatableRecordTypes.json";
import { getLinkedRecordCreator } from "./linkedRecordCreators";

/**
 * Guards for the Links panel's "Create new": every registered type a person can author has a creator, a type that cannot
 * be authored has none, and each creator opens the type's own create form with the quick-link and tag fields and a
 * header holding Create or Save. `creatableRecordTypes.json` is kept equal to the backend registry by
 * `backend/tests/test_creatable_record_types.py`, so a new type fails there until it is listed and here until it
 * declares a creator in its module's `linkedRecordCreators`.
 */
const meta: Meta = {
  title: "Modules/LinkedRecordCreators",
  decorators: [withToast(), withRouter("/"), withStatefulAuth(buildUser())],
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/my-roles")) return { roles: ["project_manager"] } as never;
      if (path.includes("/tags")) return { names: [], suggestions: [], restricted: false, can_edit: true } as never;
      if (path.includes("/scoring-schemes/")) return buildScoringScheme() as never;
      if (path.includes("/link-types")) return [buildOption()] as never;
      if (/\/projects\/[^/]+$/.test(path)) return buildProject({ id: "p-1", organization_id: "org-1" }) as never;
      if (path.endsWith("/components")) return [buildComponent({ id: "c-1", name: "Core", prefix: "CORE" })] as never;
      if (path.endsWith("/categories")) return [buildCategory({ id: "k-1", component_id: "c-1", name: "General", prefix: "GEN" })] as never;
      if (path.endsWith("/stages")) return [buildStage({ id: "s-1", name: "Version 1" })] as never;
      if (path.endsWith("/action-types")) return [buildActionType({ id: "at-1", name: "Review" })] as never;
      if (path.endsWith("/requirements")) return [buildRequirement({ id: "r-1", is_locked: true })] as never;
      return [] as never;
    });
  },
};
export default meta;

type Story = StoryObj;

export const EveryCreatableTypeHasACreatorAndOthersHaveNone: Story = {
  render: () => <div>Creators</div>,
  play: async () => {
    const missing = creatableRecordTypes.creatable.filter((type) => getLinkedRecordCreator(type) === null);
    await expect(missing).toEqual([]);
    const surplus = creatableRecordTypes.notCreatable.filter((type) => getLinkedRecordCreator(type) !== null);
    await expect(surplus).toEqual([]);
  },
};

/** Renders the creator of `type` and checks the form it opens. `links` is false for the Change Request form, which has no
 * quick-link field: it proposes its links with the request (they are created only if the approver merges them). */
function opensItsCreateForm(type: string, links = true): Story {
  return {
    render: () => {
      const creator = getLinkedRecordCreator(type);
      if (!creator) return <div>No creator for {type}</div>;
      return <>{creator.render({ projectId: "p-1", pageRecord: { type: "requirement", id: "r-1" }, onCreated: fn(), onCancel: fn() })}</>;
    },
    play: async () => {
      const dialog = within(await within(document.body).findByRole("dialog", {}, { timeout: 5000 }));
      if (links) {
        await waitFor(() => expect(dialog.getByText("Link to")).toBeInTheDocument());
      } else {
        await waitFor(() => expect(dialog.getByLabelText("Reason for change")).toBeInTheDocument());
        await expect(dialog.queryByText("Link to")).not.toBeInTheDocument();
      }
      await expect(dialog.getByText("Tags")).toBeInTheDocument();
      // The header holds the form's primary action: Create, or Save.
      await expect(dialog.getByRole("button", { name: /^(Create|Save)$/ })).toBeInTheDocument();
    },
  };
}

export const Requirement: Story = opensItsCreateForm("requirement");
export const Action: Story = opensItsCreateForm("requirement_action");
export const ChangeRequest: Story = opensItsCreateForm("change_request", false);
export const Decision: Story = opensItsCreateForm("decision");
export const Risk: Story = opensItsCreateForm("risk");
export const PainPoint: Story = opensItsCreateForm("pain_point");
export const Strategy: Story = opensItsCreateForm("strategy");
export const FutureState: Story = opensItsCreateForm("future_state");
export const GuidingPrinciple: Story = opensItsCreateForm("guiding_principle");
export const OpenQuestion: Story = opensItsCreateForm("open_question");
export const Persona: Story = opensItsCreateForm("persona");
export const Stakeholder: Story = opensItsCreateForm("stakeholder");
export const StakeholderGroup: Story = opensItsCreateForm("stakeholder_group");
export const StakeholderNeed: Story = opensItsCreateForm("stakeholder_need");
export const Engagement: Story = opensItsCreateForm("engagement");
export const ResearchFinding: Story = opensItsCreateForm("research_finding");
export const EnhancementRequest: Story = opensItsCreateForm("enhancement_request");
export const ComplianceEvidence: Story = opensItsCreateForm("compliance_evidence");
