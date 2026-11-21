/**
 * Module: components/NameAndPrefixFields
 *
 * The name and identifier prefix of a component or category: one field group for the Structure page's create and
 * edit form and for the first-component and first-category form of the requirement create dialog, so a field added
 * later reaches both.
 *
 * Responsibilities:
 * - Show the two required fields with their help.
 * - Fill the prefix from the server's suggestion for the name while the person has not typed one, and stop following
 *   it once they do (a typed prefix is never overwritten). Clearing the prefix resumes following.
 *
 * Design decisions: the rule is the server's (`usePrefixSuggestion`); the fields only display its answer. The group
 * is controlled: the caller owns the values and decides when they are valid.
 */
import { useEffect, useState } from "react";

import type { NodeValues, StructureApi, StructureKind } from "../api/structure";
import { useStrings } from "../context/TerminologyContext";
import { usePrefixSuggestion } from "../hooks/usePrefixSuggestion";
import { TextField } from "./FormFields";

/** The longest prefix the server stores. */
export const MAX_PREFIX_LENGTH = 20;
/** The longest name the server stores. */
export const MAX_NAME_LENGTH = 255;

/**
 * @param api The structure calls (the suggestion).
 * @param projectId The project the tree belongs to.
 * @param kind Whether the node is a component or a category.
 * @param componentId The component a new category goes under.
 * @param ignore The node being edited, whose own prefix is not a collision.
 * @param value The name and prefix.
 * @param onChange Called with the new values.
 * @param followName Whether the prefix follows the name from the start (a new node); an edit starts with the stored
 *   prefix and keeps it until the person clears it.
 */
export function NameAndPrefixFields({
  api, projectId, kind, componentId, ignore, value, onChange, followName,
}: {
  api: StructureApi;
  projectId: string;
  kind: StructureKind;
  componentId?: string;
  ignore?: string;
  value: NodeValues;
  onChange: (next: NodeValues) => void;
  followName: boolean;
}) {
  const strings = useStrings();
  const [typed, setTyped] = useState(!followName);
  const following = !typed || value.prefix === "";
  const suggestion = usePrefixSuggestion(
    api, projectId, following ? { kind, name: value.name, componentId, ignore } : null,
  );
  // Apply an answer only for the name now typed; an answer for an earlier name is stale.
  const answered = following && suggestion !== null && suggestion.name === value.name ? suggestion.prefix : null;
  useEffect(() => {
    if (answered !== null && answered !== value.prefix) onChange({ name: value.name, prefix: answered });
  }, [answered, value.prefix, value.name, onChange]);

  return (
    <>
      <TextField
        label={strings.admin.name} required helpNotNeeded value={value.name} inputProps={{ maxLength: MAX_NAME_LENGTH }}
        onChange={(name) => onChange({ ...value, name })}
      />
      <TextField
        label={strings.admin.prefix} required help={strings.help.requirementPrefix} value={value.prefix}
        inputProps={{ maxLength: MAX_PREFIX_LENGTH, autoCapitalize: "characters" }}
        onChange={(next) => {
          setTyped(next !== "");
          onChange({ ...value, prefix: next.toUpperCase() });
        }}
      />
    </>
  );
}
