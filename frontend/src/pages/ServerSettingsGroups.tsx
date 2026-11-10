/**
 * Module: pages/ServerSettingsGroups
 *
 * The small deployment-wide settings groups of Server Management: Server details, Platform branding, Public sign-up,
 * File uploads and Email. Each is one headed card; a group of fields has one Save (`SettingsForm`: unavailable until a
 * change, a toast on success, a failure beside the button), and the two pictures and the test email act at once.
 *
 * Responsibilities: read the current value, hold the edits, and send only this group's fields (the branding update is
 * partial, so Server details and Platform branding cannot overwrite each other). A change to branding or to the upload
 * switch tells the application shell to read the public settings again.
 *
 * Design decisions: an empty text field means "use the built-in value" (null on the server); the built-in value is
 * the placeholder. The platform pictures are platform-owned and removable (`BrandingImageField`), the same control as an
 * organisation's.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { ServerSettings, SignupConfig, SignupMode } from "../api/types";
import { BrandingImageField } from "../components/BrandingImageField";
import { CollapsibleSection } from "../components/CollapsibleSection";
import { FieldHelp } from "../components/FieldHelp";
import { ColorField, TextAreaField, TextField, ToggleField } from "../components/FormFields";
import { FormDivider, FormGrid, FormGridFull } from "../components/FormGrid";
import { LabeledSelect } from "../components/LabeledSelect";
import { SettingsForm } from "../components/SettingsForm";
import { Spinner } from "../components/Spinner";
import { StorageLimitField } from "../components/StorageLimitField";
import { useOrgLabel } from "../context/BrandingContext";
import { BRANDING_CHANGED_EVENT } from "../context/brandingEvents";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { t } from "../i18n/strings";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { joinStorageLimit, splitStorageLimit, type StorageUnit } from "../utils/storageLimit";

const strings = t();

/** Tells the application shell (header title, logo, colour, upload controls) to read the public settings again. */
function announceBrandingChange() {
  window.dispatchEvent(new Event(BRANDING_CHANGED_EVENT));
}

/** The text of an input as the value to store: an empty field is "not set". */
function orNull(value: string): string | null {
  return value.trim() === "" ? null : value;
}

/**
 * The state of one platform picture (logo or login background): upload and removal act at once and end in a toast.
 *
 * @param kind Which picture.
 * @param onSettings Receives the platform settings the server returns after the change.
 * @param uploadedMessage Toast after an upload.
 * @param removedMessage Toast after a removal.
 * @returns Whether a request is running, the last failure, and the two handlers.
 */
function usePlatformImage(
  kind: "logo" | "login_background", onSettings: (settings: ServerSettings) => void, uploadedMessage: string, removedMessage: string,
) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<ServerSettings>, message: string) {
    setError(null);
    setBusy(true);
    try {
      onSettings(await action());
      announceBrandingChange();
      showToast(message);
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
    } finally {
      setBusy(false);
    }
  }

  return {
    busy,
    error,
    upload: (file: File) => run(() => api.postFile<ServerSettings>("/api/v1/system/branding/image", file, { kind }), uploadedMessage),
    remove: () => run(() => api.delete<ServerSettings>(`/api/v1/system/branding/image?kind=${kind}`), removedMessage),
  };
}

/**
 * Server details: the platform logo and the company details printed in the footer of outgoing email. An organisation
 * that has not set its own shows these (the organisation's own page splits the same way).
 */
export function ServerDetailsTab() {
  const orgLabel = useOrgLabel();
  const [settings, setSettings] = useState<ServerSettings | null>(null);
  const [saved, setSaved] = useState<Pick<ServerSettings, "email_footer_company_name" | "email_footer_website" | "email_footer_address"> | null>(null);
  const [company, setCompany] = useState("");
  const [website, setWebsite] = useState("");
  const [address, setAddress] = useState("");
  const logo = usePlatformImage("logo", setSettings, strings.serverSettings.logoUploaded, strings.serverSettings.logoRemoved);

  function adopt(s: ServerSettings) {
    setSaved({ email_footer_company_name: s.email_footer_company_name, email_footer_website: s.email_footer_website, email_footer_address: s.email_footer_address });
    setCompany(s.email_footer_company_name ?? "");
    setWebsite(s.email_footer_website ?? "");
    setAddress(s.email_footer_address ?? "");
  }

  useLoadOnChange(async () => {
    const s = await api.get<ServerSettings>("/api/v1/system/branding");
    setSettings(s);
    adopt(s);
  }, []);

  if (!settings || !saved) return <Spinner />;
  const dirty =
    company !== (saved.email_footer_company_name ?? "") || website !== (saved.email_footer_website ?? "") || address !== (saved.email_footer_address ?? "");

  async function save() {
    const updated = await api.put<ServerSettings>("/api/v1/system/branding", {
      email_footer_company_name: orNull(company),
      email_footer_website: orNull(website),
      email_footer_address: orNull(address),
    });
    setSettings((prev) => (prev ? { ...prev, ...updated } : updated));
    adopt(updated);
    announceBrandingChange();
  }

  return (
    <CollapsibleSection sectionKey="serverManagement.details" title={strings.serverSettings.detailsTitle} help={strings.serverSettings.detailsHint(orgLabel)} collapsible={false}>
      <BrandingImageField
        id="platform-logo-input"
        label={strings.serverSettings.logo}
        fileId={settings.default_logo_file_id}
        platformFileId={null}
        busy={logo.busy}
        onSelect={logo.upload}
        onRemove={logo.remove}
        error={logo.error}
        height={40}
      />
      <FormDivider />
      <span className="row" style={{ gap: "var(--space-2)" }}>
        <h3 style={{ margin: 0 }}>{strings.serverSettings.emailFooterTitle}</h3>
        <FieldHelp label={strings.serverSettings.emailFooterTitle} help={strings.serverSettings.emailFooterHint(orgLabel)} />
      </span>
      <SettingsForm dirty={dirty} onSave={save} successMessage={strings.serverSettings.detailsSaved}>
        <FormGrid minColumn="18rem">
          <TextField
            help={strings.help.serverEmailFooterCompanyName} label={strings.serverSettings.emailFooterCompanyName}
            value={company} onChange={setCompany} placeholder={strings.appName}
          />
          <TextField help={strings.help.serverEmailFooterWebsite} label={strings.serverSettings.emailFooterWebsite} value={website} onChange={setWebsite} />
          <FormGridFull>
            <TextAreaField help={strings.help.serverEmailFooterAddress} label={strings.serverSettings.emailFooterAddress} value={address} onChange={setAddress} rows={3} />
          </FormGridFull>
        </FormGrid>
      </SettingsForm>
    </CollapsibleSection>
  );
}

/**
 * Platform branding: header title, the word used for an organisation, accent colour and the login page background.
 * An organisation that has not set its own value shows these.
 */
export function PlatformBrandingTab() {
  const orgLabel = useOrgLabel();
  const [settings, setSettings] = useState<ServerSettings | null>(null);
  const [saved, setSaved] = useState<Pick<ServerSettings, "default_header_title" | "org_label_singular" | "org_label_plural" | "accent_color_hex"> | null>(null);
  const [headerTitle, setHeaderTitle] = useState("");
  const [singular, setSingular] = useState("");
  const [plural, setPlural] = useState("");
  const [accent, setAccent] = useState("#475569");
  const background = usePlatformImage(
    "login_background", setSettings, strings.serverSettings.loginBackgroundUploaded, strings.serverSettings.loginBackgroundRemoved,
  );

  function adopt(s: ServerSettings) {
    setSaved({ default_header_title: s.default_header_title, org_label_singular: s.org_label_singular, org_label_plural: s.org_label_plural, accent_color_hex: s.accent_color_hex });
    setHeaderTitle(s.default_header_title ?? "");
    setSingular(s.org_label_singular ?? "");
    setPlural(s.org_label_plural ?? "");
    setAccent(s.accent_color_hex);
  }

  useLoadOnChange(async () => {
    const s = await api.get<ServerSettings>("/api/v1/system/branding");
    setSettings(s);
    adopt(s);
  }, []);

  if (!settings || !saved) return <Spinner />;
  const dirty =
    headerTitle !== (saved.default_header_title ?? "") || singular !== (saved.org_label_singular ?? "") ||
    plural !== (saved.org_label_plural ?? "") || accent !== saved.accent_color_hex;

  async function save() {
    const updated = await api.put<ServerSettings>("/api/v1/system/branding", {
      default_header_title: orNull(headerTitle),
      org_label_singular: orNull(singular),
      org_label_plural: orNull(plural),
      accent_color_hex: accent,
    });
    setSettings((prev) => (prev ? { ...prev, ...updated } : updated));
    adopt(updated);
    announceBrandingChange();
  }

  return (
    <CollapsibleSection sectionKey="serverManagement.branding" title={strings.serverSettings.title} help={strings.serverSettings.hint(orgLabel)} collapsible={false}>
      <BrandingImageField
        id="platform-login-background-input"
        label={strings.serverSettings.loginBackground}
        fileId={settings.default_login_background_file_id}
        platformFileId={null}
        busy={background.busy}
        onSelect={background.upload}
        onRemove={background.remove}
        error={background.error}
        height={100}
      />
      <SettingsForm dirty={dirty} onSave={save} successMessage={strings.serverSettings.brandingSaved}>
        <FormGrid minColumn="18rem">
          <TextField help={strings.help.serverHeaderTitle} label={strings.serverSettings.headerTitle} value={headerTitle} onChange={setHeaderTitle} placeholder={strings.appName} />
        </FormGrid>
        <ColorField help={strings.help.serverAccentColor} label={strings.serverSettings.accentColor} value={accent} onChange={setAccent} />
        <h3 style={{ margin: 0 }}>{strings.serverSettings.terminologyTitle}</h3>
        <FormGrid minColumn="18rem">
          <TextField
            help={strings.help.serverOrgLabelSingular} label={strings.serverSettings.orgLabelSingular}
            value={singular} onChange={setSingular} placeholder={strings.serverSettings.orgLabelSingularDefault}
          />
          <TextField
            help={strings.help.serverOrgLabelPlural} label={strings.serverSettings.orgLabelPlural}
            value={plural} onChange={setPlural} placeholder={strings.serverSettings.orgLabelPluralDefault}
          />
        </FormGrid>
      </SettingsForm>
    </CollapsibleSection>
  );
}

/** Email: a test message through the deployment's mail settings, to confirm outgoing mail works. */
export function TestEmailTab() {
  const { showToast } = useToast();
  const [recipient, setRecipient] = useState("");
  const [sending, setSending] = useState(false);

  async function send() {
    setSending(true);
    try {
      await api.post("/api/v1/system/test-email", recipient ? { to_email: recipient } : {});
      showToast(strings.system.testEmailSent);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    } finally {
      setSending(false);
    }
  }

  return (
    <CollapsibleSection sectionKey="serverManagement.email" title={strings.system.emailTab} help={strings.system.testEmailHint} collapsible={false}>
      <div className="row" style={{ alignItems: "flex-end" }}>
        <TextField
          help={strings.help.testEmailRecipient} label={strings.system.testEmailRecipient}
          value={recipient} onChange={setRecipient} inputProps={{ type: "email" }}
        />
        <button className="btn btn-primary" onClick={send} disabled={sending}>
          {sending ? strings.system.testEmailSending : strings.system.testEmail}
        </button>
      </div>
    </CollapsibleSection>
  );
}

/** Public sign-up: whether people can create their own account, with its own Save because it changes who may join. */
export function SignupModeTab() {
  const orgLabel = useOrgLabel();
  const [saved, setSaved] = useState<SignupMode | null>(null);
  const [mode, setMode] = useState<SignupMode>("disabled");

  useLoadOnChange(async () => {
    const c = await api.get<SignupConfig>("/api/v1/system/signup-config");
    setSaved(c.signup_mode);
    setMode(c.signup_mode);
  }, []);

  if (saved === null) return <Spinner />;

  async function save() {
    const c = await api.put<SignupConfig>("/api/v1/system/signup-config", { signup_mode: mode });
    setSaved(c.signup_mode);
  }

  return (
    <CollapsibleSection sectionKey="serverManagement.signup" title={strings.signupSettings.title} help={strings.signupSettings.hint} collapsible={false}>
      <SettingsForm dirty={mode !== saved} onSave={save} successMessage={strings.signupSettings.saved}>
        <LabeledSelect
          help={strings.help.signupMode}
          label={strings.signupSettings.mode}
          value={mode}
          onChange={(next) => setMode(next as SignupMode)}
          options={[
            { value: "disabled", label: strings.signupSettings.modeDisabled },
            { value: "always_on", label: strings.signupSettings.modeAlwaysOn(orgLabel) },
            { value: "org_specified", label: strings.signupSettings.modeOrgSpecified(orgLabel) },
          ]}
          placeholder={null}
        />
      </SettingsForm>
    </CollapsibleSection>
  );
}

/**
 * The deployment-wide file upload switch and the default storage limit of organisations that have none of their own.
 * Off stops new files only; existing files stay readable and deletable (`services.files.assert_uploads_allowed`).
 * The value is read from the public branding read every page already makes, and the shell is told to read it again
 * after a save.
 */
export function FileUploadsTab() {
  const [saved, setSaved] = useState<{ enabled: boolean; amount: string; unit: StorageUnit } | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [limitAmount, setLimitAmount] = useState("");
  const [limitUnit, setLimitUnit] = useState<StorageUnit>("GB");

  useLoadOnChange(async () => {
    const [settings, defaults] = await Promise.all([
      api.get<ServerSettings>("/api/v1/system/branding"),
      api.get<{ default_storage_quota_bytes: number | null }>("/api/v1/system/default-storage-quota"),
    ]);
    const parts = splitStorageLimit(defaults.default_storage_quota_bytes);
    setSaved({ enabled: settings.file_uploads_enabled, amount: parts.amount, unit: parts.unit });
    setEnabled(settings.file_uploads_enabled);
    setLimitAmount(parts.amount);
    setLimitUnit(parts.unit);
  }, []);

  if (saved === null) return <Spinner />;
  const dirty = enabled !== saved.enabled || limitAmount !== saved.amount || limitUnit !== saved.unit;

  async function save() {
    const limit = joinStorageLimit(limitAmount, limitUnit);
    if (limit === undefined) throw new Error(strings.orgStorage.invalidLimit);
    await api.put("/api/v1/system/file-uploads", { file_uploads_enabled: enabled });
    await api.put("/api/v1/system/default-storage-quota", { default_storage_quota_bytes: limit });
    setSaved({ enabled, amount: limitAmount, unit: limitUnit });
    announceBrandingChange();
  }

  return (
    <CollapsibleSection sectionKey="serverManagement.files" title={strings.fileUploads.title} collapsible={false}>
      <SettingsForm dirty={dirty} onSave={save} successMessage={strings.fileUploads.saved}>
        <ToggleField label={strings.fileUploads.enabled} checked={enabled} onChange={setEnabled} help={strings.help.fileUploadsEnabled} />
        <StorageLimitField
          label={strings.fileUploads.defaultLimit} amount={limitAmount} unit={limitUnit} placeholder={strings.fileUploads.defaultLimitNone}
          onAmountChange={setLimitAmount} onUnitChange={setLimitUnit} help={strings.help.defaultStorageLimit}
        />
      </SettingsForm>
    </CollapsibleSection>
  );
}
