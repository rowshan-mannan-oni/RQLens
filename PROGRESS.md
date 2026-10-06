# RQ Lens: progress checklist

Status of the work in [plan.md](plan.md), item by item. Last updated: 2026-10-06 (practical additions after Phase 7).

Legend: `[x]` done and verified · `[~]` partly done (see note) · `[ ]` not started

**Summary**

| Phase | Status |
|---|---|
| 0. Setup | Done |
| 1. Ingestion and profiling | Done; all development datasets load and profile |
| 2. Semantic layer and chat | Built and tested; waiting on a first run with a real model against the 31 questions |
| 3. RQ fit analysis | Done; waiting on a first run with a real model and on review of the verdict rules |
| 4. Insights | Done; the AI-assisted planning and wording not yet run with a working model |
| 5. Evaluation | Harness and first 31 chat questions in place; benchmarks not run |
| 6. Export, polish, deployment | Done except the hosted deployment and the demo video (both need your accounts) |
| 7. Literature review (cited extraction) | Built and tested end to end with a scripted model; benchmark D harness in place on 5 synthetic papers; waiting on real papers and a real-model run |

Extra features added on request (not in the plan): multi-file upload, compare and combine datasets, delete with confirmation.

---

## Phase 0: Setup

- [x] Monorepo with Docker Compose: API, worker, Postgres, Redis. The web app runs on the host (`pnpm dev` in `apps/web`) because Docker Desktop on Windows does not pass file changes into containers; a Compose `web` service remains behind `--profile docker-web`.
- [~] Ruff, mypy (strict), pytest, ESLint, Prettier, pre-commit, CI workflow. All configured and passing locally; the CI workflow has never run because the repository has no remote yet, and the pre-commit hooks are not installed (`pre-commit install`).
- [x] Alembic with migrations (5 so far).
- [~] OAuth login and a protected projects page. Google login works; GitHub login code is in place but no GitHub OAuth app has been created.
- [x] `LLMClient` with retries, timeouts, structured output, tool calls, embeddings, cost calculation and trace logging. Failed calls are logged too, with the error in `response_json`.
- [x] Collect 8 to 10 public datasets of different shapes: 8 public datasets plus one messy export derived from one of them, versioned under `evals/datasets/` with sources, licences and checksums in `manifest.json`. Shapes: survey (cps1985, penguins), software repository (ant_defects, PROMISE), time series (flights), timestamps (taxis), wide table (ames, 75 columns), leakage and missingness (titanic, mpg), messy export (messy_survey: semicolons, Latin-1, accented headers, `N/A` and `-999`).

**Done when:** a logged-in user can create a project and one traced LLM call appears in `llm_calls`. ✅ Met.

## Phase 1: Ingestion and profiling

**Ingestion**

- [x] Upload endpoint with a 500 MB size limit, saved to disk under a generated file name.
- [x] Load with DuckDB `read_csv` auto-detection: delimiter, header, quoted newlines; rows that fail to parse are recorded and reported; non-UTF-8 files fall back to Latin-1.
- [x] Sanitise table and column names; keep the original names for display. Accented letters keep their base letter (`Âge` → `age`; it used to become `ge`).
- [x] Several files per project as separate tables (with multi-file upload).
- [~] Fix mis-typed columns. Numbers and dates stored as text are re-typed; placeholder strings (`N/A`, `?`, `.`, `-` …) become missing. Numeric codes such as `-999` are **flagged, not replaced**, because they cannot be told apart from real values without the data dictionary.

**Column profile (pure SQL)**

- [x] Physical type and semantic type: identifier, categorical, numeric, datetime, boolean, free text, constant.
- [x] Missing count and percentage, distinct count, uniqueness ratio.
- [x] Numeric: min, max, mean, median, standard deviation, quantiles, skew, histogram, IQR outliers, share of zeros and negatives.
- [x] Categorical: top values with counts, rare-category count, imbalance ratio.
- [x] Datetime: range, granularity, gaps, counts per period.
- [x] Text: length statistics, blank values, sample values.

**Table profile**

- [~] Row count, exact duplicate rows, candidate keys. Candidate keys are single columns only; multi-column keys are not detected.
- [x] Correlations: Spearman, Cramér's V, correlation ratio (η), on a fixed 50,000-row sample, capped at 25 columns per type.
- [x] Missingness patterns: columns missing together, and missingness that depends on another column.
- [x] Candidate join keys between tables (name match plus value overlap).

**Warnings (rule-based)**

- [x] High missingness, constant columns, near-duplicate columns, extreme imbalance, placeholder values, mixed units, unit change partway through a column, date gaps, possible label leakage, identifier-like columns, rejected rows, encoding fallback.

**UI**

- [x] Profile page: summary tiles, sortable column list, per-column detail with charts, warnings panel, associations, missing-data patterns.
- [x] Progress indicator while background jobs run.

**Done when:** all development datasets load and profile correctly, and the profiler has unit tests against hand-checked fixtures. ✅ Met: all 9 datasets load and profile (largest, ames, in about 2.5 s), and the profiler warnings are plausible (for example, titanic's `survived`/`alive` leakage, ames imbalance, and the messy file's `-999` codes and Latin-1 fallback).

## Phase 2: Semantic layer and chat

**Semantic layer**

- [x] Personal-data detection by column name and value pattern (email, phone, IP); values masked before any LLM call.
- [x] One-line LLM description per column, with a confidence level; low-confidence guesses marked.
- [x] Data dictionary upload (CSV), preferred over AI descriptions.
- [x] User edits of descriptions, which take priority over everything else.
- [x] Per-project switch to stop sending sample values to the LLM (plan section 9).
- [x] Column retrieval for wide tables (more than 50 columns), in `semantic/column_retrieval.py`. Columns are ranked by embedding similarity plus word overlap (with stop words removed), and embeddings are cached in memory. The best 15 columns for the question go into the prompt, and `search_columns` uses the same ranking. If embeddings are unavailable, ranking falls back to word overlap alone. Not yet tried against a real embedding API.

**SQL guard and executor**

- [x] Parse generated SQL with sqlglot; allow a single SELECT only; reject DDL, DML, COPY, ATTACH, PRAGMA, file-reading and system functions, and tables outside the project.
- [x] DuckDB opened read-only with external access disabled, a memory limit, locked configuration and a 30-second timeout.
- [x] Row limit of 200 for results, with the true row count reported.
- [x] Every query logged in `queries`.

**Chat agent**

- [x] Bounded tool loop with streaming output (server-sent events).
- [x] Tools: `get_schema`, `get_column_profile`, `search_columns`, `run_sql`, `run_stat_test`, `make_chart`, `final_answer`.
- [x] Self-correction: SQL errors are returned to the model; the question stops after 3 failed queries.
- [x] Limits: tool calls, failed queries, tokens and time per question. When a limit is hit, the model gets one final turn to answer.
- [x] Grounding check: every number in an answer must appear in a tool result. An answer that fails is sent back once, then flagged. Scientific notation is now handled: `p = 6.6e-54` used to be read as `54` and rejected, and `1.2E-5` was not checked at all.
- [x] Clarifying questions for ambiguous requests (`final_answer` with kind `clarification`).
- [x] Chat UI with answer, chart and a "How this was computed" panel.

**Evaluation set**

- [~] First 30 question and gold-SQL pairs: 31 cases in `evals/qa/questions.v1.jsonl`, covering aggregates, filters, group-by, percentages, time, statistical tests, a join, a wide table, the messy file, one ambiguous and one unanswerable question. The gold results are in `gold.v1.json`. **None has been checked by hand yet** (`reviewed: false`); plan section 13 requires that.

**Done when:** the agent answers the first 30 questions, all SQL guard tests pass (including malicious inputs), and every answer shows its queries. ⚠️ Partly met:

- The SQL guard tests pass.
- Every answer stores and shows its queries.
- The harness passes all 31 cases with a scripted stand-in model (`--llm oracle`).
- A full chat ran end to end through the real API, worker, Postgres and Redis against a scripted model server.
- **Not yet run with a real model**, because no API key was available. Run: `PYTHONPATH=apps:. python evals/run_eval.py qa`.

## Phase 3: RQ fit analysis

The verdict rules are written down in `DECISIONS.md`. Plan section 13 asks you to design and review these yourself, so treat them as a draft.

- [x] Research questions in a project: add, edit, delete and reorder (API); add, delete and reword on the RQ Fit page. At most 20 per project.
- [x] Parse each RQ (LLM, structured output) into type, population, constructs with roles, comparison and time scope (`rq/mapper.py`, prompt `rq_parse.v1`).
- [x] Map constructs to columns (`rq_map.v1`), with match types direct, proxy or derivable (a guarded SQL expression), a justification, a population filter and a time scope. Everything is validated: unknown columns are dropped, and expressions and filters must pass the SQL guard. Wide tables show the mapper only the most relevant columns. The user can accept, change or reject each mapping, and edit the population filter; a change re-runs the later steps without re-mapping.
- [x] Feasibility checks, each a logged query linked as evidence (`rq/feasibility.py`): rows in scope, missing values, complete cases, outcome variation, group sizes (and groups whose outcome never varies), time coverage, a rough power check (minimum detectable d, r or margin), a causal caveat, and possible confounders from the profile's associations. v1 checks one table.
- [x] Rule-based verdict (`rq/verdict.py`, pure and unit-tested). The LLM writes the explanation, method, threats and rewording (`rq_explain.v1`); the grounding check applies, and if the LLM is unavailable the rule messages are used, so a verdict is never lost.
- [x] Suggest additional RQs the data supports (`rq_suggest.v1`); suggestions naming columns that don't exist are dropped.
- [x] RQ Fit page with one card per question: verdict badge, explanation, rewording with "Use this wording", mapping table and editor, evidence with each query's SQL and result, threats, method, and buttons to re-assess, map again or delete. Checked in a browser at desktop and phone widths and in dark mode.

**Done when:** assessments run end to end on 10 dataset-and-RQ pairs, including at least 3 RQs known to be unanswerable. ✅ Met for the measuring and verdict steps:

- 13 labelled pairs in `evals/rq_fit/cases.v1.jsonl`, 4 of them unanswerable, run end to end on real data with labelled mappings: `run_eval.py rq --gold-mapping` gives 13 of 13.
- One rule was added after a disagreement, so that score is not an unbiased accuracy (see `DECISIONS.md`).
- The full app flow (API, worker, Postgres, Redis, web page) was run against a scripted model server.
- ⚠️ Parsing, mapping and explaining have **not been run with a real model yet** (no API key available).

## Phase 4: Insights

The ranking weights and confounder rules are written down in `DECISIONS.md` as a draft for review.

- [x] Planner: at most 20 analysis specs (table, two columns, a test from the library, an optional filter), drawn in order from research-question mappings, the LLM (optional, `insights_plan.v1`) and the profile's strongest associations. Specs are validated against column kinds. Identifiers, row-number columns, personal data, recoded category pairs and near-duplicates are left out, and duplicates count up to aliases (`pclass` and `class`).
- [x] Runner: a guarded, logged query plus the fixed statistics library (Spearman, Mann-Whitney U, Kruskal-Wallis, chi-square, trend) with effect sizes, and a second query shaping the chart.
- [x] Benjamini-Hochberg across all tests in a run; raw and adjusted p-values are stored and shown.
- [x] Ranking by RQ relevance, effect size and sample support, not by p-value. Statuses: finding, significant but negligible, no clear evidence.
- [x] Confounder check for the top 5 findings: re-test within subgroups of associated grouping columns and add a caveat when the pattern reverses or weakens. A planted Simpson's paradox is caught in the tests.
- [x] Statements: a template built from the test's own numbers (always grounded). An optional LLM rewrite (`insights_write.v1`) is kept only if it passes the grounding check. Caveats on every card: exploratory label, sampling, filter, confounders, placeholder codes such as -999, association not cause.
- [x] Insights page: data-quality issues per RQ (from the Phase 3 checks), then ranked findings with chart, statement, effect size, adjusted p, n, caveats, confounder check and queries, then weak or no-evidence results collapsed. Checked in a browser at desktop and phone widths and in dark mode.

**Done when:** insights are generated for all development datasets and no card contains an untraceable number. ✅ Met without an LLM: `run_eval.py insights` produced 161 insights across all 9 datasets, all charted, none failing to run, and **0 with an untraceable number**. A planted strong effect ranks first while 6 pure-noise pairs come out as "no clear evidence" after correction. ⚠️ The AI-assisted plan and rewording have only run against a scripted model: the real key's free-tier quota was exhausted during this session.

## Phase 5: Evaluation

- [~] A. Chat accuracy: 120 to 150 questions with gold SQL across 8 datasets; execution-match scoring. Scoring and the runner (`evals/run_eval.py`, `evals/scoring.py`) are done and unit-tested; there are 31 of the 120 to 150 questions.
- [ ] B. Planted-issue detection: injector scripts, at least 100 cases, false alarms on clean data. (The profiler already has planted-issue unit tests to build on.)
- [~] C. RQ verdict agreement: 60 hand-labelled dataset and RQ pairs, second labeller on 20. The runner, confusion matrix and mapping precision and recall are done; there are 13 development cases (not reviewed by hand).
- [ ] Experiments 1 to 6, LLM response cache, bootstrap confidence intervals. (`run_eval.py --no-retrieval` covers experiment 6's switch.)
- [ ] CI smoke eval (15 questions per pull request).
- [ ] Error analysis of 30 failures.

## Phase 6: Export, polish, and deployment

- [x] Dataset report export, Markdown and PDF (`apps/api/report/`, `GET /projects/{id}/report?format=md|pdf`, download card on the Overview page). Sections: overview, data dictionary (personal-data values hidden), quality warnings, RQ fit, top insights and limitations. The PDF is rendered by WeasyPrint on A4 with page numbers.
- [x] Per-user limits (`apps/api/limits.py`), all set in config (0 means no limit): 20 projects, 50 datasets per project, 500 MB per file, and 2,000 AI calls and $5 per calendar month (UTC), counted from `llm_calls`. Over the AI limit:
  - chat and new questions answer 429 with the reset date;
  - background jobs store the message instead of calling the model;
  - insights fall back to rules and templates.
- [x] Project deletion removes the DuckDB file, uploads, query logs and LLM traces (done early, with dataset deletion).
- [x] Usage page (`/usage`, `GET /usage?period=month|all`): monthly meters for calls and spend, then per project the AI calls, failed calls, tokens, cost, average and p95 latency, queries with average time, and calls per pipeline step.
- [x] Empty states and error messages reviewed across pages. **Sample project**: "Try a sample project" creates *Sample: Palmer penguins* with three ready-mapped questions (answerable, answerable, not answerable). It works without an AI key: questions with a mapping are measured and decided by the rules, and questions waiting for data are assessed once a dataset is ready.
- [~] Deployment. Built and run end to end:
  - production stack in `docker-compose.prod.yml`, with a migration job, healthchecks on every service, and only the web app published;
  - web image `apps/web/Dockerfile` (Next.js standalone output, non-root user);
  - optional Sentry error tracking (`SENTRY_DSN`, `apps/api/observability.py`, no request bodies or user data sent);
  - guide in `DEPLOY.md` covering TLS, backups and platforms without Compose.

  The stack was built and run here: all six containers became healthy, and the sample project ran from sign-in to verdicts. **Not done:** deploying to a real host, which needs your server or Railway/Fly.io account, a domain and OAuth callback URLs. Note: Debian's package mirror is blocked in this sandbox, so the test image skipped the PDF libraries; the PDF report itself was tested outside Docker.
- [~] README with architecture, results and limitations (`README.md`). The 2-minute demo video is yours to record.

---

## Phase 7: Literature review with cited extraction

A second module in each project, on the new **Literature** tab: papers become a review table where every value cites the sentences it came from, and the citations are checked against the paper.

**Step 1: Bring in the papers**

- [x] Upload many PDFs at once, or a whole folder: the folder picker and drag-and-drop of a folder both upload every PDF inside it (other files are ignored), three at a time, keeping the subfolder path as a label.
- [x] Limits: 50 MB per PDF, 200 papers per project (settings). Duplicates are detected by SHA-256 and skipped with "Already in this project as …". Files that are not PDFs are refused.
- [ ] Optional later: BibTeX, RIS or Zotero import.

**Step 2: Parse each paper into citable passages** (`apps/api/papers/parser.py`)

- [x] Text with positions (PyMuPDF, character by character); running headers, footers, page numbers and rotated margin stamps removed; hyphenated line breaks joined.
- [x] Passages: one per sentence, never across pages, labelled `P3-S12`, each with its page, section and one rectangle per line. Paragraphs that continue across blocks or columns stay whole.
- [x] Sections from heading words, numbering and font (including "Abstract—" inline). Reference entries are kept but never sent to the model or cited.
- [x] Metadata (title, authors, year, venue, DOI) from the PDF's metadata and its first page. Editable; corrections survive re-reading.
- [x] Scanned PDFs are detected and marked "needs OCR". OCR itself is not done.
- [x] Two-column layouts read in column order; captions are one passage. Equations are skipped rather than shown as image regions.
- [~] Unit tests on single- and two-column papers, a scanned paper and reference lists, using **generated** papers (`evals/literature/synth.py`), because this sandbox cannot download open-access PDFs. Real PDFs should be added.

**Step 3: Templates** (`apps/api/review/templates.py`)

- [x] Built-in literature review template with the 13 columns of the plan, each with instructions.
- [x] User templates: add, remove, rename, reorder columns; label, instructions, kind (text, list, number, category with options), required, and "fill from the PDF's details". Reusable across projects. Editor at Literature → "Make or edit your own template".
- [x] More built-ins: empirical software engineering, clinical study (PICO), systematic review screening.
- [x] Add a column to an existing table; only that column is extracted.

**Step 4: Extraction with citations** (`apps/api/review/extract.py`, `citations.py`)

- [x] One call per paper with the columns and the numbered passages; the reply gives, per column, a value, cited passage IDs with quotes, a confidence, or not found with a reason (prompt `review_extract.v1`).
- [x] Unknown passage IDs are dropped; references are never offered.
- [x] Citation check without an LLM: exact match after normalising case, spacing, quotes, dashes and hyphenation, or fuzzy ≥ 0.9; numbers must appear in the cited passages; categories must be an option. Failing cells are retried once with the problems listed, then marked **unverified**.
- [x] Long papers (over 60,000 characters) send the abstract, conclusion and the most relevant passages per column (words, section headings, embeddings when available).
- [x] Metadata columns come from the parsed PDF first, cited to the first page, with no AI call.
- [x] One background job per paper and table; transient provider errors retry (30, 60, 90 s); cells fill in as jobs finish; new papers are added to existing tables automatically.
- [x] Every call is traced in `llm_calls` (step `review_extract`, prompt version); the Usage page shows it. Over the monthly AI limit, metadata cells still fill and the rest say why.

**Step 5: The review table and the reader**

- [x] Table: sticky paper column and header, resizable and pinnable columns (remembered per browser), sort by any column, text filter, filters for "needs attention", "not found" and "edited", long cells clamped with "show more", markers for not found, unverified, edited, accepted and low confidence.
- [x] Citation markers `[1] [2]` with the quote and page on hover; clicking opens the **reader**.
- [x] Reader: PDF.js side panel at the cited page, the passage's line rectangles highlighted, previous/next citation, page navigation, and the passage text above the PDF with the quote marked (so a citation still reads if the PDF fails to render). Uses PDF.js's legacy build, because the modern one needs JavaScript features many current browsers lack.
- [x] Editing: change any cell (lists one item per line, numbers, category options); edits are never overwritten; go back to the AI value; accept or reject; re-run a cell, a column, a paper or the table.
- [x] Export: CSV (with a citations column), Excel (with a Citations sheet: paper, column, passage, page, quote, verified), Markdown with numbered citations, BibTeX.
- [ ] Later: chat across papers with the same citations.

**Step 6: Connect to the rest of RQ Lens**

- [x] Papers related to a research question: choose an RQ in the table toolbar to see the papers whose problem, questions or findings share its terms, with the matching cells shaded (no LLM; see `DECISIONS.md`).
- [x] The dataset report has an appendix with the newest literature table: per paper, each value with the pages it cites, unverified values marked, and the fields the paper does not state.

**Evaluation (benchmark D)** (`evals/lit_eval.py`, `run_eval.py lit`)

- [~] 5 synthetic papers of different layouts and fields (software engineering, health, ML, a clinical trial, a qualitative study) with all 65 cells labelled. The plan's 20 to 30 **real** open-access papers still need collecting and labelling by hand; the runner accepts real PDFs in `evals/literature/pdfs/`.
- [x] Metrics: cell accuracy (key-term rubric; an LLM judge is not built), citation precision and recall, not-found accuracy, unverified rate, cost, time and calls per paper.
- [x] Planted cases: a paper with no limitations section, and a paper whose abstract and results disagree.
- [x] Experiments wired: 7 (`--retrieval`), 8 (`--no-check`), 9 (`--model`).
- [x] Oracle self-test: 100% on every metric across all 5 papers, so the parser, the check and the scoring agree.

**Done when:** a folder of 20 papers becomes a filled table in under 5 minutes, every non-empty cell's citation opens the right page with the sentence highlighted, benchmark D runs end to end, and custom templates work the same way. ⚠️ Partly met:

- Folder upload, filling, the reader with highlights, and custom templates work end to end in the browser, against the real API, worker, Postgres and Redis with a scripted model server.
- Benchmark D runs end to end (oracle).
- **Not yet run with a real model**, and not yet timed on 20 real papers.

## Practical additions (after Phase 7)

- [x] **Data formats:** Excel (.xlsx), SPSS (.sav, .zsav, .por), Stata (.dta) and Parquet, besides CSV. SPSS/Stata variable labels fill the data dictionary; value labels and user-defined missing values are handled (see `DECISIONS.md`). Tested on SPSS and Stata fixtures, a generated workbook and Parquet, and through the real upload pipeline.
- [x] **OCR for scanned papers** (RapidOCR, pip-only): scanned pages are read automatically, with positions, so citations still highlight the line. Tested on generated scans: title, authors, sections and sentences come out right. About 4-6 s per page on CPU. Production image installs the `ocr` extra.
- [x] **Reference import:** BibTeX and RIS (Zotero, Mendeley, EndNote). Matches by DOI or title, fills metadata and citation keys (used by the BibTeX export), and matches PDFs uploaded later. Lists the file names of entries still waiting for a PDF.
- [x] **Sharing and comments:** viewers and editors by email, role-based access on every route, "Shared with you" projects, a People/Share dialog, comment threads on the project, research questions and literature cells, with resolve. Viewers do not see edit controls. 27 access checks run against the real API (`tests/integration/test_sharing_api.py`, needs a running API); browser-checked as owner and viewer.
- [ ] No email notifications for invitations or comments (no email service).

## Extra features (added on request)

- [x] **Multi-file upload:** select several CSVs at once; each uploads with its own progress and errors.
- [x] **Compare datasets:** tick any number of datasets to see a column matrix and mismatches across files (type, scale or units, categories, missingness) and how they link.
- [x] **Combine datasets:** stack files with the same columns (with a `source_file` column) or join two on a key (left or inner join). The result is profiled like an upload and can be combined again.
- [x] **Delete with confirmation:** datasets and projects, each behind a confirmation dialog; refused while a dataset is processing.

## Testing status (plan section 8)

| Level | Status |
|---|---|
| Unit | ✅ 275 tests: loader, profiler, statistics, SQL guard, PII and masking, dictionary, describer, combine and compare, agent tools and loop (scripted model), grounding, column retrieval, eval scoring, Benjamini-Hochberg, RQ verdict rules, feasibility checks on real datasets, mapping validation, RQ pipeline (scripted model), insight planning, ranking, correction, confounders, planted effects, PDF parsing (generated papers), citation check, extraction with retry (scripted model), exports, RQ linking, benchmark D oracle |
| Integration | ⚠️ The oracle eval test runs the real loader, profiler, agent loop, guard and executor on real datasets. The full API (Postgres, Redis, worker, streaming chat) was checked with a manual script, not an automated test |
| Security | ⚠️ Malicious SQL tested; prompt injection through column names and cell values, and oversized uploads, not yet tested |
| End to end (Playwright) | ⚠️ The RQ Fit page was driven with Playwright by hand (load, edit mapping, save, rejected filter); no automated suite yet |
| Eval | ⚠️ Harness ready and self-tested; no real-model run yet |

## Known gaps and follow-ups

- The Gemini free tier often answers 429 or 503; description jobs retry automatically (after 30, 60 and 90 s).
- The CI workflow has never run (no remote); pre-commit hooks are not installed.
- Uploads are spooled to a temporary file by the multipart parser before the size check.
- The development database contains test data under `smoke@example.com`.
- An `LLM_API_KEY` is now set in the cloud environment, but its free tier (20 requests a day for this model) is too small for the full benchmarks: one QA run needs well over 100 calls.
- The 31 gold answers need checking by hand before any accuracy number is reported.
- The CI smoke eval (15 questions, `run_eval.py --smoke`) needs an `LLM_API_KEY` secret in GitHub before it can run in CI.
- In ames, `Mas_Vnr_Type` shows 61% missing because the value `None` (meaning no veneer) is treated as a missing-value placeholder. This affects real categories that happen to be spelled `None`.
