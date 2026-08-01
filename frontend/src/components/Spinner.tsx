import { Loader2 } from "lucide-react";

/**
 * Loading indicator shown for any inherently slow task (U-P-01), so the
 * user always gets feedback that the system is processing their request.
 */
export function Spinner({ label }: { label?: string }) {
  return (
    <div className="row text-muted" role="status" aria-live="polite">
      <Loader2 className="spin" size={18} />
      <span>{label ?? "Loading…"}</span>
      <style>{`
        .spin { animation: reqtrack-spin 0.8s linear infinite; }
        @keyframes reqtrack-spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
