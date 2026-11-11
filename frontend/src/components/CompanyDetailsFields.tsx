/**
 * Module: components/CompanyDetailsFields
 *
 * The company details printed in the footer of outgoing email: company name, website and postal address. The
 * platform page (Server details) and an organisation's own page (Organisation details) draw the same fields, so a
 * field added here reaches both. Each tier supplies its own help text and placeholders, and the platform tier adds
 * its prefix and company identifier through `leading` and `trailing`.
 */
import type { ReactNode } from "react";

import { t } from "../i18n/strings";
import { FormGrid, FormGridFull } from "./FormGrid";
import { TextAreaField, TextField } from "./FormFields";

const strings = t();

/** The three values the fields edit. */
export interface CompanyDetails {
  companyName: string;
  website: string;
  address: string;
}

/**
 * @param value The current text of each field.
 * @param onChange Called with the new text of one field.
 * @param help The help text of each field (it differs by tier: what an empty field falls back to).
 * @param placeholders The value an empty field falls back to, shown as its placeholder.
 * @param leading Fields placed before the company name (a platform-only prefix).
 * @param trailing Fields placed after the postal address (platform-only company identifier).
 * @param idPrefix Prefix of the inputs' ids, so a page showing two groups keeps them distinct.
 */
export function CompanyDetailsFields({
  value, onChange, help, placeholders, leading, trailing, idPrefix = "company",
}: {
  value: CompanyDetails;
  onChange: (field: keyof CompanyDetails, text: string) => void;
  help: Record<keyof CompanyDetails, string>;
  placeholders?: Partial<Record<keyof CompanyDetails, string | null | undefined>>;
  leading?: ReactNode;
  trailing?: ReactNode;
  idPrefix?: string;
}) {
  return (
    <FormGrid minColumn="18rem">
      {leading}
      <TextField
        help={help.companyName} label={strings.companyDetails.companyName}
        placeholder={placeholders?.companyName ?? undefined}
        value={value.companyName} onChange={(text) => onChange("companyName", text)}
        inputProps={{ id: `${idPrefix}-name` }}
      />
      <TextField
        help={help.website} label={strings.companyDetails.website}
        placeholder={placeholders?.website ?? undefined}
        value={value.website} onChange={(text) => onChange("website", text)}
        inputProps={{ id: `${idPrefix}-website` }}
      />
      <FormGridFull>
        <TextAreaField
          help={help.address} label={strings.companyDetails.address} rows={3}
          value={value.address} onChange={(text) => onChange("address", text)}
          inputProps={{ id: `${idPrefix}-address`, placeholder: placeholders?.address ?? undefined }}
        />
      </FormGridFull>
      {trailing}
    </FormGrid>
  );
}
