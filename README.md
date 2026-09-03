# jobagent

Personal AI job-application agent: **discover** open roles from public ATS
boards, **match** them against your resume, **tailor** the resume per job with
Claude, and **track** every application — with a human approving each step
before anything leaves your machine.

## Architecture

```mermaid
flowchart LR
    subgraph sources [ATS Boards]
        GH[Greenhouse API]
        LV[Lever API]
        AB[Ashby API]
    end

    subgraph app [jobagent]
        D[discovery/<br/>fetch + normalize + upsert]
        M[matching/<br/>embeddings + rule filters]
        T[tailoring/<br/>Claude rewrite + diff]
        A[apply/<br/>Phase 2 stubs]
        TR[tracker/<br/>status machine]
        API[FastAPI + CLI]
    end

    DB[(PostgreSQL / SQLite)]
    R[data/resume.md]
    Y[data/targets.yaml]
    C[Claude API]

    GH --> D
    LV --> D
    AB --> D
    Y --> D
    D --> DB
    R --> M
    Y --> M
    DB <--> M
    R --> T
    T <--> C
    T --> DB
    DB <--> TR
    API --- D
    API --- M
    API --- T
    API --- TR
    TR -. human approves .-> A
```

Pipeline per job: `discovered → matched → tailored → ready_to_apply → applied → interview` (`rejected` reachable from any state). **Nothing is ever submitted automatically** — the `apply/` module is stubs only, and even in Phase 2 filling and submitting are separate steps with an explicit human approval in between.

## Setup

macOS / Linux:

```bash
make setup            # venv + deps, copies .env.example -> .env
```

Windows (Git Bash — no `make` needed):

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e ".[dev]"
cp .env.example .env
```

Then in both cases:

1. put your `ANTHROPIC_API_KEY` in `.env`
2. paste your real resume into `data/resume.md`
3. edit `data/targets.yaml` with companies you care about

Optional extras:

```bash
.venv/bin/pip install -e ".[ml]"     # sentence-transformer embeddings (better matching;
                                     # without it a TF-IDF fallback is used)
.venv/bin/pip install -e ".[apply]"  # playwright, for Phase 2
```

Database: defaults to SQLite (`jobagent.db`). For Postgres, run
`docker compose up -d db` and set `DATABASE_URL` in `.env` to
`postgresql+psycopg2://jobagent:jobagent@localhost:5432/jobagent`, then
`make migrate` (SQLite dev mode auto-creates tables).

## First run: discover → match

```bash
make discover         # fetches all boards in targets.yaml, upserts into DB
make match            # scores each job 0-100 against data/resume.md
make run              # http://localhost:8000/docs
```

Then browse matches and tailor:

```bash
curl 'localhost:8000/jobs?min_score=60'
curl -X POST localhost:8000/jobs/123/tailor      # Claude-tailored resume + diff
curl localhost:8000/jobs/123/diff                # review exactly what changed
curl -X PATCH localhost:8000/applications/45/status \
     -H 'content-type: application/json' -d '{"status":"ready_to_apply"}'
```

CLI equivalents: `python -m app.cli discover | match | tailor <job_id>`.

Run everything in Docker instead: `docker compose up --build`.

## Tests

```bash
make test
```

All external calls (ATS APIs, Claude) are mocked; tests run against in-memory SQLite.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required for tailoring only |
| `DATABASE_URL` | `sqlite:///./jobagent.db` | SQLAlchemy URL |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | tailoring model |
| `RESUME_PATH` | `data/resume.md` | master resume |
| `TARGETS_PATH` | `data/targets.yaml` | boards + matching rules |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | local provider, needs the `[ml]` extra |
| `EMBEDDING_PROVIDER` | `auto` | `auto` / `voyage` / `local` / `hashing` |
| `VOYAGE_API_KEY` | — | Voyage AI embeddings (recommended for Vercel) |
| `VOYAGE_MODEL` | `voyage-3-lite` | Voyage model |
| `OWNER_EMAIL` | `owner@local` | identity of the single owner user |
| `DASHBOARD_PASSWORD` | — | Basic-auth password (required when public) |
| `VERTICAL` | `ai` | which `config/vertical/<name>/` to load |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | — | Adzuna aggregator (free) |
| `USAJOBS_API_KEY` / `USAJOBS_EMAIL` | — | USAJOBS aggregator (free) |
| `AGGREGATORS_ENABLED` | `remotive,remoteok,adzuna,usajobs` | which aggregators run |
| `INGEST_BATCH_SIZE` | `8` | companies per `/api/discover` slice |
| `CRON_SECRET` | — | bearer token for the daily Vercel cron |
| `AUTO_MIGRATE` | `false` (`true` on Vercel) | run migrations on startup |

Secrets live only in `.env` (gitignored). Never commit it.

## Phase 1 (Aplyx) — status

Aplyx is vertical: built for a US-based M.S./Ph.D. candidate in AI/CS who needs
sponsorship. The engine is generic; all domain knowledge lives as data in
`config/vertical/ai/` (role families, skill taxonomy) and is read only through
`app/vertical/loader.py`.

| Milestone | Status |
|---|---|
| 1.1 Resume ingestion + versioned profile | ✅ done |
| 1.2 Source adapters (ATS + aggregators) | ✅ done |
| 1.3 Enrichment (H-1B, E-Verify, staffing, dates) | ⬜ |
| 1.4 Employer tiering | ⬜ |
| 1.5 Matching (vector recall → features → LLM rerank) | ⬜ |

### Milestone 1.1 — what shipped

- `POST /api/resume` (PDF/DOCX/MD/TXT) → text extraction → one Claude call with a
  strict JSON schema (`app/profile/parser.py`, prompt version stamped on every
  row) → skills normalized against the taxonomy (unknowns kept in `other_skills`)
  → profile embedded → stored as a new **version** in `candidate_profiles`.
- `GET /api/profile`, `PATCH /api/profile`: manual corrections are stored as
  `overrides` and always win; they survive re-uploads. Sending `null` for a field
  clears the override. Every change is a new version.
- Dashboard page **/profile**: drag-and-drop upload, parsed summary, inline editor
  for every field (overridden fields are highlighted).
- `GET /api/vertical` exposes bands, families and skills for UI pickers.

### Milestone 1.2 — what shipped

- **`SourceAdapter` interface + registry** (`app/sources/`): one module per
  source, shared normalizer, `RawJob` → `Job`. Adding a source is ~50 lines.
- **ATS adapters (no keys):** Greenhouse, Lever, Ashby, SmartRecruiters,
  Workday CxS (per-tenant, slug format `tenant.wdN/Site`).
- **Aggregators (free tiers):** Adzuna (`ADZUNA_APP_ID/KEY`), USAJOBS
  (`USAJOBS_API_KEY/EMAIL`), Remotive, RemoteOK. A missing key ⇒ that source is
  reported as `skipped`, never a crash. `AGGREGATORS_ENABLED` picks which run.
  Search terms come from `aggregator_queries` in the vertical config.
- **`companies` table** seeded from `config/vertical/ai/companies.yaml`
  (**363 US employers** across big tech, AI labs, quant, fintech, healthtech,
  robotics/AV, defense-adjacent, national labs, semis, enterprise; each with
  `tier_seed` 1/2/3, headcount band, public flag, category). Seeding is
  idempotent and never overwrites `active` / `tier_override` / fetch status.
  **Board slugs are unverified until the first successful fetch** — run
  `python -m app.cli companies verify` and fix any `not_found` with
  `python -m app.cli companies add <careers-url>` (auto-detects the ATS from
  the URL or by scanning the page for an embedded ATS link, honoring robots.txt).
- **Rules 3/4/5:** every job keeps `source_name` + `url`; cross-source dedupe on
  normalized (company, title, location) with the ATS copy always winning
  (`duplicate_of` links the aggregator copy); boards that stop returning a
  posting close it (`status=closed`, `closed_at`); aggregator postings expire
  after 45 days unseen. `first_seen_at` / `last_seen_at` on every row.
- **Ingestion runs** (`ingestion_runs`): a run is processed in **slices** —
  `POST /api/discover` advances one slice (≈8 companies or one aggregator) and
  returns the run; the dashboard button loops until `status=done`. `GET
  /api/discover?all=1` loops within a 45 s budget (used by the daily Vercel cron,
  authenticated with `CRON_SECRET`). Locally `python -m app.cli discover` runs
  everything in one go. Per-source status/count/duration/error is recorded on
  the run (`GET /api/runs`, `/api/runs/{id}`).
- **Company registry API:** `GET /api/companies` (with open-job counts),
  `POST /api/companies` (careers URL → ATS auto-detect), `PATCH
  /api/companies/{id}` (`active`, `tier_override`, slug fixes),
  `POST /api/companies/seed`.
- **Auto-migration:** `AUTO_MIGRATE` (default on under Vercel) runs
  `alembic upgrade head` on startup / first request, so schema changes deploy
  without a manual step.

Serverless choice, documented: Vercel Hobby functions cap at 60 s, so a full
run (hundreds of boards) cannot finish in one invocation. Ingestion is sliced
and resumable instead of moved to a separate worker; the dashboard drives the
slices interactively and the cron does a bounded catch-up daily.

### Startup-readiness done in 1.1 (Section 4)

- **Multi-tenant**: `users` table; `user_id` (FK + index) on every per-user table
  (`applications`, `tailored_resumes`, `resume_files`, `candidate_profiles`,
  `llm_usage`). Jobs stay global.
- **Row-level security** (Postgres): policies + `FORCE ROW LEVEL SECURITY` on
  every per-user table; `app/db/tenancy.py` sets `app.user_id` per transaction.
  No user in context ⇒ zero rows (fails closed). Verified against Postgres 16
  with a non-superuser role.
- **AuthProvider** interface (`app/auth.py`): HTTP Basic today; swapping to
  OAuth is one class.
- **LLM metering**: `llm_usage` logs tokens + estimated cost per user per
  feature per prompt version, from the first call.
- **Versioned artifacts**: `prompt_version`, `parser_model`, `embedding_model`
  stored on every profile row.

### Parsing without API credits

If `ANTHROPIC_API_KEY` is unset, or the API rejects the call (invalid key, no
credits), resume upload falls back to a free extractive parser
(`app/profile/heuristic.py`: regexes + the skill taxonomy). It fills contact,
education, skills, titles and locations where found and leaves experience
years, sponsorship and target titles blank rather than guessing. Profiles
record `parser_model = heuristic-1.0` and the dashboard shows a notice.
Re-upload after adding credits for the full Claude parse.

### Embeddings

`EMBEDDING_PROVIDER=auto` picks, in order: Voyage AI (`VOYAGE_API_KEY`,
recommended on Vercel; `voyage-3-lite` by default), local sentence-transformers
(`pip install -e ".[ml]"`), then a dependency-free hashing fallback (works
everywhere, low quality — the provider name is stored with each vector so a
mismatch is visible, never silent). On Postgres with the `pgvector` extension
(Neon has it) vectors are stored as `vector`; elsewhere as JSON.

### Migrations

`alembic upgrade head` — migration `0002` creates the new tables, backfills
`user_id` to the owner (`OWNER_EMAIL`), enables RLS and, when available, the
`vector` extension. Run it against Neon before deploying this version.

## Deploying to Vercel

The repo includes `vercel.json` + `api/index.py`, so Vercel builds it as a
Python serverless app automatically once the project is linked to this GitHub
repo. Three environment variables are required in the Vercel project settings:

| Var | Value |
|---|---|
| `DATABASE_URL` | a hosted Postgres URL (e.g. free [Neon](https://neon.tech): `postgresql+psycopg2://user:pass@host/db?sslmode=require`) |
| `DASHBOARD_PASSWORD` | any password — **without it your data and API key are public** |
| `ANTHROPIC_API_KEY` | for the Tailor button |

Serverless caveats: without `DATABASE_URL` the app falls back to SQLite in
`/tmp`, which is wiped between invocations — fine for a smoke test, useless for
real data. The `[ml]` embeddings extra doesn't fit in a serverless bundle, so
matching uses the TF-IDF fallback there; run `python -m app.cli match --all`
locally (pointing `DATABASE_URL` at the same Postgres) for embedding-quality
scores. GitHub Pages is static-only and cannot host this app.

## Phase 2 roadmap

1. **Playwright auto-apply for Greenhouse & Lever** — fill forms from the
   approved tailored resume, screenshot for review, submit only after an
   explicit human approve step (`ready_to_apply → applied`).
2. **Open-ended question answering** — Claude drafts answers to free-text
   application questions from resume facts only; human edits/approves each.
3. **Workday support** — the long tail: multi-page flows, account creation.
4. **Web dashboard** — review queue (match reasons, diffs, approvals) instead
   of curl; notifications for new high-score matches.
