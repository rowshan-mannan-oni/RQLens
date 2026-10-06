"""Rule-based data-quality warnings. No LLM: every rule is a fixed threshold that can be tested."""

from typing import Any, Literal, TypedDict

Severity = Literal["info", "warning", "severe"]


class DataWarning(TypedDict):
    code: str
    severity: Severity
    message: str
    column: str | None
    details: dict[str, Any]


def warning(
    code: str,
    severity: Severity,
    message: str,
    *,
    column: str | None = None,
    details: dict[str, Any] | None = None,
) -> DataWarning:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "column": column,
        "details": details or {},
    }


# Thresholds
MISSING_WARNING = 0.20
MISSING_SEVERE = 0.50
IMBALANCE_TOP_SHARE = 0.90
# Numeric codes often used for "missing" in survey and statistics exports.
SENTINEL_VALUES = (-99999.0, -9999.0, -999.0, -99.0, 999.0, 9999.0, 99999.0)
SENTINEL_MIN_COUNT = 2
# Share of values that must look like "<number> <unit>" before units are reported.
UNIT_SHARE = 0.8
UNIT_MIN_SHARE = 0.01
NEAR_PERFECT = {"spearman": 0.98, "cramers_v": 0.95, "eta": 0.95}
MEASURE_LABEL = {"spearman": "Spearman rho", "cramers_v": "Cramér's V", "eta": "eta"}


def column_warnings(name: str, original: str, profile: dict[str, Any]) -> list[DataWarning]:
    out: list[DataWarning] = []
    semantic = profile["semantic_type"]
    missing_pct = profile["missing_pct"]

    if profile["non_null"] == 0:
        out.append(warning("empty_column", "severe", f"'{original}' is empty.", column=name))
        return out

    if missing_pct >= MISSING_WARNING:
        severe = missing_pct >= MISSING_SEVERE
        out.append(
            warning(
                "high_missing",
                "severe" if severe else "warning",
                f"'{original}' is missing in {missing_pct:.0%} of rows.",
                column=name,
                details={"missing": profile["missing"], "missing_pct": missing_pct},
            )
        )

    if semantic == "constant":
        out.append(
            warning(
                "constant",
                "warning",
                f"'{original}' has a single value, so it cannot explain any variation.",
                column=name,
            )
        )

    if semantic == "identifier":
        out.append(
            warning(
                "identifier",
                "info",
                f"'{original}' looks like an identifier; it is excluded from statistics.",
                column=name,
            )
        )

    categorical = profile.get("categorical")
    if semantic in ("categorical", "boolean") and categorical:
        top_share = categorical["top_share"]
        if top_share >= IMBALANCE_TOP_SHARE:
            top = profile["top_values"][0]
            out.append(
                warning(
                    "imbalance",
                    "warning",
                    f"'{original}' is dominated by one value ('{top['value']}' in "
                    f"{top_share:.0%} of rows), so comparisons across its groups will be weak.",
                    column=name,
                    details={"top_share": top_share, "value": top["value"]},
                )
            )

    numeric = profile.get("numeric")
    if numeric:
        for sentinel in numeric.get("sentinels", []):
            out.append(
                warning(
                    "placeholder_value",
                    "warning",
                    f"'{original}' contains {sentinel['value']:g} {sentinel['count']} time(s). "
                    "This is often a code for missing; check the data dictionary.",
                    column=name,
                    details=sentinel,
                )
            )

    datetime_ = profile.get("datetime")
    if datetime_ and datetime_["empty_periods"]:
        out.append(
            warning(
                "date_gaps",
                "warning",
                f"'{original}' has no rows in {datetime_['empty_periods']} of "
                f"{len(datetime_['counts'])} {datetime_['period']} periods.",
                column=name,
                details={"empty_periods": datetime_["empty_periods"]},
            )
        )

    shift = numeric.get("unit_shift") if numeric else None
    if shift:
        out.append(
            warning(
                "unit_shift",
                "warning",
                f"'{original}' changes scale around row {shift['from_row']}: later values are "
                f"about {shift['ratio']:.2g} times earlier ones. This may be a unit change (for "
                "example kg to lb), or the file may be sorted by a group.",
                column=name,
                details=shift,
            )
        )

    text = profile.get("text")
    units = text.get("units") if text else None
    if units and units["share"] >= UNIT_SHARE:
        minimum = max(2, UNIT_MIN_SHARE * profile["non_null"])
        real = [u for u in units["values"] if u["count"] >= minimum]
        listing = ", ".join(f"{u['unit']} ({u['count']})" for u in real[:5])
        if len(real) >= 2:
            out.append(
                warning(
                    "mixed_units",
                    "warning",
                    f"'{original}' mixes units: {listing}. Convert to one unit before "
                    "comparing values.",
                    column=name,
                    details=units,
                )
            )
        elif real:
            out.append(
                warning(
                    "numeric_with_unit",
                    "info",
                    f"'{original}' stores numbers with a unit ('{real[0]['unit']}') as text. "
                    "Convert it to a number column to analyse it.",
                    column=name,
                    details=units,
                )
            )

    if text and text["blank"]:
        out.append(
            warning(
                "blank_strings",
                "info",
                f"'{original}' has {text['blank']} value(s) that are only spaces.",
                column=name,
                details={"count": text["blank"]},
            )
        )
    return out


def table_warnings(
    table_profile: dict[str, Any], names: dict[str, str] | None = None
) -> list[DataWarning]:
    out: list[DataWarning] = []
    names = names or {}
    duplicates = table_profile["duplicate_rows"]
    if duplicates:
        share = duplicates / table_profile["row_count"]
        out.append(
            warning(
                "duplicate_rows",
                "warning",
                f"{duplicates} row(s) ({share:.1%}) are exact duplicates of another row.",
                details={"count": duplicates, "share": share},
            )
        )
    if table_profile["row_count"] == 0:
        out.append(warning("no_rows", "severe", "The table has no rows."))

    relations = table_profile.get("relationships") or {}
    for d in relations.get("duplicates", []):
        a, b = names.get(d["a"], d["a"]), names.get(d["b"], d["b"])
        out.append(
            warning(
                "near_duplicate_columns",
                "warning",
                f"'{a}' and '{b}' hold the same value in {d['share']:.0%} of rows; one is "
                "probably a copy of the other.",
                column=d["b"],
                details=d,
            )
        )
    for r in relations.get("associations", []):
        if abs(r["value"]) < NEAR_PERFECT[r["measure"]]:
            continue
        a, b = names.get(r["a"], r["a"]), names.get(r["b"], r["b"])
        out.append(
            warning(
                "near_perfect_association",
                "warning",
                f"'{a}' almost perfectly predicts '{b}' ({MEASURE_LABEL[r['measure']]} = "
                f"{r['value']:.2f}). If one of them is an outcome, the other may leak it; "
                "otherwise one may be derived from the other.",
                column=r["b"],
                details=r,
            )
        )
    seen: set[str] = set()
    for d in (relations.get("missingness") or {}).get("dependencies", []):
        if d["column"] in seen:
            continue  # only the strongest dependency per column
        seen.add(d["column"])
        col, by = names.get(d["column"], d["column"]), names.get(d["by"], d["by"])
        if d["kind"] == "categorical":
            hi, lo = d["highest"], d["lowest"]
            text = (
                f"'{col}' is missing more often when '{by}' is '{hi['value']}' "
                f"({hi['rate']:.0%}) than when it is '{lo['value']}' ({lo['rate']:.0%})."
            )
        else:
            direction = "higher" if d["smd"] > 0 else "lower"
            text = (
                f"Rows where '{col}' is missing have {direction} '{by}' (mean "
                f"{d['mean_when_missing']:.3g} vs {d['mean_when_present']:.3g})."
            )
        out.append(
            warning(
                "missing_depends",
                "warning",
                text + " The data may not be missing at random, which can bias results.",
                column=d["column"],
                details=d,
            )
        )
    return out
