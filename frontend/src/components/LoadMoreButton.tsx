import { t } from "../i18n/strings";

const strings = t();

/** Shown under a paginated list (U-P-06) while more results remain to load. */
export function LoadMoreButton({
  loaded,
  total,
  onClick,
}: {
  loaded: number;
  total: number;
  onClick: () => void;
}) {
  if (loaded >= total) return null;
  return (
    <button className="btn" onClick={onClick} style={{ alignSelf: "center" }}>
      {strings.common.loadMore} ({loaded}/{total})
    </button>
  );
}
