# RQ Lens: progress checklist

Status of the work in [plan.md](plan.md), item by item. Last updated: 2026-10-06.

Legend: `[x]` done and verified · `[~]` partly done (see note) · `[ ]` not started

**Summary**

| Phase | Status |
|---|---|
| 0. Setup | Done, except collecting the development datasets |
| 1. Ingestion and profiling | Done |
| 2. Semantic layer and chat | Part 1 done (semantic layer, SQL guard); chat agent not started |
| 3. RQ fit analysis | Not started |
| 4. Insights | Not started |
| 5. Evaluation | Not started |
| 6. Export, polish, deployment | Project deletion done early; rest not started |

Extra features added on request (not in the plan): multi-file upload, compare and combine datasets, delete with confirmation.

---

## Phase 0: Setup

- [x] Monorepo with Docker Compose: API, worker, Postgres, Redis. The web app runs on the host (`pnpm dev` in `apps/web`) because Docker Desktop on Windows does not pass file changes into containers; a Compose `web` service remains behind `--profile docker-web`.
- [~] Ruff, mypy (strict), pytest, ESLint, Prettier, pre-commit, CI workflow. All configured and passing locally; the CI workflow has never run because the repository has no remote yet, and the pre-commit hooks are not installed (`pre-commit install`).
- [x] Alembic with migrations (5 so far).
- [~] OAuth login and a protected projects page. Google login works; GitHub login code is in place but no GitHub OAuth app has been created.
- [~] `LLMClient` with retries, timeouts, structured output, cost calculation and trace logging. Done; calls that fail with an exception are not yet written to `llm_calls`.
- [ ] Collect 8 to 10 public datasets of different shapes for development and evaluation.

**Done when:** a logged-in user can create a project and one traced LLM call appears in `llm_calls`. ✅ Met.

## Phase 1: Ingestion and profiling

**Ingestion**

- [x] Upload endpoint with a 500 MB size limit, saved to disk under a generated file name.
- [x] Load with DuckDB `read_csv` auto-detection: delimiter, header, quoted newlines; rows that fail to parse are recorded and reported; non-UTF-8 files fall back to Latin-1.
- [x] Sanitise table and column names; keep the original names for display.
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

**Done when:** all development datasets load and profile correctly, and the profiler has unit tests against hand-checked fixtures. ⚠️ Partly met: the hand-checked tests exist and pass; the development datasets have not been collected yet (Phase 0).

## Phase 2: Semantic layer and chat

**Semantic layer**

- [x] Personal-data detection by column name and value pattern (email, phone, IP); values masked before any LLM call.
- [x] One-line LLM description per column, with a confidence level; low-confidence guesses marked.
- [x] Data dictionary upload (CSV), preferred over AI descriptions.
- [x] User edits of descriptions, which take priority over everything else.
- [x] Per-project switch to stop sending sample values to the LLM (plan section 9).
- [ ] Column retrieval (embeddings) for wide tables of more than about 50 columns.

**SQL guard and executor**

- [x] Parse generated SQL with sqlglot; allow a single SELECT only; reject DDL, DML, COPY, ATTACH, PRAGMA, file-reading and system functions, and tables outside the project.
- [x] DuckDB opened read-only with external access disabled, a memory limit, locked configuration and a 30-second timeout.
- [x] Row limit of 200 for results, with the true row count reported.
- [x] Every query logged in `queries`.

**Chat agent**

- [ ] Bounded tool loop with streaming output.
- [ ] Tools: `get_schema`, `get_column_profile`, `search_columns`, `run_sql`, `run_stat_test`, `make_chart`, `final_answer`.
- [ ] Self-correction: return SQL errors to the model, up to 3 retries.
- [ ] Limits: tool calls, token budget, wall-clock time per question.
- [ ] Grounding check: every number in an answer must appear in a tool result.
- [ ] Clarifying questions for ambiguous requests.
- [ ] Chat UI with answer, chart and a "How this was computed" panel.

**Evaluation set**

- [ ] First 30 question and gold-SQL pairs.

**Done when:** the agent answers the first 30 questions, all SQL guard tests pass (including malicious inputs), and every answer shows its queries. ⚠️ Partly met: the SQL guard tests pass (31 malicious inputs blocked); the agent does not exist yet.

## Phase 3: RQ fit analysis

- [ ] Parse each RQ into a structured form (type, population, constructs, comparison, time scope).
- [ ] Map constructs to columns (direct, proxy, derivable) and mark gaps; user can accept, change or reject mappings.
- [ ] Feasibility checks with queries: rows after filters, missingness, group sizes, outcome variance, time coverage, rough power check, causal caveats.
- [ ] Rule-based verdict (answerable, partial, not answerable) with LLM-written explanation, evidence linked to queries, suggested method, threats, and a reworded RQ.
- [ ] Suggest additional RQs the data supports.
- [ ] RQ Fit page with one card per RQ; editing re-runs the assessment.

## Phase 4: Insights

- [ ] Planner: bounded list of analysis specs (maximum 20).
- [ ] Runner: SQL plus the fixed statistics library (Spearman, Mann-Whitney U, Kruskal-Wallis, chi-square, trend test, with effect sizes).
- [ ] Benjamini-Hochberg correction; raw and adjusted p-values stored.
- [ ] Ranking by RQ relevance, effect size and sample support.
- [ ] Confounder check for top insights.
- [ ] LLM-written statements with the grounding check.
- [ ] Insights page, including data-quality insights that affect an RQ.

## Phase 5: Evaluation

- [ ] A. Chat accuracy: 120 to 150 questions with gold SQL across 8 datasets; execution-match scoring.
- [ ] B. Planted-issue detection: injector scripts, at least 100 cases, false alarms on clean data. (The profiler already has planted-issue unit tests to build on.)
- [ ] C. RQ verdict agreement: 60 hand-labelled dataset and RQ pairs, second labeller on 20.
- [ ] Experiments 1 to 6, LLM response cache, bootstrap confidence intervals.
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
| Unit | ✅ 91 tests: loader, profiler, statistics against hand calculations and scipy, SQL guard, PII and masking, dictionary, describer, combine and compare |
| Integration | ⚠️ Checked with manual end-to-end scripts only; no automated tests against a real database yet |
| Security | ⚠️ Malicious SQL tested; prompt injection through column names and cell values, and oversized uploads, not yet tested |
| End to end (Playwright) | ❌ Not started |
| Eval | ❌ Not started |

## Known gaps and follow-ups

- Failed LLM calls (exceptions) are not logged in `llm_calls`; needed before the chat agent's cost and retry metrics.
- The Gemini free tier often answers 429 or 503; description jobs retry automatically (after 30, 60 and 90 s).
- The CI workflow has never run (no remote); pre-commit hooks are not installed.
- Uploads are spooled to a temporary file by the multipart parser before the size check.
- `DECISIONS.md` (one line per design choice, suggested in plan section 13) has not been started.
- The development database contains test data under `smoke@example.com`.
