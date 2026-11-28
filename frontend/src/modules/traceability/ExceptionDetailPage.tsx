/**
 * Module: modules/traceability/ExceptionDetailPage
 *
 * One traceability exception as a routed page (`/projects/:projectId/modules/traceability/exceptions/:exceptionId`, the
 * path `module.ts` declares for `artefactPaths`): its record and rule, whether it covers the record today and why not,
 * the reason, the people, the dates and the decision, with the shared tags, activity, evidence and comments. There is no
 * Links panel: an exception takes no links, and names its record and rule itself.
 *
 * The exception itself is read only here: the page offers no creation, edit or approval control. Evidence of an approved
 * or archived exception is shown without the upload and remove controls.
 */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { DetailLayout } from "../../components/DetailLayout";
import { lifecycleSteps } from "../../components/lifecycleSteps";
import { MarkdownView } from "../../components/MarkdownView";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordActivity } from "../../components/RecordActivity";
import { recordActivityKey } from "../../components/recordActivityKey";
import { RecordField, RecordFieldGroup } from "../../components/RecordDetailParts";
import { RecordDiscussion } from "../../components/RecordDiscussion";
import { RecordHeader } from "../../components/RecordHeader";
import { RecordTags } from "../../components/RecordTags";
import { Spinner } from "../../components/Spinner";
import { useAuth } from "../../context/AuthContext";
import { toErrorMessage } from "../../context/ToastContext";
import { useApprovalStatus } from "../../hooks/useApprovalStatus";
import { getArtefactPath } from "../artefactPaths";
import { exceptionApi } from "./exceptionApi";
import { EXCEPTION_HELP } from "./help";
import { exceptionCoverLabel, EXCEPTION_STATUS_DESCRIPTION, EXCEPTION_STATUS_LABEL, EXCEPTION_STATUS_TONE } from "./types";
import type { ExceptionStatus, TraceabilityException } from "./types";

const MAIN_PATH: readonly ExceptionStatus[] = ["requested", "approved"];

export function ExceptionDetailPage() {
  const { projectId, exceptionId } = useParams<{ projectId: string; exceptionId: string }>();
  const { user } = useAuth();
  const [exception, setException] = useState<TraceabilityException | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const approval = useApprovalStatus(projectId ? { projectId } : null, "traceability_exception", exception?.id, exception?.status);

  useEffect(() => {
    if (!projectId || !exceptionId) return;
    let active = true;
    exceptionApi.get(projectId, exceptionId)
      .then((found) => active && setException(found))
      .catch((err) => active && setLoadError(toErrorMessage(err, "This exception could not be found, or you do not have access to it.")));
    return () => {
      active = false;
    };
  }, [projectId, exceptionId]);

  if (!projectId || !exceptionId) return null;
  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (exception === null) return <Spinner />;

  const recordPath = exception.record.removed ? null : getArtefactPath(exception.record.artefact_type, projectId, exception.record.id);
  const recordName = exception.record.code ? `${exception.record.code} ${exception.record.label}` : "Removed record";
  const approved = exception.status === "approved";
  const offPath = MAIN_PATH.includes(exception.status) ? undefined : {
    key: exception.status,
    label: EXCEPTION_STATUS_LABEL[exception.status],
    description: EXCEPTION_STATUS_DESCRIPTION[exception.status],
    after: exception.status === "revoked" ? "approved" : "requested",
  };

  return (
    <DetailLayout
      activity={<RecordActivity projectId={projectId} artefactType="traceability_exception" artefactId={exception.id} refreshToken={recordActivityKey(exception)} />}
    >
      <RecordHeader
        recordLabel="Traceability exception"
        title={exception.title}
        code={exception.unique_code}
        approval={approval.status}
        tags={<RecordTags projectId={projectId} artefactType="traceability_exception" artefactId={exception.id} />}
        back={{ to: `/projects/${projectId}/modules/traceability/exceptions`, label: "Traceability Exceptions" }}
        badges={
          <>
            {exception.rule_changed && <Badge tone="warning">Rule changed since approval</Badge>}
            {exception.is_archived && <Badge tone="muted">Archived</Badge>}
            <Badge tone={exception.covers ? "accent" : "muted"}>{exceptionCoverLabel(exception)}</Badge>
            <Badge tone={EXCEPTION_STATUS_TONE[exception.status]}>{EXCEPTION_STATUS_LABEL[exception.status]}</Badge>
          </>
        }
        subtitle={<>Rule: {exception.rule_name} · Requester: <PrincipalBadge principal={exception.requester} /></>}
        lifecycle={{
          steps: lifecycleSteps(MAIN_PATH, EXCEPTION_STATUS_LABEL, { descriptions: EXCEPTION_STATUS_DESCRIPTION }),
          current: exception.status,
          offPath,
        }}
      />

      <DetailCard>
        <RecordFieldGroup label="Record" help={EXCEPTION_HELP.record}>
          <span>
            {recordPath ? <Link to={recordPath}>{recordName}</Link> : recordName}
            {" "}<span className="text-muted">({exception.record.artefact_type_label})</span>
          </span>
        </RecordFieldGroup>
        <RecordFieldGroup label="Rule" help={EXCEPTION_HELP.rule}>
          <span>{exception.rule_name}</span>
          {exception.needs_organisation_approval && (
            <span className="text-muted">Enforced by the organisation: only an organisation-level approver may decide.</span>
          )}
        </RecordFieldGroup>
        <RecordFieldGroup label="Cover" help={EXCEPTION_HELP.cover}>
          <span>{exceptionCoverLabel(exception)}</span>
        </RecordFieldGroup>
        <RecordField markdown label="Reason" value={exception.reason} />
      </DetailCard>

      <DetailCard heading="People and dates">
        <RecordFieldGroup label="Requester" help={EXCEPTION_HELP.requester}>
          <PrincipalBadge principal={exception.requester} />
        </RecordFieldGroup>
        <RecordFieldGroup label="Nominated approver" help={EXCEPTION_HELP.approver}>
          <PrincipalBadge principal={exception.approver} />
        </RecordFieldGroup>
        <RecordFieldGroup label="Expiry date" help={EXCEPTION_HELP.expiresOn}>
          <span>{exception.expires_on ?? "No expiry"}</span>
        </RecordFieldGroup>
        <RecordFieldGroup label="Review date" help={EXCEPTION_HELP.reviewDate}>
          <span>{exception.review_date ?? "None scheduled"}</span>
        </RecordFieldGroup>
        {exception.decided_at && (
          <RecordFieldGroup label="Latest decision" helpNotNeeded>
            <span>
              {exception.decided_by_name ?? "Unknown user"}, {new Date(exception.decided_at).toLocaleString()}
            </span>
            {exception.decision_comment && <MarkdownView text={exception.decision_comment} />}
          </RecordFieldGroup>
        )}
      </DetailCard>

      <RecordDiscussion
        api={exceptionApi}
        scopeId={projectId}
        recordId={exception.id}
        noun="exception"
        currentUserId={user?.id}
        attachmentsReadOnly={approved || exception.is_archived}
        attachmentsHint={approved ? "This exception is approved; its evidence is fixed." : "This exception is archived."}
      />
    </DetailLayout>
  );
}
