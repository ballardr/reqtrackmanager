import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import type { ReportChapter } from "../api/types";
import { RichTextEditor } from "./RichTextEditor";
import { TextField } from "./FormFields";

/**
 * An ordered list of {title, body} report chapters — used identically for
 * a project's own "body chapters"/"appendices" (`ProjectAdminPage.tsx`)
 * and an organisation's default equivalents (`OrgAdminPage.tsx`), which is
 * why this is a shared component rather than duplicated per page. Each
 * chapter's body is a `RichTextEditor` (Markdown or WYSIWYG), matching
 * whatever mode the report intro next to it uses.
 */
export function ReportChapterListEditor({
  label,
  list,
  setList,
  organizationId,
}: {
  label: string;
  list: ReportChapter[];
  setList: (list: ReportChapter[]) => void;
  organizationId?: string;
}) {
  function move(index: number, direction: "up" | "down") {
    const swapIndex = direction === "up" ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= list.length) return;
    const next = [...list];
    [next[index], next[swapIndex]] = [next[swapIndex], next[index]];
    setList(next);
  }

  return (
    <div className="stack">
      <strong>{label}</strong>
      {list.map((chapter, idx) => (
        <div key={idx} className="card stack" style={{ gap: "0.4rem" }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-end" }}>
            <TextField
              label="Chapter title"
              placeholder="Chapter title"
              value={chapter.title}
              onChange={(title) => {
                const next = [...list];
                next[idx] = { ...next[idx], title };
                setList(next);
              }}
            />
            <div className="row" style={{ gap: "0.25rem" }}>
              <button
                className="btn"
                disabled={idx === 0}
                title="Move chapter up"
                aria-label="Move chapter up"
                onClick={() => move(idx, "up")}
              >
                <ArrowUp />
              </button>
              <button
                className="btn"
                disabled={idx === list.length - 1}
                title="Move chapter down"
                aria-label="Move chapter down"
                onClick={() => move(idx, "down")}
              >
                <ArrowDown />
              </button>
              <button
                className="btn btn-danger"
                title="Delete chapter"
                aria-label="Delete chapter"
                onClick={() => setList(list.filter((_, i) => i !== idx))}
              >
                <Trash2 />
              </button>
            </div>
          </div>
          <RichTextEditor
            rows={2}
            placeholder="Chapter body"
            value={chapter.body}
            organizationId={organizationId}
            onChange={(body) => {
              const next = [...list];
              next[idx] = { ...next[idx], body };
              setList(next);
            }}
          />
        </div>
      ))}
      <button className="btn" onClick={() => setList([...list, { title: "", body: "" }])} style={{ alignSelf: "flex-start" }}>
        <Plus /> Add chapter
      </button>
    </div>
  );
}
