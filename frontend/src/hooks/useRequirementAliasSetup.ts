/**
 * Module: hooks/useRequirementAliasSetup
 *
 * What a requirement's further-places surfaces need to know about a project: whether new aliases are allowed (the
 * project's effective setting) and the project's component and category tree to choose from. A failed read leaves
 * both `null`, so a surface offers nothing rather than a control the server would refuse.
 */
import { useEffect, useState } from "react";

import { requirementAliasesApi, type AliasSettings, type RequirementAliasesApi } from "../api/requirementAliases";
import { recordPlacementsApi, type PlacementTree, type RecordPlacementsApi } from "../api/placements";

/**
 * @param projectId The project.
 * @param api The alias calls (the live ones by default).
 * @param placementsApi Reads the tree (the live calls by default).
 * @returns The project's alias setting and tree, each `null` until read (or when the read failed).
 */
export function useRequirementAliasSetup(
  projectId: string, api: RequirementAliasesApi = requirementAliasesApi, placementsApi: RecordPlacementsApi = recordPlacementsApi,
): { settings: AliasSettings | null; tree: PlacementTree | null } {
  const [settings, setSettings] = useState<AliasSettings | null>(null);
  const [tree, setTree] = useState<PlacementTree | null>(null);
  useEffect(() => {
    let active = true;
    Promise.all([api.settings(projectId), placementsApi.tree(projectId)])
      .then(([loadedSettings, loadedTree]) => {
        if (active) {
          setSettings(loadedSettings);
          setTree(loadedTree);
        }
      })
      .catch(() => {
        if (active) {
          setSettings(null);
          setTree(null);
        }
      });
    return () => {
      active = false;
    };
  }, [api, placementsApi, projectId]);
  return { settings, tree };
}

/**
 * The tree without the category a requirement already sits in (its own place), and without any component left with
 * no category: the choices for its further places.
 *
 * @param tree The project's tree.
 * @param exclude Categories to leave out (the requirement's own and those it already holds).
 */
export function treeWithout(tree: PlacementTree, exclude: readonly string[]): PlacementTree {
  const categories = tree.categories.filter((category) => !exclude.includes(category.id));
  const usable = new Set(categories.map((category) => category.component_id));
  return { components: tree.components.filter((component) => usable.has(component.id)), categories };
}
