# Decisions

One line per design choice and the reason, as suggested in plan.md section 13. Newest sections are at the bottom.

## Phase 2: chat

- The chat agent finishes with `final_answer` and a kind (`answer`, `clarification`, `cannot_answer`), so behaviour on ambiguous or unanswerable questions can be scored.
- Grounding accepts rounding to the precision written, percentages of shares, scale words (million) and scientific notation. Whole numbers 0 to 10 are exempt, because they usually count things in the sentence.
- Wide tables (more than 50 columns) show only column names in the prompt, plus the 15 columns most relevant to the question. Relevance combines embedding similarity with word overlap, because embeddings miss exact codes like `q17` and words miss synonyms.
- The chat benchmark scores by execution match, not by text, because answers can be phrased in many ways but their numbers come from a query result.

## Phase 3: research-question fit

### Pipeline

- Each research question passes through four steps:
  1. **Parse** (LLM): question type, constructs, population and time scope.
  2. **Map** (LLM): each construct to columns.
  3. **Measure** (SQL only): the feasibility checks.
  4. **Verdict** (rules only), then **explain** (LLM).

  The verdict never comes from the model, so the same measurements always give the same verdict, and the rules can be unit-tested and compared with an LLM-only verdict (experiment 5).
- The LLM writes the explanation, suggested method, threats and rewording from the rule results. Its numbers must pass the grounding check against the measurements.
- A construct maps to a SQL expression, not only to a column. A derivable construct ("age at diagnosis") becomes an expression such as `diagnosis_year - birth_year`. Every expression runs through the SQL guard inside a full SELECT before use.
- The population and time filters are SQL conditions written by the mapper and checked by the guard the same way. Users can edit them.
- User edits to a mapping are kept until the question text changes. Re-assessing after an edit skips the parse and map steps.
- v1 runs the checks on one table: the table of the outcome construct. Constructs mapped to other tables raise a warning instead of a join. Joins are a later improvement.

### Construct roles

- `dependent`: the outcome, or the thing being described.
- `independent`: the explanatory or grouping variable.
- `covariate`: a control or context variable.

Dependent and independent constructs are **core**. A gap in a core construct makes the question not answerable; a gap in a covariate only makes it partial.

### Verdict rules (draft for review)

The verdict is the worst level among the rules that fire:

- any `fail` gives **not_answerable**;
- otherwise any `warn` gives **partial**;
- otherwise **answerable**.

| Rule | Level | Fires when |
|---|---|---|
| `core_gap` | fail | A dependent or independent construct has no column (or its mapping was rejected) |
| `no_rows_in_scope` | fail | No rows remain after the population and time filters |
| `too_few_complete` | fail | Fewer than 10 rows in scope have every mapped column present |
| `outcome_constant` | fail | The outcome has at most 1 distinct value in scope |
| `too_few_groups` | fail | A comparison needs groups but fewer than 2 groups have at least 5 complete rows |
| `no_time_overlap` | fail | The requested period does not overlap the data's dates at all |
| `covariate_gap` | warn | A covariate has no column |
| `proxy_only` | warn | A core construct is mapped only through a proxy |
| `small_sample` | warn | Fewer than 30 complete rows |
| `high_missing` | warn | A mapped column is missing in more than 30% of rows in scope |
| `small_group` | warn | The smallest group has fewer than 20 complete rows |
| `unbalanced_groups` | warn | The largest group is more than 10 times the smallest |
| `outcome_near_constant` | warn | One outcome value covers 95% or more of the rows in scope |
| `group_constant_outcome` | warn | The outcome never varies within one group, a sign it is not recorded for that group (for example, cash tips in taxi data) |
| `partial_time_coverage` | warn | The data covers less than 80% of the requested period |
| `low_power` | warn | The smallest detectable effect at α = 0.05 and 80% power is large: Cohen's d above 0.8 for two groups, r above 0.5 for a correlation, or a margin of error above 0.1 (for a proportion) for a descriptive question |
| `causal_claim` | warn | The question is causal: observational data supports association only |
| `multi_table` | warn | Constructs are mapped to more than one table (v1 checks one table) |
| `confounders` | info | Columns associated with both the outcome and the explanatory variable (from the profile), listed as possible confounders |

Notes on the rules:

- **Power.** The minimum detectable effect uses the normal approximation:
  - two groups: d = (z₀.₉₇₅ + z₀.₈) × √(1/n₁ + 1/n₂), using the two smallest groups when there are more than two;
  - correlation: r = tanh((z₀.₉₇₅ + z₀.₈) / √(n − 3));
  - descriptive: margin = 1.96 × √(0.25 / n).

  It is a rough check and is labelled as one.
- **Causal questions are at most partial.** No check can rule out confounding in observational data, so a causal question is never "answerable" as worded. The rewording suggests the associational version.
- **Thresholds** (10, 30, 30%, 5, 20, 10×, 95%, 80%, 0.8, 0.5, 0.1) are conventional starting points, not tuned values. Benchmark C (60 hand-labelled pairs) is where they get checked.

### Changes after the first benchmark run

- `group_constant_outcome` was added after `taxis-tip-payment` disagreed with its label: every cash trip had a tip of 0 because cash tips are not recorded. The rule generalises (an outcome that never varies within a group is usually missing for that group). Because it was added after seeing that case, the 13 development cases are no longer an unbiased test of the rules. Report agreement only on cases labelled after this change.

### Mapping and checks

- A numeric explanatory column with at most 20 distinct values counts as groups only for comparative questions. Otherwise it is treated as a correlation. The profiler already types low-cardinality integers such as `pclass` as categorical.
- Each check is a separate small query rather than one large query, so each piece of evidence links to exactly the query that produced it.

## Phase 4: insights

- **Planning.** Analyses come from three sources, in this priority order: research-question mappings (outcome against each explanatory variable, with the question's population filter), then the LLM's ideas (optional, at most 8), then the profile's strongest associations. At most 20 analyses run. Without an LLM, insights still work: the plan comes from rules and statements use templates.
- **Specs are data, not code:** a table, two columns, a test from the fixed library and an optional SQL filter. Each spec is checked against column kinds (for example, Mann-Whitney needs a numeric column and a 2-value group column) and the filter passes the SQL guard.
- **Columns that are never analysed:** identifiers, constants, free text, personal data, and complete integer columns with a unique value in every row (row numbers in CSV exports). An analysis of a row number only reflects how the file was sorted, as messy_survey's `Respondent #` showed.
- **Integer columns with 6 or more values** are treated as ordered numbers (Spearman), not as groups, even when the profiler types them categorical (bug counts). Fewer values (`pclass`) are groups.
- **Profile pairs left out:** category pairs with Cramér's V ≥ 0.9, because one usually recodes the other (`who` and `sex`); any pair at 0.98 or more (near-duplicates). Strong numeric correlations are kept (flights' year and passengers, rho 0.95, is a real trend). Columns at 0.95 or more count as one column when removing duplicate analyses (`pclass` and `class`).
- **Multiple testing.** Benjamini-Hochberg runs over every test in a run; both raw and adjusted p-values are stored and shown.
- **Ranking (draft for review):** score = 0.4 × relevance + 0.4 × effect + 0.2 × support, halved when the adjusted p ≥ 0.05.
  - Relevance: 1 for an analysis of a research question, 0.6 when a column is mapped to some question, 0.5 for the LLM's ideas, 0.3 for profile pairs.
  - Effect: |effect| on a 0-to-1 scale, using √ε² for Kruskal-Wallis.
  - Support: log10(n) / 3, capped at 1.

  The p-value never ranks a result on its own: a tiny p with a negligible effect is labelled "significant but negligible".
- **Status:** finding (adjusted p < 0.05 and at least a small effect), weak (significant but negligible), or no evidence.
- **Confounder check** for the top 5 findings: grouping columns with 2 to 6 values, associated (≥ 0.1) with both analysed columns, at most 2 per finding. The same test is re-run in each subgroup with 30 or more rows, and at least 2 such subgroups are needed.
  - **reverses:** opposite sign with |effect| ≥ 0.1 in some subgroup (signed measures only);
  - **weakens:** the row-weighted mean |effect| within subgroups is under half the overall |effect|;
  - **holds:** otherwise.

  A planted Simpson's paradox is caught in the tests.
- **Statements.** A template statement uses only the test's own numbers, so it always passes the grounding check. An LLM rewrite replaces it only if the rewrite passes the check against that insight's result.
- **Caveats on every card:** the exploratory label, sampling, the population filter, confounder results, placeholder codes such as -999 that were included, and "association, not cause".
- **Data-quality insights** reuse the Phase 3 rule results (missing outcome, small or one-value groups) for each research question, with the query that measured them.
- **Known limitation:** a column computed from another (titanic's `alone` from `sibsp` and `parch`, or `who` from age) can't be detected in general, so such pairs can still rank high.
