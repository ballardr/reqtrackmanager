/**
 * Module: components/OrganisationDetailsPanel
 *
 * The organisation's identity in Organisation administration: its logo, its name and the company details printed in
 * the footer of its outgoing email. These are not appearance settings, so they are saved apart from Branding &
 * defaults; the branding endpoint is a partial update, so neither page can overwrite the other's values.
 *
 * Responsibilities: the logo acts at once (upload, Remove); the name and the company details share one Save that
 * sends only the fields that changed (the name through the rename endpoint, the company details through the branding
 * endpoint). An empty company field uses the platform value, which is shown as its placeholder.
 *
 * Design decisions: the parent owns the organisation record and receives each updated copy through `onOrgChange`.
 */
import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { Organization, ServerSettings } from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { BrandingImageField } from "./BrandingImageField";
import { CompanyDetailsFields, type CompanyDetails } from "./CompanyDetailsFields";
import { FieldHelp } from "./FieldHelp";
import { TextField } from "./FormFields";
import { FormDivider, FormGrid } from "./FormGrid";
import { SettingsForm } from "./SettingsForm";

const strings = t();

/** The text of an input as the value to store: an empty field is "not set". */
function orNull(value: string): string | null {
  return value.trim() === "" ? null : value;
}

/** The company details an organisation record holds, as the text of the three fields. */
function detailsOf(org: Organization): CompanyDetails {
  return {
    companyName: org.email_footer_company_name ?? "",
    website: org.email_footer_website ?? "",
    address: org.email_footer_address ?? "",
  };
}

/**
 * @param org The organisation being edited.
 * @param platformBranding The platform values shown as placeholders, or null until loaded.
 * @param onOrgChange Receives the organisation as the server returns it after a change.
 */
export function OrganisationDetailsPanel({
  org, platformBranding, onOrgChange,
}: {
  org: Organization;
  platformBranding: ServerSettings | null;
  onOrgChange: (org: Organization) => void;
}) {
  const orgLabel = useOrgLabel();
  const { showToast } = useToast();
  const [name, setName] = useState(org.name);
  const [details, setDetails] = useState<CompanyDetails>(() => detailsOf(org));
  const [imageBusy, setImageBusy] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState(false);

  const savedDetails = detailsOf(org);
  const nameChanged = name.trim() !== org.name;
  const changedDetails = (Object.keys(details) as (keyof CompanyDetails)[]).filter((field) => details[field] !== savedDetails[field]);
  const dirty = nameChanged || changedDetails.length > 0;

  async function changeLogo(action: () => Promise<unknown>, onDone: () => void) {
    setImageError(null);
    setUploaded(false);
    setImageBusy(true);
    try {
      await action();
      onOrgChange(await api.get<Organization>(`/api/v1/orgs/${org.id}`));
      onDone();
    } catch (err) {
      setImageError(err instanceof ApiError ? err.message : strings.common.error);
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setImageBusy(false);
    }
  }

  /** Saves the name, then the company details, each only when it changed. */
  async function save() {
    let latest = org;
    if (nameChanged) latest = await api.put<Organization>(`/api/v1/orgs/${org.id}/name`, { name: name.trim() });
    if (changedDetails.length > 0) {
      latest = await api.put<Organization>(`/api/v1/orgs/${org.id}/branding`, {
        ...(changedDetails.includes("companyName") && { email_footer_company_name: orNull(details.companyName) }),
        ...(changedDetails.includes("website") && { email_footer_website: orNull(details.website) }),
        ...(changedDetails.includes("address") && { email_footer_address: orNull(details.address) }),
      });
    }
    onOrgChange(latest);
    setName(latest.name);
    setDetails(detailsOf(latest));
  }

  return (
    <div className="stack">
      <BrandingImageField
        id="org-logo-input"
        label={strings.orgAdmin.logo(orgLabel)}
        fileId={org.logo_file_id ?? null}
        platformFileId={platformBranding?.default_logo_file_id ?? null}
        busy={imageBusy}
        onSelect={(file) => changeLogo(
          () => api.postFile(`/api/v1/orgs/${org.id}/branding-image`, file, { kind: "logo" }), () => setUploaded(true),
        )}
        onRemove={() => changeLogo(
          () => api.delete(`/api/v1/orgs/${org.id}/branding-image?kind=logo`), () => showToast(strings.orgAdmin.logoRemoved),
        )}
        error={imageError}
        uploaded={uploaded ? strings.orgAdmin.logoUploaded : null}
        height={40}
      />
      <FormDivider />
      <SettingsForm dirty={dirty} onSave={save} successMessage={strings.orgAdmin.detailsSaved}>
        <FormGrid minColumn="18rem">
          <TextField
            required label={strings.orgAdmin.detailsName} help={strings.orgAdmin.detailsNameHelp(orgLabel)}
            value={name} onChange={setName} inputProps={{ id: "org-details-name" }}
          />
        </FormGrid>
        <span className="row" style={{ gap: "var(--space-2)" }}>
          <h4 style={{ margin: 0 }}>{strings.orgAdmin.emailFooterTitle}</h4>
          <FieldHelp label={strings.orgAdmin.emailFooterTitle} help={strings.orgAdmin.emailFooterHint(orgLabel)} />
        </span>
        <CompanyDetailsFields
          idPrefix="org-email-footer"
          value={details}
          onChange={(field, text) => setDetails((prev) => ({ ...prev, [field]: text }))}
          help={{
            companyName: strings.help.orgEmailFooterCompanyName,
            website: strings.help.orgEmailFooterWebsite,
            address: strings.help.orgEmailFooterAddress,
          }}
          placeholders={{
            companyName: platformBranding?.email_footer_company_name,
            website: platformBranding?.email_footer_website,
            address: platformBranding?.email_footer_address,
          }}
        />
      </SettingsForm>
    </div>
  );
}
