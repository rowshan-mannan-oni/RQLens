# RQ Lens: progress checklist

Status of the work in [plan.md](plan.md), item by item. Last updated: 2026-10-06 (after merging main's chat agent).

Legend: `[x]` done and verified · `[~]` partly done (see note) · `[ ]` not started

**Summary**

| Phase | Status |
|---|---|
| 0. Setup | Done |
| 1. Ingestion and profiling | Done; all development datasets load and profile |
| 2. Semantic layer and chat | Built and tested; waiting on a first run with a real model against the 31 questions |
| 3. RQ fit analysis | Done; waiting on a first run with a real model and on review of the verdict rules |
| 4. Insights | Not started |
| 5. Evaluation | Harness and first 31 chat questions in place; benchmarks not run |
| 6. Export, polish, deployment | Project deletion done early; rest not started |

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

- [ ] Planner: bounded list of analysis specs (maximum 20).
- [ ] Runner: SQL plus the fixed statistics library (Spearman, Mann-Whitney U, Kruskal-Wallis, chi-square, trend test, with effect sizes).
- [ ] Benjamini-Hochberg correction; raw and adjusted p-values stored.
- [ ] Ranking by RQ relevance, effect size and sample support.
- [ ] Confounder check for top insights.
- [ ] LLM-written statements with the grounding check.
- [ ] Insights page, including data-quality insights that affect an RQ.

## Phase 5: Evaluation

- [~] A. Chat accuracy: 120 to 150 questions with gold SQL across 8 datasets; execution-match scoring. Scoring and the runner (`evals/run_eval.py`, `evals/scoring.py`) are done and unit-tested; there are 31 of the 120 to 150 questions.
- [ ] B. Planted-issue detection: injector scripts, at least 100 cases, false alarms on clean data. (The profiler already has planted-issue unit tests to build on.)
- [~] C. RQ verdict agreement: 60 hand-labelled dataset and RQ pairs, second labeller on 20. The runner, confusion matrix and mapping precision and recall are done; there are 13 development cases (not reviewed by hand).
- [ ] Experiments 1 to 6, LLM response cache, bootstrap confidence intervals. (`run_eval.py --no-retrieval` covers experiment 6's switch.)
- [ ] CI smoke eval (15 questions per pull request).
- [ ] Error analysis of 30 failures.

## Phase 6: Export, polish, and deployment

- [ ] Dataset report export (Markdown and PDF).
- [ ] Per-user limits: project count, file size, monthly LLM budget.
- [x] Project deletion removes the DuckDB file, uploads, query logs and LLM traces (done early, with dataset deletion).
- [ ] Usage page: cost and latency per project.
- [ ] Empty states, error messages, sample project with a public dataset.
- [ ] Deploy, health checks (the API already has `/health/live` and `/health/ready`), error tracking.
- [ ] README with architecture, results and limitations; 2-minute demo video.

---

## Extra features (added on request)

- [x] **Multi-file upload:** select several CSVs at once; each uploads with its own progress and errors.
- [x] **Compare datasets:** tick any number of datasets to see a column matrix and mismatches across files (type, scale or units, categories, missingness) and how they link.
- [x] **Combine datasets:** stack files with the same columns (with a `source_file` column) or join two on a key (left or inner join). The result is profiled like an upload and can be combined again.
- [x] **Delete with confirmation:** datasets and projects, each behind a confirmation dialog; refused while a dataset is processing.

## Testing status (plan section 8)

| Level | Status |
|---|---|
| Unit | ✅ 191 tests: loader, profiler, statistics, SQL guard, PII and masking, dictionary, describer, combine and compare, agent tools and loop (scripted model), grounding, column retrieval, eval scoring, Benjamini-Hochberg, RQ verdict rules, feasibility checks on real datasets, mapping validation, RQ pipeline (scripted model) |
| Integration | ⚠️ The oracle eval test runs the real loader, profiler, agent loop, guard and executor on real datasets. The full API (Postgres, Redis, worker, streaming chat) was checked with a manual script, not an automated test |
| Security | ⚠️ Malicious SQL tested; prompt injection through column names and cell values, and oversized uploads, not yet tested |
| End to end (Playwright) | ⚠️ The RQ Fit page was driven with Playwright by hand (load, edit mapping, save, rejected filter); no automated suite yet |
| Eval | ⚠️ Harness ready and self-tested; no real-model run yet |

## Known gaps and follow-ups

- The Gemini free tier often answers 429 or 503; description jobs retry automatically (after 30, 60 and 90 s).
- The CI workflow has never run (no remote); pre-commit hooks are not installed.
- Uploads are spooled to a temporary file by the multipart parser before the size check.
- The development database contains test data under `smoke@example.com`.
- The 31 gold answers need checking by hand before any accuracy number is reported.
- The CI smoke eval (15 questions, `run_eval.py --smoke`) needs an `LLM_API_KEY` secret in GitHub before it can run in CI.
- In ames, `Mas_Vnr_Type` shows 61% missing because the value `None` (meaning no veneer) is treated as a missing-value placeholder. This affects real categories that happen to be spelled `None`.
