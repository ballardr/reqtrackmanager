/**
 * Module: components/PrincipalListField
 *
 * A "who" field that holds several people or groups (users, organisation groups, project groups: users
 * and groups on parity), such as an engagement's facilitators. It shows them as removable chips under
 * a heading with a (+) that opens the search in a `Popover`, the compact shape for a list
 * (docs/ux-style-guide.md, "Pattern: compact forms and add-on-demand"). The field is controlled: it
 * reports the whole new list through `onChange`, and the caller saves it. Adding someone already
 * listed does nothing, and removing needs no confirm because it changes a field, not a record.
 */
import type { OrgUser, Principal, PrincipalRef, PrincipalType } from "../api/types";
import { usePrincipalDirectory } from "../hooks/usePrincipalDirectory";
import { AddPopoverButton } from "./AddPopoverButton";
import { PrincipalBadge } from "./PrincipalBadge";
import { PrincipalSearch } from "./PrincipalPicker";
import { RecordFieldGroup } from "./RecordDetailParts";
import { RemovableItemList } from "./RemovableItemList";

const ALL_KINDS: readonly PrincipalType[] = ["user", "org_group", "project_group"];

/**
 * @param label Heading, e.g. "Facilitators"; the (+) is named "Add to <label>".
 * @param ariaLabel Accessible name of the search input.
 * @param values The current entries, resolved (the record's own `PrincipalOut`s).
 * @param emptyText Shown while the list is empty.
 * @param onChange Called with the whole new list.
 * @param readOnly Show the chips without the (+) or the "x".
 */
export function PrincipalListField({
  label, ariaLabel, values, orgUsers, organizationId, projectId, kinds = ALL_KINDS, emptyText = "Nobody yet.", readOnly = false, onChange,
}: {
  label: string;
  ariaLabel: string;
  values: Principal[];
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  kinds?: readonly PrincipalType[];
  emptyText?: string;
  readOnly?: boolean;
  onChange: (principals: PrincipalRef[]) => void;
}) {
  const { orgGroups, projectGroups } = usePrincipalDirectory(organizationId, projectId, kinds);
  const refs: PrincipalRef[] = values.map((v) => ({ type: v.type, id: v.id }));
  const key = (ref: PrincipalRef) => `${ref.type}:${ref.id}`;

  return (
    <RecordFieldGroup
      label={label}
      gap="0.35rem"
      action={
        !readOnly && (
          <AddPopoverButton label={`Add to ${label}`}>
            {(close) => (
              <PrincipalSearch
                orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} kinds={kinds}
                orgGroups={orgGroups} projectGroups={projectGroups} placeholder="Add…" ariaLabel={ariaLabel}
                onPick={(ref) => {
                  close();
                  if (!refs.some((r) => key(r) === key(ref))) onChange([...refs, ref]);
                }}
              />
            )}
          </AddPopoverButton>
        )
      }
    >
      {values.length === 0 ? (
        <span className="text-muted">{emptyText}</span>
      ) : (
        <RemovableItemList
          items={values.map((v) => ({ id: key(v), content: <PrincipalBadge principal={v} />, removeLabel: `Remove ${v.label}` }))}
          onRemove={readOnly ? undefined : (id) => onChange(refs.filter((r) => key(r) !== id))}
          noun={label.toLowerCase()}
          modalTitle={label}
        />
      )}
    </RecordFieldGroup>
  );
}
