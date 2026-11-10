/**
 * Module: components/PeriodFilter
 *
 * The time-range filter of a filter panel: a preset (Today, Last 7 days, Last 30 days) or a custom range, with the
 * two date-time inputs shown only for the custom range. One component so every list that narrows by time offers
 * the same presets, the same help and the same inputs. Presentational: the caller owns the three values (in the
 * URL, for a list) and turns them into instants with `utils/historyPeriod`.
 */
import { t } from "../i18n/strings";
import { PERIOD_KEYS, type PeriodKey } from "../utils/historyPeriod";
import { FilterField } from "./FilterPanel";
import { FilterSelect } from "./FilterSelect";

const strings = t();

const PERIOD_LABEL: Record<PeriodKey, string> = {
  today: strings.history.periodToday,
  week: strings.history.periodWeek,
  month: strings.history.periodMonth,
  custom: strings.history.periodCustom,
};

/**
 * @param period The chosen preset, `custom`, or `""` for any time.
 * @param since / until The custom range's `datetime-local` values.
 * @param onPeriod / onSince / onUntil Called with the new value.
 */
export function PeriodFilter({
  period, since, until, onPeriod, onSince, onUntil,
}: {
  period: PeriodKey | "";
  since: string;
  until: string;
  onPeriod: (period: PeriodKey | "") => void;
  onSince: (value: string) => void;
  onUntil: (value: string) => void;
}) {
  return (
    <>
      <FilterSelect
        label={strings.history.period} help={strings.history.help.period} value={period} onChange={onPeriod}
        allLabel={strings.history.periodAny} options={PERIOD_KEYS.map((value) => ({ value, label: PERIOD_LABEL[value] }))}
      />
      {period === "custom" && (
        <>
          <FilterField label={strings.history.since}>
            <input type="datetime-local" className="input" value={since} onChange={(e) => onSince(e.target.value)} />
          </FilterField>
          <FilterField label={strings.history.until}>
            <input type="datetime-local" className="input" value={until} onChange={(e) => onUntil(e.target.value)} />
          </FilterField>
        </>
      )}
    </>
  );
}
