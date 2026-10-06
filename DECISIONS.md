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
| `partial_time_coverage` | warn | The data covers less than 80% of the requested period |
| `low_power` | warn | The smallest detectable effect at α = 0.05 and 80% power is large: Cohen's d above 0.8 for two groups, r above 0.5 for a correlation, or a margin of error above 0.1 (proportion, or SD units) for a descriptive question |
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
