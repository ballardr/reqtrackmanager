/**
 * Module: api/externalSystems
 *
 * The external systems (Jira, ServiceNow, ...) a record's references can name, at both tiers, in the shapes the shared
 * `TypeVocabularyPanels` and the reference pickers take. One list for every record type (`routers/external_systems.py`).
 */
import { orgVocabularyApi, projectVocabularyApi } from "./typeVocabulary";

export const externalSystemApi = {
  project: projectVocabularyApi((projectId) => `/api/v1/projects/${projectId}/external-systems`),
  org: orgVocabularyApi((organizationId) => `/api/v1/orgs/${organizationId}/external-systems`),
};
