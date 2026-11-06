/**
 * Module: modules/coreLinkedRecordCreators
 *
 * The "Create new" dialogs of the core record types (requirement, action, change request) for the Links panel. A
 * module declares its own types' dialogs on `TierAModuleDefinition.linkedRecordCreators`; core owns these three, so they
 * are listed here, which `modules/linkedRecordCreators` merges with the modules'. Each dialog is loaded on first use, so
 * the shared Links panel does not pull the three large forms into every page that shows it.
 */
import { createElement, lazy, Suspense } from "react";

import type { LinkedRecordCreator, LinkedRecordCreatorProps } from "./types";

const CreateRequirementDialog = lazy(() => import("../components/CreateRequirementDialog").then((m) => ({ default: m.CreateRequirementDialog })));
const CreateActionDialog = lazy(() => import("../components/CreateActionDialog").then((m) => ({ default: m.CreateActionDialog })));
const CreateChangeRequestDialog = lazy(() => import("../components/CreateChangeRequestDialog").then((m) => ({ default: m.CreateChangeRequestDialog })));

/** Renders a lazily loaded dialog; nothing shows while it loads. */
function loaded(Dialog: React.ComponentType<LinkedRecordCreatorProps>, props: LinkedRecordCreatorProps) {
  return createElement(Suspense, { fallback: null }, createElement(Dialog, props));
}

/** The core record types' creators, keyed by registered artefact type. */
export const CORE_LINKED_RECORD_CREATORS: Record<string, LinkedRecordCreator> = {
  requirement: { label: "Requirement", render: (props) => loaded(CreateRequirementDialog, props) },
  requirement_action: { label: "Action", render: (props) => loaded(CreateActionDialog, props) },
  change_request: { label: "Change Request", render: (props) => loaded(CreateChangeRequestDialog, props) },
};
