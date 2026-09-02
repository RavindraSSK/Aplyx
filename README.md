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

```bash
make setup            # venv + deps, copies .env.example -> .env
# then:
#   1. put your ANTHROPIC_API_KEY in .env
#   2. paste your real resume into data/resume.md
#   3. edit data/targets.yaml with companies you care about
```

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
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | needs the `[ml]` extra |

Secrets live only in `.env` (gitignored). Never commit it.

## Phase 2 roadmap

1. **Playwright auto-apply for Greenhouse & Lever** — fill forms from the
   approved tailored resume, screenshot for review, submit only after an
   explicit human approve step (`ready_to_apply → applied`).
2. **Open-ended question answering** — Claude drafts answers to free-text
   application questions from resume facts only; human edits/approves each.
3. **Workday support** — the long tail: multi-page flows, account creation.
4. **Web dashboard** — review queue (match reasons, diffs, approvals) instead
   of curl; notifications for new high-score matches.
