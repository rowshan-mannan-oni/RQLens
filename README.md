# RQ Lens

**Know what your data can answer before you design the study.**

Documentation reviewed against the repository on **2026-10-07**.

RQ Lens is a companion for researchers working with a tabular dataset. Upload your data (CSV, Excel, SPSS, Stata or Parquet) and write your research questions. RQ Lens profiles every column, tells you whether each question is answerable with this data and why, ranks exploratory findings, and answers questions in plain language. Every number on screen comes from a logged SQL query you can open and rerun.

![RQ Fit page](docs/rq-fit.png)

![Literature table with the reader open at a cited sentence](docs/literature-reader.png)

## What it does

| Feature | How it works |
|---|---|
| **Data files** | CSV, Excel, SPSS (`.sav`, `.zsav`, `.por`), Stata (`.dta`) and Parquet. SPSS and Stata variable labels fill the data dictionary; fully labelled codes become their labels, and user-defined missing values ("9 = Refused") become missing, with a note. |
| **Compare and combine** | Compare column types, categories, missingness and possible links across datasets. Stack compatible files with a `source_file` column, or join two datasets on a key using a left or inner join. Combined datasets are profiled and can be used for research questions and insights. |
| **Profiling** | Pure SQL in DuckDB, with no AI involved. It finds types, missing values, distributions, outliers, correlations, missing-data patterns and join keys, plus rule-based warnings for placeholder codes such as `-999`, label leakage, unit changes and near-duplicate columns. |
| **Research-question fit** | An LLM parses each question and maps its constructs to columns. Guarded SQL checks then measure rows in scope, missing values, group sizes, outcome variation, time coverage and statistical power. **Fixed rules** give the verdict: answerable, partly answerable or not answerable. The LLM only writes the explanation, and every number in it must appear in a query result. |
| **Insights** | Up to 20 analyses are planned from your questions and the profile, then run with a fixed statistics library (Spearman, Mann-Whitney U, Kruskal-Wallis, chi-square, trend). Results are corrected with Benjamini-Hochberg, ranked by relevance, effect size and support (not p-value), and re-tested within subgroups to catch confounding. |
| **Chat** | A bounded tool-using agent (schema, profiles, column search, read-only SQL, statistical tests, charts). Answers stream back with their queries, and an answer with a number not found in any tool result is rejected. |
| **Literature review** | Upload PDFs or a whole folder. Each paper is split into numbered sentences with their positions on the page, and the AI fills a review table (built-in templates or your own), citing sentence IDs with quotes. A check without AI verifies every quote and number against the cited sentence; failures are retried once, then marked *unverified*. Click a citation to open the PDF at that page with the sentence highlighted. Edits are never overwritten; exports to CSV, Excel, Markdown and BibTeX. |
| **Dataset report** | A Markdown or PDF report with an overview, data dictionary, quality warnings, question fit, top insights and limitations. It works as a draft of a paper's data section. |
| **Sharing and comments** | Share a project by email with viewers (read and comment) or editors (also change data, questions and tables). Comment threads on the project, each research question and each literature-table cell, with resolve. |
| **Reference libraries** | Import a BibTeX or RIS export from Zotero, Mendeley or EndNote: papers get exact metadata and citation keys, matched by DOI or title, including PDFs uploaded later. Scanned papers are read with OCR. |
| **Usage and limits** | Every AI call and query is logged. The Usage page shows calls, tokens, cost and latency (average and p95) per project. Per-user limits cover projects, datasets, upload size and monthly AI calls and spend. |

To try it without your own data, click **Try a sample project**. This loads the Palmer penguins data with three research questions, and works without an AI key.

## Architecture

### Technology stack

| Layer | Technologies |
|---|---|
| Web | Next.js 16 App Router, React 19, TypeScript 5, Tailwind CSS 4 |
| Charts, icons and PDF reader | Recharts, Lucide React, PDF.js |
| Authentication | Auth.js / NextAuth 5 beta, Google or GitHub OAuth; short-lived JWTs signed with JOSE |
| API | Python 3.12, FastAPI, Uvicorn, Pydantic 2 |
| Persistence and jobs | PostgreSQL 16, SQLAlchemy 2, psycopg 3, Alembic; Redis 7 and ARQ |
| Analysis | DuckDB, NumPy, SciPy, SQLGlot |
| AI | OpenAI Python SDK over a configurable OpenAI-compatible endpoint; optional embeddings for column retrieval |
| Documents | PyMuPDF, WeasyPrint, OpenPyXL, pyreadstat; optional RapidOCR and wordninja |
| Tooling | Docker Compose, pnpm, pytest, Ruff, mypy, ESLint, Prettier, pre-commit, GitHub Actions |

Dependency declarations are in [pyproject.toml](pyproject.toml) and [apps/web/package.json](apps/web/package.json).

```
Browser ── Next.js 16 (App Router, Auth.js) ──── signed 5-minute JWT ───┐
                                                                         ▼
             Redis ◀── enqueue ── FastAPI ──▶ Postgres (projects, profiles, RQs,
               │                     │          insights, chats, llm_calls, queries)
               ▼                     │
           arq worker                └──▶ DuckDB, one file per project,
  ingest → profile → describe                opened read-only by the SQL guard
  assess RQs · generate insights
               │
               └──▶ LLM (any OpenAI-compatible API; Gemini by default)
```

Design rules:

1. **The data stays in DuckDB.** The LLM sees the schema, profile statistics, a few masked sample values and query results, never the raw table. Personal data (emails, phone numbers, IP addresses) is detected and masked before any AI call.
2. **Generated SQL is guarded.** sqlglot allows one `SELECT` over the project's own tables. DuckDB runs read-only, with external access off, a memory limit and a 30-second timeout.
3. **Decisions are deterministic, words are generated.** Verdicts come from rules in `apps/api/rq/verdict.py` and statistics from `apps/api/stats/`. The LLM explains and rewords, and its text is checked against the numbers it was given. If the model fails, rule-based text is used, so a result is never lost.
4. **Everything is traced.** Each AI call (prompt version, tokens, cost, latency, errors) goes to `llm_calls`, and each query to `queries`, linked to the answer, verdict or insight it supports.

| Path | Contents |
|---|---|
| `apps/api/` | FastAPI app, arq worker, profiler, SQL guard, agent, RQ and insight pipelines, report builder |
| `apps/api/prompts/` | Versioned prompts (`rq_parse.v1.md` and others); the version is stored with each call |
| `apps/web/` | Next.js front end |
| `evals/` | Benchmarks, versioned datasets and the eval runner ([evals/README.md](evals/README.md)) |
| `tests/` | Unit and pipeline tests (pytest) |
| [`plan.md`](plan.md), [`PROGRESS.md`](PROGRESS.md), [`DECISIONS.md`](DECISIONS.md) | The plan, its status, and the reasoning behind the verdict and ranking rules |

## Run it locally

Start Docker Desktop (or Docker Engine) first. For the usual development setup, you need Docker Compose v2 and Node.js 24 with the pnpm version declared in `apps/web/package.json`. Python 3.12 is only needed on the host for backend checks or evaluation; the API and worker run in Docker.

### 1. Configure the environment

Copy `.env.example` to `.env` from the repository root. Keep an existing `.env` when restarting the app.

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```sh
# macOS / Linux
cp .env.example .env
```

Set these values in `.env`:

| Variable | Purpose |
|---|---|
| `AUTH_SECRET` | Random secret for Auth.js sessions |
| `API_JWT_SECRET` | Separate random secret shared by the web app and API; add this variable to `.env` because the development example does not include it |
| `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET` | Google OAuth credentials, or use `AUTH_GITHUB_ID` and `AUTH_GITHUB_SECRET` instead |
| `LLM_API_KEY` | API key for AI features |
| `LLM_BASE_URL`, `LLM_MODEL` | Optional provider endpoint and model overrides; defaults are defined in `apps/api/config.py` |
| `LLM_EMBEDDING_MODEL` | Optional embedding model override; set to an empty value to use word matching only |

Generate each secret independently with `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"`. Register the OAuth callback as `http://localhost:3000/api/auth/callback/google` or `http://localhost:3000/api/auth/callback/github`.

Without an AI key, profiling, comparison, combination, template insights and the sample project's mapped question assessments still work. Chat, new question parsing and literature extraction need a working model. The sample project still requires sign-in.

### 2. Start the services

From the repository root:

```sh
docker compose up -d --build
```

This starts PostgreSQL, Redis, the API and the background worker. The API applies database migrations automatically. In a separate terminal, start the frontend:

```sh
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

The frontend normally runs on the host because Docker Desktop on Windows does not forward file-change events reliably. To run the frontend in Docker too, use `docker compose --profile docker-web up -d --build` instead of starting `pnpm dev` on the host.

| Address | Purpose |
|---|---|
| http://localhost:3000 | App; sign in and choose **Try a sample project** |
| http://localhost:8000/docs | Interactive API documentation; project endpoints require authentication |
| http://localhost:8000/health/live | API process health |
| http://localhost:8000/health/ready | PostgreSQL and Redis readiness |

Check containers with `docker compose ps`. Inspect backend logs with `docker compose logs --tail=100 api worker`. Stop the host frontend with Ctrl+C and stop the containers with `docker compose down`; database volumes and local uploaded data are retained.

### Development checks

The GitHub Actions workflow configures backend linting, formatting, typing and tests, plus frontend linting, formatting, typing and a production build.

For backend checks on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe
.\.venv\Scripts\pytest.exe
```

On macOS / Linux:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
```

WeasyPrint PDF reports need native Pango libraries on the host; the API Dockerfile installs these for container use. Optional OCR dependencies are included in the `dev` extra and can also be installed with `pip install -e ".[ocr]"`.

For frontend checks, run `pnpm lint`, `pnpm format:check`, `pnpm typecheck` and `pnpm build` from `apps/web`.

For production deployment, follow [DEPLOY.md](DEPLOY.md) and `.env.prod.example`. The production Compose stack includes a migration job, health checks, OCR and optional Sentry support, and publishes only the web app.

## Evaluation

Install the backend development dependencies and activate the Python 3.12 virtual environment first. On macOS / Linux:

```sh
PYTHONPATH=apps:. python evals/run_eval.py qa         # chat accuracy (execution match against gold SQL)
PYTHONPATH=apps:. python evals/run_eval.py qa --smoke # 15-question smoke set
PYTHONPATH=apps:. python evals/run_eval.py rq         # RQ verdict agreement and mapping precision/recall
PYTHONPATH=apps:. python evals/run_eval.py insights   # insight generation across all datasets
PYTHONPATH=apps:. python evals/run_eval.py lit        # literature extraction with citations
```

On Windows PowerShell, set the module search path once, then run the same evaluator commands without the inline `PYTHONPATH=apps:.` prefix:

```powershell
$env:PYTHONPATH = "apps;."
.\.venv\Scripts\python.exe evals/run_eval.py qa --smoke
```

See [evals/README.md](evals/README.md) for provider configuration, oracle runs and scoring options.

There are 9 versioned development datasets: survey, software defects, time series, timestamps, a 75-column table, leakage and missingness cases, and a deliberately messy export.

### Results so far

These are previously reported development results, not fresh benchmark runs from this documentation update. See [PROGRESS.md](PROGRESS.md) for the testing history and remaining work.

| Benchmark | Result | Caveat |
|---|---|---|
| RQ verdicts with labelled mappings | 13 of 13 cases agree (4 of them unanswerable) | Development set. One rule was added after a disagreement, so this is not an unbiased accuracy. |
| Insights on all 9 datasets | 161 insights, all charted; **0** with a number that cannot be traced to a query | Template wording; the LLM rewording has not been run with a real model |
| Planted effects | A planted strong effect ranks first; 6 pure-noise pairs come out as "no clear evidence" after correction; a planted Simpson's paradox is caught | Unit tests |
| Chat accuracy (31 questions) | Harness passes 31 of 31 with a scripted model | **No real-model run yet.** The gold answers have not been checked by hand. |
| Literature extraction (benchmark D, 5 papers, 65 labelled cells) | Oracle self-test 100% on accuracy, citation precision and recall, and not-found accuracy, including both planted cases | Synthetic papers; **no real-model run yet**. Real papers still need collecting and labelling. |
| Tests | pytest unit and pipeline suite, plus a separate sharing API integration check | The sharing check needs a running API; collect the suite for the current test count. |

The real-model benchmarks (chat accuracy on 120 to 150 questions, planted-issue detection, verdict agreement on 60 hand-labelled pairs) are Phase 5 in [plan.md](plan.md). They need an API key with enough quota and hand-checked labels.

## Limitations

- **Observational data only.** RQ Lens flags causal wording and suggests confounders, but it cannot make an association causal.
- **One table per question.** Feasibility checks and insights work within one table; multi-table questions need a combined dataset first (the Combine feature).
- **Placeholder codes are flagged, not replaced.** Values such as `-999` cannot be told apart from real values without a data dictionary. Upload one to resolve them. A real category spelled `None` is also treated as missing.
- **Candidate keys are single columns.** Composite keys are not detected.
- **Old Excel files.** `.xls` is not read; save it as `.xlsx`. Only the first sheet with data is loaded.
- **The AI steps depend on the model.** Parsing questions, mapping them to columns, and chat quality vary with the model, and have not yet been benchmarked against a real model.
- **Sharing has no notifications.** Owners share by email as viewer or editor, but no email is sent; send the project link yourself. Comments do not notify anyone either.
- **OCR is approximate.** Scanned pages are read with OCR (a few seconds per page, at most 60 pages), which can misread characters; check quotes from OCR'd pages. Equations are skipped, and tables are cited by their caption.
- **Paper metadata is heuristic** unless you import a BibTeX or RIS file. Title and authors come from the first page's layout; correct them when the parser gets them wrong (they are editable).
