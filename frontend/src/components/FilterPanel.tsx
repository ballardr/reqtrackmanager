import type { ReactNode } from "react";

/** Right-side filter sidebar shell (mock's Search/Status/Category/Filters panel). */
export function FilterPanel({ children }: { children: ReactNode }) {
  return (
    <div className="card stack" style={{ alignSelf: "flex-start", minWidth: 220 }}>
      {children}
    </div>
  );
}

export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="stack" style={{ gap: "0.25rem" }}>
      <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

export function FilterCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="row" style={{ gap: "0.4rem" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
