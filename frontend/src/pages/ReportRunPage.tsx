/**
 * Module: pages/ReportRunPage
 *
 * `/report-runs/:runId`, where a background-report notification lands: it loads the person's own run and shows it
 * in `ReportRunDialog`. The page behind the dialog is empty; closing goes back to where the person came from, or to
 * the report's project or organisation overview when the link was opened directly.
 *
 * Design decisions: a run that is not the person's (or no longer listed) shows a short message instead of the dialog,
 * the same answer for both so a run id reveals nothing. The route is not module-specific: any notification whose
 * entity is a background report resolves here (`notificationLink`).
 */
import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { reportRunsApi, type ReportRun } from "../api/reports";
import { ReportRunDialog } from "../components/ReportRunDialog";
import { Spinner } from "../components/Spinner";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";

export function ReportRunPage() {
  const { runId = "" } = useParams();
  const strings = useStrings();
  const navigate = useNavigate();
  const location = useLocation();
  const [run, setRun] = useState<ReportRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    reportRunsApi
      .get(runId)
      .then((next) => !cancelled && setRun(next))
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError && err.status === 404 ? strings.reportRuns.notFound : toErrorMessage(err, strings.reportRuns.loadFailed));
      });
    return () => {
      cancelled = true;
    };
  }, [runId, strings]);

  function close() {
    if (location.key !== "default") navigate(-1);
    else if (run?.project_id) navigate(`/projects/${run.project_id}`, { replace: true });
    else if (run) navigate(`/orgs/${run.organization_id}/overview`, { replace: true });
    else navigate("/projects", { replace: true });
  }

  if (error) {
    return (
      <div className="stack">
        <p role="alert">{error}</p>
        <button className="btn" onClick={close}>{strings.common.close}</button>
      </div>
    );
  }
  return run ? <ReportRunDialog initial={run} onClose={close} /> : <Spinner />;
}
