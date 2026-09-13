import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PeoplePage from "./page";
import en from "@/messages/en.json";
import fr from "@/messages/fr.json";

/**
 * US-39 chunk 22 — the people screen.
 *
 * The test that matters most is the one asserting the notice is on the page.
 * An administrator uploading a staff list has every reason to assume they are
 * inviting colleagues; discovering otherwise later is how a spreadsheet of
 * credentials ends up in somebody's email. The API refuses to grant access —
 * this checks the screen says so before anybody uploads anything.
 *
 * The rest is the preview contract: what the import *will* do is shown before
 * it does it, invalid rows explain themselves in the administrator's language,
 * and a file the server could not read says why rather than failing silently.
 */

vi.mock("@/lib/people", () => ({
  fetchPeople: vi.fn(),
  fetchTeams: vi.fn(),
  fetchCostCentres: vi.fn(),
  createTeam: vi.fn(),
  createCostCentre: vi.fn(),
  uploadPeopleFile: vi.fn(),
  applyPeopleImport: vi.fn(),
  cancelPeopleImport: vi.fn(),
  fetchImportRows: vi.fn(),
  downloadPeopleCsv: vi.fn(),
}));

const people = await import("@/lib/people");
const mocked = people as unknown as {
  fetchPeople: ReturnType<typeof vi.fn>;
  fetchTeams: ReturnType<typeof vi.fn>;
  fetchCostCentres: ReturnType<typeof vi.fn>;
  uploadPeopleFile: ReturnType<typeof vi.fn>;
  applyPeopleImport: ReturnType<typeof vi.fn>;
  cancelPeopleImport: ReturnType<typeof vi.fn>;
};

const PERSON = {
  person_id: "person-1",
  full_name: "Ada Obi",
  email: "ada@example.test",
  phone_number: null,
  external_reference: "E-1",
  job_title: null,
  team_id: null,
  cost_centre_id: null,
  status: "active" as const,
  has_account: false,
};


/** Put a file on the input the way the browser would, then let React settle. */
async function chooseFile(name: string) {
  const input = screen.getByTestId("people-file") as HTMLInputElement;
  const file = new File(["Full Name,Email\nAda,ada@example.test\n"], name, {
    type: "text/csv",
  });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
  await waitFor(() =>
    expect((screen.getByTestId("people-upload") as HTMLButtonElement).disabled).toBe(
      false,
    ),
  );
}

function renderPage(messages: typeof en = en) {
  return render(
    <NextIntlClientProvider locale={messages === en ? "en" : "fr"} messages={messages}>
      <PeoplePage />
    </NextIntlClientProvider>,
  );
}

describe("people page", () => {
  // Vitest does not unmount between tests on its own here, and a second render
  // of the same page makes every `getByText` ambiguous rather than failing
  // somewhere that explains itself.
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.setItem("damdam_organization_id", "org-1");
    mocked.fetchPeople.mockResolvedValue([PERSON]);
    mocked.fetchTeams.mockResolvedValue([]);
    mocked.fetchCostCentres.mockResolvedValue([]);
  });

  it("says plainly that adding somebody is not granting access", async () => {
    renderPage();

    const notice = await screen.findByTestId("people-no-privilege-notice");
    expect(notice.textContent).toContain("does not give them access");
  });

  it("lists the organization's people", async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText("Ada Obi")).toBeTruthy());
    expect(screen.getByText("ada@example.test")).toBeTruthy();
    expect(screen.getByText("E-1")).toBeTruthy();
  });

  it("shows what an import will do before it does it", async () => {
    mocked.uploadPeopleFile.mockResolvedValue({
      summary: {
        import_id: "import-1",
        state: "previewed",
        filename: "staff.csv",
        row_count: 3,
        valid_count: 2,
        invalid_count: 1,
        created_count: 0,
        updated_count: 0,
        rejection_code: null,
        created_at: "2026-09-13T10:00:00Z",
        applied_at: null,
      },
      sample_rows: [
        { row_number: 2, state: "valid", error_codes: [], payload: {} },
        {
          row_number: 3,
          state: "invalid",
          error_codes: ["missing_name", "invalid_phone"],
          payload: {},
        },
      ],
      ignored_columns: ["Favourite Colour"],
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("people-tab-imports"));
    await chooseFile("staff.csv");
    fireEvent.click(screen.getByTestId("people-upload"));

    const preview = await screen.findByTestId("import-preview");
    expect(preview).toBeTruthy();
    expect(screen.getByTestId("import-valid").textContent).toContain("2");
    expect(screen.getByTestId("import-invalid").textContent).toContain("1");
    expect(screen.getByTestId("import-ignored").textContent).toContain(
      "Favourite Colour",
    );
    expect(mocked.applyPeopleImport).not.toHaveBeenCalled();
  });

  it("explains every reason a row cannot be used", async () => {
    mocked.uploadPeopleFile.mockResolvedValue({
      summary: {
        import_id: "import-1",
        state: "previewed",
        filename: "staff.csv",
        row_count: 1,
        valid_count: 0,
        invalid_count: 1,
        created_count: 0,
        updated_count: 0,
        rejection_code: null,
        created_at: "2026-09-13T10:00:00Z",
        applied_at: null,
      },
      sample_rows: [
        {
          row_number: 2,
          state: "invalid",
          error_codes: ["missing_name", "invalid_phone"],
          payload: {},
        },
      ],
      ignored_columns: [],
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("people-tab-imports"));
    await chooseFile("staff.csv");
    fireEvent.click(screen.getByTestId("people-upload"));

    const row = await screen.findByTestId("import-row-2");
    expect(row.textContent).toContain("No name");
    expect(row.textContent).toContain("country code");
  });

  it("will not offer to import a file with nothing usable in it", async () => {
    mocked.uploadPeopleFile.mockResolvedValue({
      summary: {
        import_id: "import-1",
        state: "previewed",
        filename: "staff.csv",
        row_count: 1,
        valid_count: 0,
        invalid_count: 1,
        created_count: 0,
        updated_count: 0,
        rejection_code: null,
        created_at: "2026-09-13T10:00:00Z",
        applied_at: null,
      },
      sample_rows: [],
      ignored_columns: [],
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("people-tab-imports"));
    await chooseFile("staff.csv");
    fireEvent.click(screen.getByTestId("people-upload"));

    const apply = await screen.findByTestId("import-apply");
    expect((apply as HTMLButtonElement).disabled).toBe(true);
  });

  it("says why a file could not be read at all", async () => {
    mocked.uploadPeopleFile.mockResolvedValue({
      summary: {
        import_id: "import-1",
        state: "rejected",
        filename: "notes.txt",
        row_count: 0,
        valid_count: 0,
        invalid_count: 0,
        created_count: 0,
        updated_count: 0,
        rejection_code: "no_identifying_column",
        created_at: "2026-09-13T10:00:00Z",
        applied_at: null,
      },
      sample_rows: [],
      ignored_columns: [],
    });

    renderPage();
    fireEvent.click(await screen.findByTestId("people-tab-imports"));
    await chooseFile("notes.txt");
    fireEvent.click(screen.getByTestId("people-upload"));

    const rejected = await screen.findByTestId("import-rejected");
    expect(rejected.textContent).toContain("name column");
  });

  it("renders in French without falling back to English", async () => {
    renderPage(fr as typeof en);

    const notice = await screen.findByTestId("people-no-privilege-notice");
    expect(notice.textContent).toContain("ne lui donne pas accès");
  });
});
