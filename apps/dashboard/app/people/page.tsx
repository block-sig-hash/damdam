"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  CostCentre,
  ImportPreview,
  Person,
  Team,
  applyPeopleImport,
  cancelPeopleImport,
  createCostCentre,
  createTeam,
  downloadPeopleCsv,
  fetchCostCentres,
  fetchPeople,
  fetchTeams,
  uploadPeopleFile,
} from "@/lib/people";

/**
 * Organization people (US-39, chunk 22).
 *
 * The screen an enterprise administrator uses to say who their organization
 * buys service for. Three things it is careful about.
 *
 * **It says, in words, that this is not access.** The notice is not decoration:
 * an administrator uploading a staff list has every reason to assume they are
 * inviting people, and finding out otherwise later is the kind of surprise that
 * ends with somebody emailing a spreadsheet of credentials instead.
 *
 * **An import is previewed before it is applied.** The preview is computed by
 * the server with the same code that will do the work, so "412 new, 6 errors"
 * is a fact rather than an estimate, and the administrator approves that fact.
 *
 * **Errors are shown per row, in the administrator's language, all at once.**
 * The server sends stable codes; this file turns them into sentences. A row
 * that is wrong four ways says so four ways, because fixing a large file one
 * error per upload is how people give up.
 */

type Tab = "people" | "teams" | "costCentres" | "imports";

export default function PeoplePage() {
  const t = useTranslations("people");
  const [organizationId, setOrganizationId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("people");
  const [people, setPeople] = useState<Person[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [costCentres, setCostCentres] = useState<CostCentre[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");


  const load = useCallback(async () => {
    // Read on demand rather than mirrored into state by a mount effect: the
    // value never changes while the page is open, and copying it in an effect
    // costs a render and trips `react-hooks/set-state-in-effect`.
    const id = window.localStorage.getItem("damdam_organization_id");
    setOrganizationId(id);
    if (!id) return;
    setError("");
    try {
      const [loadedPeople, loadedTeams, loadedCentres] = await Promise.all([
        fetchPeople(id),
        fetchTeams(id),
        fetchCostCentres(id),
      ]);
      setPeople(loadedPeople);
      setTeams(loadedTeams);
      setCostCentres(loadedCentres);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("errors.loadFailed"));
    }
  }, [t]);

  useEffect(() => {
    // Deferred by a zero timer, matching the admin pricing page: a synchronous
    // `load()` here sets state during the effect and cascades a render.
    const timer = window.setTimeout(() => {
      load().catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function upload() {
    if (!organizationId || !file) return;
    setBusy(true);
    setError("");
    try {
      setPreview(await uploadPeopleFile(organizationId, file));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("errors.uploadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!organizationId || !preview) return;
    setBusy(true);
    try {
      const summary = await applyPeopleImport(
        organizationId,
        preview.summary.import_id,
      );
      setNotice(
        t("imports.applied", {
          created: summary.created_count,
          updated: summary.updated_count,
        }),
      );
      setPreview(null);
      setFile(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("errors.uploadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!organizationId || !preview) return;
    await cancelPeopleImport(organizationId, preview.summary.import_id);
    setPreview(null);
    setFile(null);
  }

  async function exportCsv() {
    if (!organizationId) return;
    // Fetched rather than linked: the export needs the Authorization header,
    // and a plain link would send the browser without it and 401 in a way that
    // looks like a broken button.
    const blob = await downloadPeopleCsv(organizationId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "people.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  const teamName = (id: string | null) =>
    teams.find((team) => team.team_id === id)?.name ?? "";
  const centreCode = (id: string | null) =>
    costCentres.find((centre) => centre.cost_centre_id === id)?.code ?? "";

  return (
    <main className="page" data-testid="people-page">
      <h1>{t("title")}</h1>
      <p>{t("subtitle")}</p>

      <p role="note" data-testid="people-no-privilege-notice">
        {t("notice.noPrivilege")}
      </p>

      {error ? (
        <p role="alert" data-testid="people-error">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" data-testid="people-notice">
          {notice}
        </p>
      ) : null}

      <nav aria-label={t("title")}>
        {(["people", "teams", "costCentres", "imports"] as Tab[]).map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setTab(name)}
            aria-current={tab === name ? "page" : undefined}
            data-testid={`people-tab-${name}`}
          >
            {t(`tabs.${name}`)}
          </button>
        ))}
      </nav>

      {tab === "people" ? (
        <section aria-label={t("tabs.people")}>
          <button type="button" onClick={exportCsv} data-testid="people-export">
            {t("actions.export")}
          </button>
          {people.length === 0 ? (
            <p data-testid="people-empty">{t("empty")}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">{t("columns.name")}</th>
                  <th scope="col">{t("columns.email")}</th>
                  <th scope="col">{t("columns.reference")}</th>
                  <th scope="col">{t("columns.team")}</th>
                  <th scope="col">{t("columns.costCentre")}</th>
                  <th scope="col">{t("columns.status")}</th>
                </tr>
              </thead>
              <tbody>
                {people.map((person) => (
                  <tr key={person.person_id} data-testid={`person-${person.person_id}`}>
                    <td>{person.full_name}</td>
                    <td>{person.email ?? ""}</td>
                    <td>{person.external_reference ?? ""}</td>
                    <td>{teamName(person.team_id)}</td>
                    <td>{centreCode(person.cost_centre_id)}</td>
                    <td>{t(`status.${person.status}`)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {tab === "teams" ? (
        <TeamSection
          organizationId={organizationId}
          teams={teams}
          costCentres={costCentres}
          onCreated={load}
        />
      ) : null}

      {tab === "costCentres" ? (
        <CostCentreSection
          organizationId={organizationId}
          costCentres={costCentres}
          onCreated={load}
        />
      ) : null}

      {tab === "imports" ? (
        <section aria-label={t("tabs.imports")}>
          <h2>{t("imports.title")}</h2>
          <label htmlFor="people-file">{t("imports.choose")}</label>
          <input
            id="people-file"
            type="file"
            accept=".csv,text/csv"
            data-testid="people-file"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
          <button
            type="button"
            onClick={upload}
            disabled={!file || busy}
            data-testid="people-upload"
          >
            {busy ? t("imports.reading") : t("imports.upload")}
          </button>

          {preview ? <ImportPreviewPanel preview={preview} onApply={apply} onDiscard={discard} busy={busy} /> : null}
        </section>
      ) : null}
    </main>
  );
}

function ImportPreviewPanel({
  preview,
  onApply,
  onDiscard,
  busy,
}: {
  preview: ImportPreview;
  onApply: () => void;
  onDiscard: () => void;
  busy: boolean;
}) {
  const t = useTranslations("people");
  const { summary } = preview;

  if (summary.state === "rejected") {
    return (
      <div role="alert" data-testid="import-rejected">
        <p>
          {summary.rejection_code
            ? t(`imports.rejection.${summary.rejection_code}`)
            : t("errors.uploadFailed")}
        </p>
      </div>
    );
  }

  return (
    <div data-testid="import-preview">
      <h3>{t("imports.preview")}</h3>
      <ul>
        <li data-testid="import-valid">
          {t("imports.willCreate", { count: summary.valid_count })}
        </li>
        <li data-testid="import-invalid">
          {t("imports.invalid", { count: summary.invalid_count })}
        </li>
      </ul>

      {preview.ignored_columns.length > 0 ? (
        <p data-testid="import-ignored">
          {t("imports.ignoredColumns", {
            columns: preview.ignored_columns.join(", "),
          })}
        </p>
      ) : null}

      <h4>{t("imports.sample")}</h4>
      <ul>
        {preview.sample_rows.map((row) => (
          <li key={row.row_number} data-testid={`import-row-${row.row_number}`}>
            {t("imports.row", { number: row.row_number })}
            {row.error_codes.length > 0
              ? `: ${row.error_codes
                  .map((code) => t(`imports.rowError.${code}`))
                  .join("; ")}`
              : ""}
          </li>
        ))}
      </ul>

      <button
        type="button"
        onClick={onApply}
        disabled={busy || summary.valid_count === 0}
        data-testid="import-apply"
      >
        {busy ? t("imports.applying") : t("imports.apply")}
      </button>
      <button type="button" onClick={onDiscard} data-testid="import-discard">
        {t("imports.cancel")}
      </button>
    </div>
  );
}

function TeamSection({
  organizationId,
  teams,
  costCentres,
  onCreated,
}: {
  organizationId: string | null;
  teams: Team[];
  costCentres: CostCentre[];
  onCreated: () => Promise<void>;
}) {
  const t = useTranslations("people");
  const [name, setName] = useState("");
  const [centre, setCentre] = useState("");

  async function submit() {
    if (!organizationId || !name.trim()) return;
    await createTeam(organizationId, name.trim(), centre || undefined);
    setName("");
    setCentre("");
    await onCreated();
  }

  return (
    <section aria-label={t("tabs.teams")}>
      {teams.length === 0 ? <p data-testid="teams-empty">{t("teams.empty")}</p> : null}
      <ul>
        {teams.map((team) => (
          <li key={team.team_id} data-testid={`team-${team.team_id}`}>
            {team.name}
          </li>
        ))}
      </ul>
      <label htmlFor="team-name">{t("teams.name")}</label>
      <input
        id="team-name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        data-testid="team-name"
      />
      <label htmlFor="team-centre">{t("teams.costCentre")}</label>
      <select
        id="team-centre"
        value={centre}
        onChange={(event) => setCentre(event.target.value)}
        data-testid="team-centre"
      >
        <option value="">{t("teams.none")}</option>
        {costCentres.map((option) => (
          <option key={option.cost_centre_id} value={option.cost_centre_id}>
            {option.code}
          </option>
        ))}
      </select>
      <button type="button" onClick={submit} data-testid="team-create">
        {t("actions.addTeam")}
      </button>
    </section>
  );
}

function CostCentreSection({
  organizationId,
  costCentres,
  onCreated,
}: {
  organizationId: string | null;
  costCentres: CostCentre[];
  onCreated: () => Promise<void>;
}) {
  const t = useTranslations("people");
  const [code, setCode] = useState("");
  const [name, setName] = useState("");

  async function submit() {
    if (!organizationId || !code.trim() || !name.trim()) return;
    await createCostCentre(organizationId, code.trim(), name.trim());
    setCode("");
    setName("");
    await onCreated();
  }

  return (
    <section aria-label={t("tabs.costCentres")}>
      {costCentres.length === 0 ? (
        <p data-testid="centres-empty">{t("costCentres.empty")}</p>
      ) : null}
      <ul>
        {costCentres.map((centre) => (
          <li key={centre.cost_centre_id} data-testid={`centre-${centre.cost_centre_id}`}>
            {centre.code} — {centre.name}
          </li>
        ))}
      </ul>
      <label htmlFor="centre-code">{t("costCentres.code")}</label>
      <input
        id="centre-code"
        value={code}
        onChange={(event) => setCode(event.target.value)}
        data-testid="centre-code"
      />
      <label htmlFor="centre-name">{t("costCentres.name")}</label>
      <input
        id="centre-name"
        value={name}
        onChange={(event) => setName(event.target.value)}
        data-testid="centre-name"
      />
      <button type="button" onClick={submit} data-testid="centre-create">
        {t("actions.addCostCentre")}
      </button>
    </section>
  );
}
