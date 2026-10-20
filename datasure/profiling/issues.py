"""Issue generation: turn measured profile facts into actionable warnings.

Each issue carries:
- kind: stable machine identifier
- severity: info | warning | critical
- columns: affected columns (or [] for dataset-level)
- message: what was observed (always with the actual numbers)
- recommendation: deterministic, actionable next step

Severity guide:
- critical: data would be unusable or misleading without correction
- warning:  real quality concern worth acting on
- info:     largely informational observation
"""
from __future__ import annotations

from typing import Any

SEVERITY_ORDER = {"critical": 3, "warning": 2, "info": 1}


def build_issues(profile: dict, leakage: dict | None = None) -> list[dict[str, Any]]:
    """Generate the consolidated issue list from a `profile_dataset` result."""
    issues: list[dict[str, Any]] = []
    overview = profile["overview"]
    missingness = profile["missingness"]
    duplicates = profile["duplicates"]
    cardinality = profile["cardinality"]
    schema = profile.get("schema", {})

    # ---- completeness -----------------------------------------------------
    if missingness["missing_cells"] > 0:
        worst = missingness["columns_with_missing"][0] if missingness["columns_with_missing"] else None
        severity = "warning" if missingness["missing_pct"] <= 15 else "critical"
        issues.append(
            {
                "kind": "missing_values",
                "severity": severity,
                "columns": [entry["column"] for entry in missingness["columns_with_missing"]],
                "message": (
                    f"{missingness['missing_cells']:,} missing cells "
                    f"({missingness['missing_pct']:.2f}% of all values) across "
                    f"{len(missingness['columns_with_missing'])} column(s)."
                    + (f" Worst affected: {worst['column']} ({worst['pct']:.1f}%)." if worst else "")
                ),
                "recommendation": (
                    "Investigate why values are missing before imputing; if a column is "
                    "missing in large part, check whether the missings are structurally "
                    "encoded (e.g. empty strings) or a real gap in collection."
                ),
            }
        )
    if missingness["rows_missing_all"] > 0:
        issues.append(
            {
                "kind": "fully_empty_rows",
                "severity": "warning",
                "columns": [],
                "message": f"{missingness['rows_missing_all']:,} row(s) are completely empty.",
                "recommendation": "Remove or repair fully empty rows before analysis.",
            }
        )

    # ---- unusable columns -------------------------------------------------
    for column in cardinality["constant"]:
        issues.append(
            {
                "kind": "constant_column",
                "severity": "warning",
                "columns": [column],
                "message": f"Column '{column}' has the same value in every non-empty cell.",
                "recommendation": (
                    "Constant columns carry no predictive or analytical information; "
                    "confirm they are intentional before dropping them."
                ),
            }
        )
    empty_columns = [
        entry["name"] for entry in profile["columns"] if entry["non_null"] == 0
    ]
    for column in empty_columns:
        issues.append(
            {
                "kind": "empty_column",
                "severity": "critical",
                "columns": [column],
                "message": f"Column '{column}' contains no data at all.",
                "recommendation": "Remove the empty column or locate the correct source data.",
            }
        )

    # ---- uniqueness --------------------------------------------------------
    if duplicates["duplicate_rows"] > 0:
        severity = "warning" if duplicates["duplicate_row_pct"] <= 25 else "critical"
        issues.append(
            {
                "kind": "duplicate_rows",
                "severity": severity,
                "columns": [],
                "message": (
                    f"{duplicates['duplicate_rows']:,} duplicate row(s) "
                    f"({duplicates['duplicate_row_pct']:.2f}% of rows) were detected."
                ),
                "recommendation": (
                    "Deduplicate before analysis, but confirm the duplicates are not "
                    "genuine repeated observations (e.g. repeated measurements)."
                ),
            }
        )
    for column in duplicates["duplicate_columns"]:
        issues.append(
            {
                "kind": "duplicate_column",
                "severity": "warning",
                "columns": [column],
                "message": f"Column '{column}' exactly duplicates another column's values.",
                "recommendation": "Drop one of the duplicated columns to avoid double weighting.",
            }
        )

    # ---- schema / type problems -------------------------------------------
    for entry in schema.get("suspicious_type_storage", []):
        issues.append(
            {
                "kind": "numeric_stored_as_text",
                "severity": "warning",
                "columns": [entry["column"]],
                "message": (
                    f"Column '{entry['column']}' is stored as text although "
                    f"{entry['affected_pct']:.1f}% of its non-empty values parse as numbers."
                ),
                "recommendation": (
                    "Convert the column to a numeric type (check the suffix/decimal "
                    "formats of the remaining values first)."
                ),
            }
        )

    # ---- mixed / blank text issues ---------------------------------------
    for entry in profile["columns"]:
        if entry["kind"] == "mixed":
            issues.append(
                {
                    "kind": "mixed_types",
                    "severity": "warning",
                    "columns": [entry["name"]],
                    "message": (
                        f"Column '{entry['name']}' mixes incompatible types "
                        f"({', '.join(entry.get('python_types', {}))})."
                    ),
                    "recommendation": (
                        "Normalise the column to a single type; mixed types often come "
                        "from accidental characters or merged export formats."
                    ),
                }
            )
        if entry.get("whitespace_issue_count"):
            issues.append(
                {
                    "kind": "whitespace_problems",
                    "severity": "info",
                    "columns": [entry["name"]],
                    "message": (
                        f"{entry['whitespace_issue_count']:,} value(s) in '{entry['name']}' "
                        "have leading/trailing whitespace."
                    ),
                    "recommendation": "Trim string values; this usually merges duplicate categories.",
                }
            )

    # ---- cardinality -------------------------------------------------------
    for column in cardinality["high_cardinality"]:
        issues.append(
            {
                "kind": "high_cardinality",
                "severity": "info",
                "columns": [column],
                "message": (
                    f"Column '{column}' is almost unique per row - it behaves like an "
                    "identifier rather than a feature."
                ),
                "recommendation": (
                    "Exclude identifier-like columns from modelling; check them is not "
                    "carrying accidental personal identifiers."
                ),
            }
        )
    if not cardinality["constant"] and overview["rows"] < 30:
        issues.append(
            {
                "kind": "small_sample",
                "severity": "info",
                "columns": [],
                "message": f"The dataset has only {overview['rows']} row(s); distributions may be unreliable.",
                "recommendation": "Treat all statistics as indicative with very small samples.",
            }
        )

    # ---- outliers / distribution shape ------------------------------------
    for entry in profile["columns"]:
        if entry["kind"] != "numeric" or not entry.get("outliers"):
            continue
        stats = entry.get("stats") or {}
        non_null = entry["non_null"]
        out_iqr = entry["outliers"].get("iqr_count", 0)
        out_pct = 100.0 * out_iqr / max(non_null, 1)
        if out_iqr and out_pct >= 10:
            issues.append(
                {
                    "kind": "outliers",
                    "severity": "warning",
                    "columns": [entry["name"]],
                    "message": (
                        f"{out_iqr:,} potential outlier(s) ({out_pct:.1f}% of values) in "
                        f"'{entry['name']}' beyond the Tukey 1.5*IQR bounds "
                        f"[{entry['outliers'].get('iqr_lower')}, {entry['outliers'].get('iqr_upper')}]."
                    ),
                    "recommendation": (
                        "Inspect the flagged values; decide between valid extremes and data "
                        "entry errors before modelling."
                    ),
                }
            )
        skew = entry.get("skew")
        if skew is not None and abs(skew) >= 3:
            issues.append(
                {
                    "kind": "high_skew",
                    "severity": "info",
                    "columns": [entry["name"]],
                    "message": f"Column '{entry['name']}' is highly skewed (skew = {skew:.2f}).",
                    "recommendation": "Consider a transformation (e.g. log) for models that assume symmetry.",
                }
            )

    # ---- class imbalance ---------------------------------------------------
    imbalance = [
        entry for entry in profile["columns"]
        if entry.get("class_imbalance_ratio") is not None
        and entry["unique"] and entry["unique"] >= 2 and entry["unique"] <= 20
        and entry.get("class_imbalance_ratio", 1) <= 0.05
    ]
    for entry in imbalance:
        issues.append(
            {
                "kind": "class_imbalance",
                "severity": "warning",
                "columns": [entry["name"]],
                "message": (
                    f"Column '{entry['name']}' is heavily imbalanced: the smallest category "
                    f"holds ~{entry['class_imbalance_ratio'] * 100:.1f}% of the share of the largest."
                ),
                "recommendation": (
                    "If this is a prediction target, use stratified sampling and prefer "
                    "metrics like macro-F1 that are robust to imbalance."
                ),
            }
        )

    # ---- leakage (warnings only) -------------------------------------------
    if leakage:
        for warning in leakage.get("warnings", []):
            columns = warning.get("columns", [])
            if warning["kind"] == "target_leakage_suspected":
                detail = warning.get("correlation", warning.get("agreement"))
                issues.append(
                    {
                        "kind": "target_leakage_suspected",
                        "severity": "warning",
                        "columns": columns,
                        "message": (
                            f"Feature '{columns[0] if columns else '?'}' is nearly identical to "
                            f"target '{columns[1] if len(columns) > 1 else '?'}'"
                            + (f" (statistic ~ {detail})" if detail is not None else ".")
                        ),
                        "recommendation": (
                            "Leakage is suspected, not confirmed: verify whether this feature is "
                            "genuinely available before prediction time. If it encodes the target, "
                            "exclude it from models."
                        ),
                    }
                )
        for note in leakage.get("info", []):
            issues.append(
                {
                    "kind": note["kind"],
                    "severity": "info",
                    "columns": note.get("columns", []),
                    "message": _describe_leakage_info(note),
                    "recommendation": (
                        "Review the relationship; redundancy is not harmful but may bias "
                        "feature importance scores."
                    ),
                }
            )

    return sorted(
        issues,
        key=lambda issue: (-SEVERITY_ORDER.get(issue["severity"], 0), issue["kind"]),
    )


def _describe_leakage_info(note: dict) -> str:
    if note["kind"] == "feature_correlation":
        return (
            f"Feature '{note['columns'][0]}' strongly correlates with target "
            f"'{note['columns'][1]}' (r = {note.get('correlation')})."
        )
    if note["kind"] == "feature_determines_target":
        return (
            f"Values of '{note['columns'][0]}' nearly determine the target category "
            f"(mean group purity {note.get('mean_group_purity')})."
        )
    return f"Unexpected relationship detected: {note}"
