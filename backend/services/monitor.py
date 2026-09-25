# backend/services/monitor.py

import json
import logging
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
import scipy.stats as stats
import requests

logger = logging.getLogger("genq_api.monitor")


def calculate_psi(baseline_series: pd.Series, current_series: pd.Series, num_buckets: int = 10) -> float:
    """Calculates the Population Stability Index (PSI) between baseline and current distributions."""
    b_clean = baseline_series.dropna()
    c_clean = current_series.dropna()

    if len(b_clean) < 10 or len(c_clean) < 10:
        return 0.0

    try:
        if pd.api.types.is_numeric_dtype(b_clean):
            # Quantile binning on baseline
            quantiles = np.linspace(0, 1, num_buckets + 1)
            bins = np.percentile(b_clean, quantiles * 100)
            bins = np.unique(bins)
            if len(bins) < 2:
                return 0.0
            bins[0] = -np.inf
            bins[-1] = np.inf

            b_counts, _ = np.histogram(b_clean, bins=bins)
            c_counts, _ = np.histogram(c_clean, bins=bins)
        else:
            # Categorical frequency binning
            top_cats = b_clean.value_counts().head(num_buckets - 1).index.tolist()
            b_cat = b_clean.apply(lambda x: x if x in top_cats else "Other")
            c_cat = c_clean.apply(lambda x: x if x in top_cats else "Other")

            all_cats = list(set(top_cats + ["Other"]))
            b_counts = np.array([int((b_cat == cat).sum()) for cat in all_cats])
            c_counts = np.array([int((c_cat == cat).sum()) for cat in all_cats])

        # Smooth zero counts to prevent div-by-zero
        b_pct = (b_counts + 1e-4) / (b_counts.sum() + 1e-4 * len(b_counts))
        c_pct = (c_counts + 1e-4) / (c_counts.sum() + 1e-4 * len(c_counts))

        psi_val = np.sum((c_pct - b_pct) * np.log(c_pct / b_pct))
        return round(float(psi_val), 4)

    except Exception as e:
        logger.warning("Error calculating PSI: %s", e)
        return 0.0


def compute_drift_and_anomaly_alerts(
    baseline_df: pd.DataFrame,
    current_df: pd.DataFrame,
    alert_threshold_psi: float = 0.20,
    mean_shift_pct_threshold: float = 15.0,
) -> Dict[str, Any]:
    """Compares baseline and current dataset snapshots to detect data drift, statistical shifts,
    and trigger operational alerts."""
    common_cols = [c for c in baseline_df.columns if c in current_df.columns]
    if not common_cols:
        return {
            "overall_health_score": 0,
            "status": "CRITICAL",
            "alerts": [{"severity": "CRITICAL", "title": "Schema Mismatch", "detail": "No common columns found between datasets."}],
            "feature_drifts": {},
        }

    feature_drifts = {}
    alerts = []
    penalties = 0

    for col in common_cols:
        b_col = baseline_df[col]
        c_col = current_df[col]

        is_num = pd.api.types.is_numeric_dtype(b_col) and pd.api.types.is_numeric_dtype(c_col)
        psi = calculate_psi(b_col, c_col)

        col_drift = {
            "column": col,
            "dtype": "numeric" if is_num else "categorical",
            "psi": psi,
            "drift_severity": "low" if psi < 0.1 else ("moderate" if psi < alert_threshold_psi else "high"),
        }

        if psi >= alert_threshold_psi:
            alerts.append({
                "severity": "WARNING",
                "title": f"Distribution Drift on '{col}'",
                "column": col,
                "detail": f"Population Stability Index (PSI = {psi:.3f}) exceeded threshold ({alert_threshold_psi}). Population characteristics have significantly shifted.",
            })
            penalties += 15

        if is_num:
            b_mean = float(b_col.mean())
            c_mean = float(c_col.mean())
            pct_change = ((c_mean - b_mean) / (abs(b_mean) + 1e-6)) * 100.0
            col_drift["baseline_mean"] = round(b_mean, 3)
            col_drift["current_mean"] = round(c_mean, 3)
            col_drift["mean_pct_change"] = round(pct_change, 2)

            # Two-sample Kolmogorov-Smirnov test for continuous distribution shift
            b_clean = b_col.dropna()
            c_clean = c_col.dropna()
            if len(b_clean) > 10 and len(c_clean) > 10:
                ks_stat, ks_pval = stats.ks_2samp(b_clean, c_clean)
                col_drift["ks_test_pvalue"] = round(float(ks_pval), 4)

            if abs(pct_change) >= mean_shift_pct_threshold:
                direction = "increased" if pct_change > 0 else "dropped"
                alerts.append({
                    "severity": "CRITICAL" if abs(pct_change) >= mean_shift_pct_threshold * 2 else "WARNING",
                    "title": f"Significant Metric Shift on '{col}'",
                    "column": col,
                    "detail": f"Mean value {direction} by {abs(pct_change):.1f}% (from {b_mean:.2f} to {c_mean:.2f}).",
                })
                penalties += 20

        feature_drifts[col] = col_drift

    health_score = max(0, 100 - penalties)
    status = "HEALTHY" if health_score >= 80 else ("WARNING" if health_score >= 60 else "CRITICAL")

    return {
        "overall_health_score": health_score,
        "status": status,
        "rows_baseline": len(baseline_df),
        "rows_current": len(current_df),
        "columns_evaluated": len(common_cols),
        "total_alerts": len(alerts),
        "alerts": alerts,
        "feature_drifts": feature_drifts,
        "summary": f"Monitoring audit complete. Health Score: {health_score}/100 [{status}]. {len(alerts)} alert(s) triggered across {len(common_cols)} features.",
    }


def send_webhook_alert(webhook_url: str, alert_report: Dict[str, Any], dataset_label: str = "Dataset") -> Dict[str, Any]:
    """Dispatches a formatted alert notification to a webhook endpoint (Slack, Teams, or generic webhook)."""
    if not webhook_url:
        return {"success": False, "error": "No webhook URL provided."}

    alerts = alert_report.get("alerts", [])
    status = alert_report.get("status", "UNKNOWN")
    score = alert_report.get("overall_health_score", 0)

    # Format Slack / Webhook friendly payload
    lines = [
        f"🚨 *GenQ Analytics Monitor Alert: {dataset_label}*",
        f"*Status:* `{status}` | *Health Score:* `{score}/100`",
        f"*Triggered Alerts:* {len(alerts)}",
        "",
    ]
    for a in alerts[:6]:
        icon = "🔴" if a.get("severity") == "CRITICAL" else "🟡"
        lines.append(f"{icon} *[{a.get('severity')}] {a.get('title')}*\n>{a.get('detail')}")

    payload = {
        "text": "\n".join(lines),
        "status": status,
        "health_score": score,
        "alerts_count": len(alerts),
        "alerts": alerts,
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        return {"success": res.status_code in [200, 201, 204], "status_code": res.status_code}
    except Exception as e:
        logger.error("Failed to post webhook alert: %s", e)
        return {"success": False, "error": str(e)}
