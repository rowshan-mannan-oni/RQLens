# Evaluation

Run every command below from the repository root. `PYTHONPATH=apps:.` makes both `api` and `evals` importable.

## Datasets

`datasets/<name>/v1/` holds the versioned development datasets. Never edit a version in place: add `v2` instead. `datasets/manifest.json` records each file's source, licence, row and column counts, and SHA-256 checksum. `messy_survey` is generated from `cps1985` by `datasets/make_messy.py`.

## Chat accuracy (benchmark A)

The questions are in `qa/questions.v1.jsonl`, one JSON object per line:

| Field | Meaning |
|---|---|
| `id`, `tables`, `category`, `question` | The case, and the tables the project holds |
| `expected` | `answer`, `clarification` or `cannot_answer` |
| `gold_sql` | The reference query (none for clarification and cannot-answer cases) |
| `order_matters` | Whether row order is part of the answer |
| `stat_test` | For significance questions: the test and the columns it should use |
| `reviewed` | Whether a person has checked the gold result by hand |

Commands:

```sh
PYTHONPATH=apps:. python evals/run_eval.py qa --check-gold   # run the gold queries; writes qa/gold.v1.json
PYTHONPATH=apps:. python evals/run_eval.py qa --llm oracle   # harness self-test; should be 100%
PYTHONPATH=apps:. python evals/run_eval.py qa                # the real agent, using LLM_* settings
PYTHONPATH=apps:. python evals/run_eval.py qa --smoke        # the 15-question smoke set
PYTHONPATH=apps:. python evals/run_eval.py qa --no-retrieval # experiment 6: word matching only
```

Scoring uses execution match (`scoring.py`). An answer passes when one of the queries it cites returns the gold result. Extra columns and a different column order are allowed. Row order is ignored unless `order_matters` is set. Numbers may be rounded to the precision the agent chose, or differ by up to 0.1%.

Statistical cases pass when the agent ran the same test, the p-values agree (both below 0.001, or within 5%) and the effect sizes are within 0.02. Clarification and cannot-answer cases pass when the agent's answer is of that kind.

Reports are written to `reports/` as JSON with every case, plus a Markdown summary.

## Before reporting numbers

Check each gold result in `qa/gold.v1.json` by hand and set `reviewed: true`. Plan section 13 says the gold answers must not be trusted until a person has checked them.

## Research-question verdicts (benchmark C)

The cases are in `rq_fit/cases.v1.jsonl`. Each case has a question, its table, a hand-labelled `expected_verdict`, and a labelled `gold_parse` and `gold_mapping` (`reviewed: false` until a person checks them).

```sh
PYTHONPATH=apps:. python evals/run_eval.py rq --gold-mapping   # labelled mappings, no LLM
PYTHONPATH=apps:. python evals/run_eval.py rq                  # the LLM parses and maps
```

The `--gold-mapping` mode checks the measurements and the verdict rules on their own, so mapping errors don't affect the result. The full mode also reports mapping precision and recall: the share of `(role, table.column)` pairs that match the labelled mapping.

The plan's target is 60 labelled pairs, about a third of them partial or not answerable, with a second person labelling 20. The 13 current cases are development cases: one rule was added after seeing one of them (see `DECISIONS.md`), so do not report their agreement as accuracy.

## Insights check (Phase 4)

```sh
PYTHONPATH=apps:. python evals/run_eval.py insights           # every development dataset
PYTHONPATH=apps:. python evals/run_eval.py insights --ids mpg
```

Each dataset runs as its own project, with that dataset's labelled research questions. The report counts insights, findings, charts and confounder flags, and fails if any statement has a number that does not appear in its test result. Set `LLM_API_KEY=` (empty) to run without an LLM.
