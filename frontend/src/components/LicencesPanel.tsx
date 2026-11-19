/**
 * Module: components/LicencesPanel
 *
 * The three sections of the Licences group on the Policies page: the product's own licence, the third-party
 * components it ships (libraries, programs in the images, base images) and the fonts. Readable without signing in.
 *
 * Responsibilities:
 * - `LicencesSection`: reads the generated inventory once and shows the chosen section.
 * - The library table: search, sort on a header click and "Show more" over the whole list held in the browser; a row
 *   opens its detail (licence, where it is used, its registry page and its licence texts).
 * - Licence texts are read only when a person opens one (the file is large), through one shared viewer.
 *
 * Design decisions: the data is static and authorless, so it does not go through the versioned policy model (see
 * `docs/decisions.md`, "Licences in the Policies area"). The product licence is a constant here, the one place a
 * licence change edits. Everything is a React element; no licence text or package field is inserted as markup.
 *
 * Dependencies: `hooks/useThirdPartyNotices` (static JSON assets), `DirectoryTable`, `Modal`.
 */
import { useMemo, useState, type ReactNode } from "react";

import { useStrings } from "../context/TerminologyContext";
import {
  useLicenceTexts, useThirdPartyNotices,
  type LicenceFont, type LicencePackage, type LicenceSystemComponent, type ThirdPartyNotices,
} from "../hooks/useThirdPartyNotices";
import { useSortState, useTableSort } from "../hooks/useTableSort";
import type { LicenceSection } from "../utils/policiesPath";
import { sortRows } from "../utils/sortRows";
import { DirectoryTable, type DirectoryColumn } from "./DirectoryTable";
import { DisclosureRow } from "./DisclosureRow";
import { InlineTextInput } from "./FormFields";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

/** The licence the product itself is offered under; the single place a change of licence is recorded for display. */
export const PRODUCT_LICENCE = {
  name: "GNU General Public License, version 3",
  spdx: "GPL-3.0-only",
  textUrl: "https://www.gnu.org/licenses/gpl-3.0.html",
  sourceUrl: "https://github.com/ballardr/reqtrackmanager",
} as const;

/** How many libraries the table shows before "Show more". */
const LIBRARY_PAGE = 100;

/** An external link that opens in a new tab without leaking the referrer. */
function ExternalLink({ href, children }: { href: string; children: string }) {
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}

/** A web address is shown as a link only when it is http or https; anything else is plain text. */
function SafeLink({ href, children }: { href: string; children: string }) {
  return /^https?:\/\//i.test(href) ? <ExternalLink href={href}>{children}</ExternalLink> : <>{children}</>;
}

/**
 * The licence texts of one component, collapsed until opened; the shared texts file is read on the first opening.
 *
 * @param ids Ids of the texts (from the inventory); empty shows that no licence file is bundled.
 */
function LicenceTexts({ ids }: { ids: string[] }) {
  const text = useStrings().licences;
  const [open, setOpen] = useState(false);
  const texts = useLicenceTexts(open);
  if (ids.length === 0) return <p className="text-muted" style={{ margin: 0 }}>{text.textsNone}</p>;
  return (
    <DisclosureRow title={text.showText} collapsed={!open} onToggle={() => setOpen((current) => !current)}>
      {texts.failed && <div role="alert">{text.textsFailed}</div>}
      {!texts.failed && !texts.data && <Spinner label={text.textsLoading} />}
      {texts.data && ids.map((id) => (
        <pre key={id} className="licence-text" tabIndex={0} aria-label={text.showText}>{texts.data?.[id] ?? text.textsFailed}</pre>
      ))}
    </DisclosureRow>
  );
}

/** A label and value pair of a detail view. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <span className="text-muted">{label}</span>
      <div>{children}</div>
    </div>
  );
}

/** The detail dialog of one library. */
function LibraryDetail({ pkg, notices, onClose }: { pkg: LicencePackage; notices: ThirdPartyNotices; onClose: () => void }) {
  const text = useStrings().licences;
  const sourceLabel: Record<LicencePackage["licence_source"], string> = {
    metadata: text.licenceSourceMetadata,
    "package.json": text.licenceSourceMetadata,
    classifier: text.licenceSourceMetadata,
    override: text.licenceSourceOverride,
  };
  const reason = notices.library_copyleft_reasons[`${pkg.ecosystem}:${pkg.name}`];
  return (
    <Modal title={text.detailTitle(`${pkg.name} ${pkg.version}`)} onClose={onClose}>
      <div className="stack">
        <Fact label={text.licence}>{pkg.licence}</Fact>
        <Fact label={text.licenceSource}>{sourceLabel[pkg.licence_source]}</Fact>
        <Fact label={text.usedIn}>{componentTitles(notices, pkg.components)}</Fact>
        {reason && <Fact label={text.reason}>{reason}</Fact>}
        <Fact label={text.registryLink}><SafeLink href={pkg.link}>{pkg.link}</SafeLink></Fact>
        <LicenceTexts ids={pkg.texts} />
      </div>
    </Modal>
  );
}

/** The titles of the images or bundles that hold a component, joined for display. */
function componentTitles(notices: ThirdPartyNotices, ids: string[]): string {
  return ids.map((id) => notices.components.find((c) => c.id === id)?.title ?? id).join(", ");
}

const LIBRARY_SORT_VALUES = {
  name: (p: LicencePackage) => p.name,
  version: (p: LicencePackage) => p.version,
  licence: (p: LicencePackage) => p.licence,
  kind: (p: LicencePackage) => p.ecosystem,
};

/** The searchable, sortable table of every library, with a detail dialog per row. */
function LibrariesTable({ notices }: { notices: ThirdPartyNotices }) {
  const text = useStrings().licences;
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(LIBRARY_PAGE);
  const [selected, setSelected] = useState<LicencePackage | null>(null);
  const needle = query.trim().toLowerCase();
  const filtered = useMemo(
    () => (needle ? notices.packages.filter((p) => `${p.name} ${p.licence}`.toLowerCase().includes(needle)) : notices.packages),
    [notices.packages, needle],
  );
  const { sort, onSort } = useSortState();
  const rows = useMemo(() => sortRows(filtered, sort, LIBRARY_SORT_VALUES), [filtered, sort]);
  const columns: DirectoryColumn<LicencePackage>[] = [
    { key: "name", label: text.name, sortable: true, render: (p) => p.name },
    { key: "version", label: text.version, sortable: true, render: (p) => p.version },
    { key: "licence", label: text.licence, sortable: true, render: (p) => p.licence },
    { key: "kind", label: text.kind, sortable: true, render: (p) => (p.ecosystem === "npm" ? text.packageNpm : text.packagePython) },
    { key: "usedIn", label: text.usedIn, render: (p) => componentTitles(notices, p.components) },
  ];
  return (
    <section className="stack" aria-labelledby="licences-libraries">
      <h3 id="licences-libraries" style={{ margin: 0 }}>{text.librariesHeading}</h3>
      <div style={{ maxWidth: "24rem" }}>
        <InlineTextInput
          ariaLabel={text.librariesSearch} placeholder={text.librariesSearchPlaceholder} value={query}
          onChange={(value) => { setQuery(value); setShown(LIBRARY_PAGE); }}
        />
      </div>
      <DirectoryTable
        ariaLabel={text.librariesTable} columns={columns} rows={rows.slice(0, shown)} rowKey={(p) => `${p.ecosystem}:${p.name}@${p.version}`}
        sort={sort} onSort={onSort} total={rows.length} onLoadMore={() => setShown((n) => n + LIBRARY_PAGE)}
        onRowClick={setSelected} emptyState={<p className="text-muted">{text.librariesNone}</p>}
      />
      {selected && <LibraryDetail pkg={selected} notices={notices} onClose={() => setSelected(null)} />}
    </section>
  );
}

/** The table of programs the images get from the operating system, each with why it is allowed and where its source is. */
function ProgramsTable({ notices }: { notices: ThirdPartyNotices }) {
  const text = useStrings().licences;
  const [selected, setSelected] = useState<LicenceSystemComponent | null>(null);
  const useLabel: Record<LicenceSystemComponent["use"], string> = {
    program: text.useProgram, "separate-program": text.useSeparateProgram, library: text.useLibrary, "build-tool": text.useBuildTool,
  };
  const { rows, sort, onSort } = useTableSort(notices.system_components, {
    name: (c: LicenceSystemComponent) => c.name, licence: (c) => c.licence,
  });
  const columns: DirectoryColumn<LicenceSystemComponent>[] = [
    { key: "name", label: text.name, sortable: true, render: (c) => c.name },
    { key: "licence", label: text.licence, sortable: true, render: (c) => c.licence },
    { key: "role", label: text.role, render: (c) => c.role },
    { key: "images", label: text.images, render: (c) => (c.images.length ? c.images.join(", ") : "–") },
  ];
  return (
    <section className="stack" aria-labelledby="licences-programs">
      <h3 id="licences-programs" style={{ margin: 0 }}>{text.programsHeading}</h3>
      <DirectoryTable
        ariaLabel={text.programsTable} columns={columns} rows={rows} rowKey={(c) => c.name} sort={sort} onSort={onSort}
        onRowClick={setSelected} emptyState={null}
      />
      {selected && (
        <Modal title={text.detailTitle(selected.name)} onClose={() => setSelected(null)}>
          <div className="stack">
            <Fact label={text.licence}>{selected.licence}</Fact>
            <Fact label={text.use}>{useLabel[selected.use]}</Fact>
            <Fact label={text.reason}>{selected.reason}</Fact>
            <Fact label={text.sourceLink}><SafeLink href={selected.source}>{selected.source}</SafeLink></Fact>
          </div>
        </Modal>
      )}
    </section>
  );
}

/** The table of base images and the licences of what they bring. */
function BaseImagesTable({ notices }: { notices: ThirdPartyNotices }) {
  const text = useStrings().licences;
  const entries = Object.entries(notices.base_images).map(([image, info]) => ({ image, ...info }));
  const { rows, sort, onSort } = useTableSort(entries, { image: (e: (typeof entries)[number]) => e.image, licence: (e) => e.licence });
  const columns: DirectoryColumn<(typeof entries)[number]>[] = [
    { key: "image", label: text.image, sortable: true, render: (e) => e.image },
    { key: "licence", label: text.licence, sortable: true, render: (e) => e.licence },
    { key: "images", label: text.usedIn, render: (e) => (e.images.length ? e.images.join(", ") : "–") },
    { key: "note", label: text.notices, render: (e) => e.note },
  ];
  return (
    <section className="stack" aria-labelledby="licences-base-images">
      <h3 id="licences-base-images" style={{ margin: 0 }}>{text.baseImagesHeading}</h3>
      <DirectoryTable ariaLabel={text.baseImagesTable} columns={columns} rows={rows} rowKey={(e) => e.image} sort={sort} onSort={onSort} emptyState={null} />
    </section>
  );
}

/** The third-party components section: programs, base images, libraries and the notes about optional services. */
function ComponentsSection({ notices }: { notices: ThirdPartyNotices }) {
  const text = useStrings().licences;
  return (
    <div className="stack">
      <h2 style={{ margin: 0 }}>{text.componentsHeading}</h2>
      <p className="text-muted" style={{ margin: 0 }}>{text.componentsSummary(notices.packages.length, notices.system_components.length)}</p>
      <ProgramsTable notices={notices} />
      <BaseImagesTable notices={notices} />
      <LibrariesTable notices={notices} />
      {notices.notes.length > 0 && (
        <ul style={{ margin: 0 }}>{notices.notes.map((note) => <li key={note}>{note}</li>)}</ul>
      )}
    </div>
  );
}

/** One font's card: its licence, where it is used and its licence text. */
function FontCard({ font }: { font: LicenceFont }) {
  const text = useStrings().licences;
  return (
    <article className="card stack" aria-label={font.name}>
      <h3 style={{ margin: 0 }}>{font.name}</h3>
      <Fact label={text.licence}>{font.licence}</Fact>
      <Fact label={text.fontLocation}>{font.where}</Fact>
      <Fact label={text.fontFiles}>{font.files}</Fact>
      <p style={{ margin: 0 }}>{font.note}</p>
      <LicenceTexts ids={font.texts} />
    </article>
  );
}

/** The product licence section. */
function ProductSection() {
  const text = useStrings().licences;
  return (
    <div className="stack">
      <h2 style={{ margin: 0 }}>{text.productHeading}</h2>
      <p style={{ margin: 0 }}>{text.productStatement(PRODUCT_LICENCE.name, PRODUCT_LICENCE.spdx)}</p>
      <ul style={{ margin: 0 }}>
        <li><ExternalLink href={PRODUCT_LICENCE.textUrl}>{text.productLicenceText}</ExternalLink></li>
        <li><ExternalLink href={PRODUCT_LICENCE.sourceUrl}>{text.productSource}</ExternalLink></li>
      </ul>
      <p className="text-muted" style={{ margin: 0 }}>{text.productComponentsNote}</p>
    </div>
  );
}

/**
 * One section of the Licences group. The product licence needs no data; the other sections read the inventory.
 *
 * @param section Which section to show.
 */
export function LicencesSection({ section }: { section: LicenceSection }) {
  const text = useStrings().licences;
  const { data, failed } = useThirdPartyNotices();
  if (section === "product") return <ProductSection />;
  if (failed) return <div role="alert">{text.loadFailed}</div>;
  if (!data) return <Spinner />;
  if (section === "components") return <ComponentsSection notices={data} />;
  return (
    <div className="stack">
      <h2 style={{ margin: 0 }}>{text.fontsHeading}</h2>
      {data.fonts.length === 0 ? <p className="text-muted">{text.fontsNone}</p> : data.fonts.map((font) => <FontCard key={font.name} font={font} />)}
    </div>
  );
}
