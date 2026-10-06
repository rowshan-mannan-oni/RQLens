# Plan: Research Dataset Companion

Working name: **RQ Lens** (rename freely).

## 1. Summary

A web app for researchers. The user enters a research topic or research questions (RQs) and uploads a dataset. The app profiles the whole dataset with code, judges whether the data can answer each RQ, surfaces insights related to the RQs, and answers follow-up questions in chat. Every number shown comes from a query that was executed and can be inspected.

### The problem

A researcher cannot read a large dataset row by row, yet the dataset decides which questions can be answered. Problems such as missing variables, small subgroups, or biased sampling are often found late, after the research design is fixed.

### Goals

- Give a researcher an accurate picture of a dataset in under 5 minutes.
- For each RQ, state whether the data can answer it, with evidence.
- Answer free-form questions about the data with verifiable numbers.
- Measure all three with reproducible benchmarks.

### Non-goals (v1)

- Running the final statistical analysis for a paper. The tool is for understanding and planning.
- Image, audio, or free-text corpora (see section 12).
- Live database connections. v1 accepts CSV files only.
- Data cleaning or editing. The dataset is read-only.

### Two design rules

1. **Every number comes from an executed query.** The LLM writes queries and interprets results. It never states a statistic from memory.
2. **Insights are labelled exploratory.** A tool that scans many patterns will find some by chance. Insights are presented as hypotheses to test, with effect sizes and caveats.

### Target metrics

Set real targets after the first benchmark run. Starting placeholders:

| Metric | Placeholder target |
|---|---|
| Chat answer accuracy (execution match) | 80% or higher |
| Planted-issue detection recall | 85% or higher |
| False alarms on clean datasets | Under 1 per dataset |
| RQ verdict agreement with hand labels | 75% or higher |
| Numeric claims traceable to a query | 100% |
| Time to first profile (100 MB CSV) | Under 60 seconds |

---

## 2. User flow

1. Create a project and enter a topic and one or more RQs.
2. Upload one or more CSV files. Optionally upload a data dictionary.
3. Review the **Profile** page: columns, types, missing values, distributions, warnings.
4. Review and edit the generated column descriptions.
5. Open the **RQ Fit** page: one card per RQ with a verdict, mapped columns, evidence, and gaps.
6. Open the **Insights** page: ranked findings linked to RQs, each with a chart and its query.
7. Ask follow-up questions in **Chat**.
8. Export a dataset report (Markdown or PDF).

---

## 3. Architecture

```
Browser (Next.js)
     │ REST + SSE (streaming)
     ▼
API (FastAPI) ───enqueue──> Redis ──> Worker
     │                                  ├─ Ingestion (CSV to DuckDB)
     │                                  ├─ Profiler (deterministic SQL, no LLM)
     │                                  ├─ Describer (LLM column descriptions)
     │                                  ├─ RQ analyser (LLM + queries)
     │                                  └─ Insight generator (LLM + queries + stats)
     │
     ├─ Chat agent (LLM + tools, streamed)
     ├─ Postgres: users, projects, RQs, profiles, insights, chats, traces
     └─ DuckDB: one file per project holding the uploaded data (opened read-only)
```

**Key decisions**

- **DuckDB holds the data.** It reads CSVs directly, handles files larger than memory, and runs analytical SQL fast. One `.duckdb` file per project keeps users isolated.
- **Profiling uses no LLM.** It is plain SQL, so it is cheap, exact, and testable.
- **The LLM sees metadata, not the dataset.** It receives the schema, profile statistics, a few masked sample values, and query results.
- **Statistics come from a fixed tool library,** not free-form Python. This is safer than running generated code and easier to test.
- **Every LLM call and query is traced** for the dashboard, for debugging, and for the evaluation.

### Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Frontend | Next.js (App Router), TypeScript, Tailwind, shadcn/ui, Recharts | Fast to generate with AI coding tools |
| Backend | Python 3.12, FastAPI, Pydantic v2 | Typing and good LLM SDK support |
| Data engine | DuckDB | Analytical SQL over CSV files |
| App database | Postgres, SQLAlchemy 2, Alembic | Standard |
| Jobs | Redis + arq | Profiling and analysis run in the background |
| SQL validation | sqlglot | Parse and restrict generated SQL |
| Statistics | scipy, statsmodels | Tests and effect sizes |
| LLM | Provider API with tool use and structured output | Check current models and prices before starting |
| Auth | Google or GitHub OAuth (Auth.js) | Simple |
| Deploy | Docker Compose; Railway, Fly.io, or a small VPS | Low cost |
| CI | GitHub Actions | Lint, types, tests, smoke eval |

---

## 4. Repository layout

```
rq-lens/
├── apps/
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/          # projects.py, uploads.py, profile.py, rqs.py, insights.py, chat.py, export.py
│   │   ├── ingest/          # loader.py, type_inference.py
│   │   ├── profiler/        # columns.py, tables.py, relationships.py, warnings.py
│   │   ├── semantic/        # describer.py, pii.py, column_retrieval.py
│   │   ├── rq/              # parser.py, mapper.py, feasibility.py, verdict.py
│   │   ├── insights/        # planner.py, runner.py, ranking.py
│   │   ├── agent/           # loop.py, tools.py, prompts/, grounding.py
│   │   ├── sql/             # guard.py, executor.py
│   │   ├── stats/           # tests.py, effect_sizes.py, corrections.py
│   │   ├── llm/             # client.py, pricing.py, tracing.py
│   │   ├── db/              # models.py, migrations/
│   │   └── worker.py
│   └── web/                 # Next.js app
├── evals/
│   ├── qa/                  # questions with gold SQL and answers
│   ├── planted/             # issue injectors and clean base datasets
│   ├── rq_fit/              # dataset and RQ pairs with hand labels
│   ├── run_eval.py
│   └── reports/
├── tests/
├── docker-compose.yml
├── plan.md
└── README.md
```

---

## 5. Data model (Postgres)

```sql
users (id, email, name, created_at)

projects (id, user_id, title, topic, status, duckdb_path, created_at)

research_questions (id, project_id, text, parsed_json, position, created_at)

datasets (id, project_id, table_name, original_filename, row_count, column_count,
          size_bytes, load_warnings_json, created_at)

columns (id, dataset_id, name, physical_type, semantic_type,
         description, description_source,      -- llm | user | dictionary
         is_pii, profile_json)

table_profiles (id, dataset_id, profile_json, warnings_json, created_at)

rq_assessments (id, rq_id, verdict,            -- answerable | partial | not_answerable
                mapped_columns_json, evidence_json, gaps_json,
                suggested_method, threats_json, config_version, created_at)

insights (id, project_id, rq_id, title, statement, kind, effect_size, p_value,
          p_adjusted, score, sql, result_json, chart_json, caveats_json, created_at)

chats (id, project_id, title, created_at)
messages (id, chat_id, role, content, chart_json, created_at)

queries (id, project_id, message_id, insight_id, rq_assessment_id,
         sql, row_count, duration_ms, error, result_preview_json, created_at)

llm_calls (id, project_id, eval_run_id, step, model, prompt_version,
           input_tokens, output_tokens, cost_usd, latency_ms,
           request_json, response_json, created_at)

eval_runs (id, suite, dataset_version, config_json, git_sha, metrics_json, created_at)
eval_results (id, eval_run_id, case_id, passed, details_json, cost_usd)
```

---

## 6. Phases

Estimates assume about 15 hours per week. Total: about 11 weeks.

### Phase 0: Setup (week 1)

- [ ] Monorepo, Docker Compose (api, worker, postgres, redis, web).
- [ ] Ruff, mypy, pytest, ESLint, Prettier, pre-commit, CI workflow.
- [ ] Alembic with the first migration.
- [ ] OAuth login and a protected projects page.
- [ ] `LLMClient` with retries, timeouts, structured output, cost calculation, and trace logging.
- [ ] Collect 8 to 10 public datasets of different shapes for development and evaluation (survey data, software repository data, time series, wide tables, messy exports).

**Done when:** a logged-in user can create a project and one traced LLM call appears in `llm_calls`.

### Phase 1: Ingestion and profiling (weeks 2 to 3)

**Ingestion**

- [ ] Upload endpoint with a size limit (start at 500 MB) and streaming to disk.
- [ ] Load with DuckDB `read_csv` auto-detection. Handle delimiter, encoding, header detection, and quoted newlines. Record rows that failed to parse.
- [ ] Sanitise table and column names. Keep the original names for display.
- [ ] Support several files per project as separate tables.
- [ ] Fix mis-typed columns: numbers stored as text, dates as text, placeholder values such as `-999`, `N/A`, or `?` that mean missing.

**Column profile (pure SQL)**

- [ ] Physical type and semantic type: identifier, categorical, numeric, datetime, boolean, free text, constant.
- [ ] Missing count and percentage, distinct count, uniqueness ratio.
- [ ] Numeric: min, max, mean, median, standard deviation, quantiles, skew, histogram bins, outlier count (IQR rule), share of zeros and negatives.
- [ ] Categorical: top values with counts, rare-category count, imbalance ratio.
- [ ] Datetime: range, granularity, gaps, counts per period.
- [ ] Text: length statistics, share of empty strings, sample values.

**Table profile**

- [ ] Row count, exact duplicate rows, candidate keys.
- [ ] Correlations: Spearman for numeric pairs, Cramér's V for categorical pairs, correlation ratio for mixed pairs. Cap the number of pairs on wide tables.
- [ ] Missingness patterns: columns that are missing together; missingness that depends on another column.
- [ ] Candidate join keys between tables (matching names and overlapping values).

**Warnings (rule-based)**

- [ ] High missingness, constant columns, near-duplicate columns, extreme imbalance, suspicious placeholder values, mixed units, date gaps, possible label leakage (a column that almost perfectly predicts another), identifier-like columns.

**UI**

- [ ] Profile page: table overview, sortable column list, per-column detail with a chart, and a warnings panel.
- [ ] Progress indicator while the background job runs.

**Done when:** all development datasets load and profile correctly, and the profiler has unit tests against small hand-checked CSV fixtures.

### Phase 2: Semantic layer and chat (weeks 4 to 5)

**Semantic layer**

- [ ] PII detection by pattern and column name (emails, phone numbers, names, IDs). Mask sample values from flagged columns before any LLM call.
- [ ] Generate a one-line description per column from its name, profile, and masked samples. Mark low-confidence guesses.
- [ ] Parse an optional data dictionary upload and prefer it over generated descriptions.
- [ ] Let the user edit descriptions. User edits take priority.
- [ ] For wide tables (more than about 50 columns), embed column descriptions and retrieve only the relevant columns per question.

**SQL guard and executor**

- [ ] Parse generated SQL with sqlglot. Allow a single `SELECT` statement only. Reject DDL, DML, `COPY`, `ATTACH`, `PRAGMA`, and file-reading functions.
- [ ] Open DuckDB in read-only mode with external access disabled, a memory limit, and a query timeout.
- [ ] Add a row limit to results returned to the model (for example 200 rows) and report the true row count.
- [ ] Log every query in `queries`.

**Chat agent**

- [ ] Bounded tool loop with streaming output.

| Tool | Purpose |
|---|---|
| `get_schema` | Tables, columns, types, descriptions |
| `get_column_profile` | Full profile of one column |
| `search_columns` | Find columns by meaning on wide tables |
| `run_sql` | Execute a guarded query and return rows |
| `run_stat_test` | Run a named test from the fixed library |
| `make_chart` | Return a chart spec (type, x, y, series) rendered by the frontend |
| `final_answer` | End the loop with the answer and references to queries |

- [ ] Self-correction: on a SQL error, return the error to the model and allow up to 3 retries.
- [ ] Limits: maximum tool calls, token budget, and wall-clock time per question.
- [ ] **Grounding check:** after the answer is produced, extract every number in it and confirm each one appears in a tool result (allowing for rounding). If a number is unsupported, regenerate once, then flag the answer.
- [ ] Ask a clarifying question when the request is ambiguous (for example, "average" of which column).
- [ ] Chat UI: answer text, chart, and an expandable "How this was computed" panel with the SQL and result table.

**Start the evaluation set now:** write 30 question and gold-SQL pairs while building. See Phase 5.

**Done when:** the agent answers the first 30 questions, all SQL guard tests pass (including malicious inputs), and every answer shows its queries.

### Phase 3: RQ fit analysis (weeks 6 to 7)

This is the feature that sets the project apart. Give it the most care.

**Step 1: Parse each RQ** into a structured form with an LLM call:

```json
{
  "type": "descriptive | comparative | correlational | predictive | causal",
  "population": "who or what is studied",
  "constructs": [
    {"name": "developer experience", "role": "independent"},
    {"name": "bug-fix time", "role": "dependent"}
  ],
  "comparison": "groups or conditions, if any",
  "time_scope": "period, if any"
}
```

**Step 2: Map constructs to columns.**

- [ ] For each construct, propose candidate columns with a match type: `direct`, `proxy`, or `derivable` (computed from other columns), plus a short justification.
- [ ] Mark constructs with no match as gaps.
- [ ] Let the user accept, change, or reject each mapping. Re-run the later steps after changes.

**Step 3: Run feasibility checks with queries.** Chosen by RQ type:

- [ ] Rows remaining after population and time filters.
- [ ] Missingness in mapped columns, and rows with all mapped columns present.
- [ ] Group sizes for comparisons, with a warning for small or very unequal groups.
- [ ] Variance of the outcome (a near-constant outcome cannot be explained).
- [ ] Time coverage against the RQ's time scope.
- [ ] Rough power check: smallest effect detectable with the available sample.
- [ ] For causal RQs: state that observational data supports association only, and list available confounder columns.

**Step 4: Produce the verdict.**

- [ ] `answerable`, `partial`, or `not_answerable`, decided by explicit rules over the check results, with the LLM writing the explanation. Rules make the verdict consistent and testable.
- [ ] Output per RQ: verdict, mapped columns, evidence (each item linked to a query), gaps, suggested analysis method, threats to validity, and a suggested rewording of the RQ if the current one cannot be answered.

**Step 5: Suggest additional RQs** that the dataset could support, each with the columns it would use.

**UI**

- [ ] RQ Fit page with one card per RQ: verdict badge, mapping table, evidence list, gaps, threats.
- [ ] Editing an RQ or a mapping re-runs the assessment.

**Done when:** assessments run end to end on 10 dataset and RQ pairs, including at least 3 RQs you know to be unanswerable.

### Phase 4: Insights (week 8)

- [ ] **Planner:** the LLM proposes a bounded list of analyses (maximum 20) from the RQs, mappings, and profile. Each is a structured spec: columns, test, and reason. No free-form code.
- [ ] **Runner:** execute each spec with SQL and the statistics library.

| Situation | Test | Effect size |
|---|---|---|
| Two numeric columns | Spearman correlation | rho |
| Numeric across two groups | Mann-Whitney U | Cliff's delta |
| Numeric across several groups | Kruskal-Wallis | epsilon squared |
| Two categorical columns | Chi-square | Cramér's V |
| Numeric over time | Trend test | Slope |

- [ ] **Multiple-testing correction:** apply Benjamini-Hochberg across all tests in a run. Store raw and adjusted p-values.
- [ ] **Ranking:** score by relevance to an RQ, effect size, and sample support. Do not rank by p-value alone.
- [ ] **Confounder check:** for the top insights, test whether the relationship holds within subgroups of likely confounders, and add a caveat if it changes.
- [ ] **Writing:** the LLM writes a one-sentence statement and caveats from the result. Apply the grounding check.
- [ ] Insights page: ranked cards with chart, statement, effect size, the "exploratory" label, caveats, and the query.
- [ ] Include data-quality insights that affect an RQ (for example, "the outcome is missing for 40% of the treatment group").

**Done when:** insights are generated for all development datasets and no card contains an untraceable number.

### Phase 5: Evaluation (weeks 9 to 10)

Three benchmarks. Version each dataset file and never edit a version in place.

**A. Chat accuracy**

- [ ] 120 to 150 questions across 8 datasets, each with gold SQL and a gold answer. Cover: simple aggregates, filters, group-by, joins, time questions, percentages, questions needing a statistical test, ambiguous questions, and unanswerable questions.
- [ ] Score by execution match: compare the agent's result with the gold result (order-insensitive, with numeric tolerance).
- [ ] For unanswerable questions, the correct behaviour is to say so.
- [ ] Also report grounding rate, cost, latency, and number of retries.

**B. Planted-issue detection**

- [ ] Take clean datasets and inject known problems with scripts: random missingness, missingness that depends on another column, duplicate rows, a leaked label, outliers, a unit change partway through, class imbalance, a date gap, placeholder values.
- [ ] Measure recall per issue type across at least 100 injected cases.
- [ ] Run the clean versions too and count false alarms.

**C. RQ verdict agreement**

- [ ] 60 dataset and RQ pairs with hand-labelled verdicts and expected column mappings. Include about one third unanswerable or partial cases.
- [ ] Report verdict accuracy, a confusion matrix, and mapping precision and recall.
- [ ] If possible, have a second person label 20 pairs and report agreement, so the labels are credible.

**Experiments**

| # | Comparison | Question answered |
|---|---|---|
| 1 | Schema only versus schema plus profile | Does the profile help the model write correct SQL? |
| 2 | With versus without column descriptions | Value of the semantic layer |
| 3 | Single attempt versus self-correction | Value of the retry loop |
| 4 | Cheap model versus strong model | Cost and quality trade-off |
| 5 | Rule-based verdict versus LLM-only verdict | Consistency of RQ assessment |
| 6 | With versus without column retrieval on wide tables | Scaling to many columns |

- [ ] Cache LLM responses by prompt hash during development.
- [ ] Use bootstrap confidence intervals. Small differences on 150 questions are noise.
- [ ] CI smoke eval: 15 questions on each pull request.
- [ ] Error analysis: categorise 30 failures and record what each category suggests changing.

**Done when:** `evals/reports/` holds a results table for all experiments and the README shows the headline numbers.

### Phase 6: Export, polish, and deployment (week 11)

- [ ] Dataset report export (Markdown and PDF): overview, data dictionary, quality warnings, RQ fit, top insights, and limitations. Useful as a draft for the "dataset" section of a paper.
- [ ] Per-user limits: project count, file size, and a monthly LLM budget.
- [ ] Project deletion removes the DuckDB file, traces, and query logs.
- [ ] A usage page: cost and latency per project.
- [ ] Empty states, error messages, and a sample project with a public dataset for the demo.
- [ ] Deploy, add health checks and error tracking.
- [ ] README with architecture diagram, results, and limitations. Record a 2-minute demo video.

---

## 7. Prompt design notes

- **Context for SQL generation:** table and column names, types, descriptions, value ranges, top categorical values, and missing rates. Top values matter because they stop the model from inventing category names in `WHERE` clauses.
- **Separate data from instructions.** Column names, cell values, and RQ text are user-supplied. Wrap them in labelled tags and tell the model they are data.
- **State the DuckDB dialect** and include two or three dialect-specific examples.
- **Tell the model what to do when it cannot answer:** say so and name what is missing.
- **Version every prompt** and record the version on each call and eval run.

---

## 8. Testing strategy

| Level | Coverage |
|---|---|
| Unit | Profiler against hand-checked fixtures, SQL guard, statistics functions against known values, grounding check, verdict rules |
| Integration | Upload to profile to chat with a fake LLM client returning recorded responses |
| Security | Malicious SQL, prompt injection through column names and cell values, oversized uploads |
| End to end | Playwright: create project, upload, view profile, ask a question |
| Eval | Smoke suite in CI, full suites before release |

---

## 9. Privacy and security

- **What reaches the LLM:** schema, aggregate statistics, masked sample values, and query results limited to a row cap. State this clearly in the UI, since research data may be sensitive.
- **Option to disable sample values** for a project, so only aggregates are sent.
- **Isolation:** one DuckDB file per project, opened read-only, with no external file or network access.
- **Generated SQL is untrusted.** Validate, limit, and time out every query.
- **Uploads:** check size and type, store outside the web root, use generated file names.
- **Deletion:** removing a project removes its data.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Model invents numbers | Grounding check, every answer linked to queries |
| Spurious insights | Correction for multiple tests, effect sizes, exploratory label, confounder check |
| Wrong RQ mapping | User can edit mappings, match type shown, measured in benchmark C |
| Messy CSV files fail to load | Broad fixture set, clear load warnings, placeholder detection |
| Wide tables exceed context | Column retrieval, profile summaries |
| Users treat verdicts as final | Wording that presents verdicts as guidance, evidence shown beside each one |
| LLM cost | Profiling without LLM, cheap model by default, caching, budgets |
| Hand labels are subjective | Written labelling rules, second labeller on a sample |

---

## 11. Timeline

| Week | Phase | Deliverable |
|---|---|---|
| 1 | 0 | Skeleton, login, traced LLM client |
| 2 to 3 | 1 | Upload, profiler, profile page |
| 4 to 5 | 2 | Column descriptions, guarded SQL, chat with charts |
| 6 to 7 | 3 | RQ fit analysis |
| 8 | 4 | Insights |
| 9 to 10 | 5 | Three benchmarks, experiments, error analysis |
| 11 | 6 | Report export, deployment, demo |

**Minimum version if time runs short:** Phases 0 to 3 plus benchmarks A and C. The insights page can be dropped; the RQ fit analysis cannot.

---

## 12. Future work

**Image and audio datasets.** The same design extends if the dataset is first turned into a table:

1. **Manifest table.** One row per file with facts read by code: label, split, file size, resolution or duration, sample rate, channels, format, and whether the file is corrupt. The existing profiler then reports class balance, split leakage, and duration or resolution distributions.
2. **Derived columns.** Compute embeddings per file to find duplicates, near-duplicates across train and test splits, clusters, and outliers. Add quality measures such as blur, brightness, silence ratio, and clipping.
3. **Sampled descriptions.** Send a stratified sample to a multimodal model for captions, or to a speech model for transcripts and language detection. Store the output as columns and mark it as sampled, not exhaustive.
4. **RQ fit and chat work unchanged,** because they operate on tables.

The main costs are storage, compute for embeddings, and model calls per file, so sampling and budgets are required.

**Other items**

- Read-only connections to Postgres and MySQL.
- Free-text columns: topic and language summaries.
- Export of an analysis as a notebook.
- Comparison of two versions of a dataset.
- Shared projects with comments for co-authors and supervisors.

---

## 13. Building with AI coding tools

- **Work in small steps.** One feature per session, with this plan and the data model in the tool's context.
- **Write tests before the risky parts:** the profiler, the SQL guard, the statistics functions, and the grounding check. Wrong output there is easy to miss by eye.
- **Let the tool generate:** UI pages, CRUD routes, migrations, Docker files, chart components.
- **Design and review yourself:** the verdict rules, the benchmark cases and labels, the prompts, and the SQL guard. These are the parts interviewers will ask about.
- **Never let the tool write the gold answers** for the benchmarks without checking each one by hand.
- **Keep a decisions log** (`DECISIONS.md`) with one line per design choice and the reason. It becomes interview preparation.

---

## 14. CV and interview material

Fill in the brackets with measured numbers only.

- "Built a web app that assesses whether a dataset can answer a researcher's questions, with [X]% agreement with expert labels on [N] dataset and question pairs."
- "Implemented a tool-using LLM agent for data questions over DuckDB, reaching [Y]% execution accuracy on [N] questions, up from [Z]% with a single prompt."
- "Designed a grounding check that traces every reported number to an executed query, giving [P]% traceable numeric claims."
- "Detected [R]% of [N] injected data-quality problems with [F] false alarms per clean dataset."

**Topics to prepare:** why the LLM never reads raw rows; how generated SQL is made safe; how you handle multiple testing; how the verdict rules work and where they fail; how you built and validated the labels; and what the error analysis showed.