import io
import base64
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.facecolor'] = 'white'
matplotlib.rcParams['axes.facecolor'] = 'white'
matplotlib.rcParams['savefig.facecolor'] = 'white'
import matplotlib.pyplot as plt
import seaborn as sns
from app.utils import coerce_numeric_series

TABLEAU10 = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F",
             "#EDC949", "#AF7AA1", "#FF9DA7", "#9C755F", "#BAB0AB"]

def _save(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    buf.seek(0)
    plt.close(fig)
    return buf

def _infer_chart_columns(df: pd.DataFrame, col_types: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    configured_num = col_types.get("numeric", [])
    configured_cat = col_types.get("categorical", [])
    configured_dt = col_types.get("datetime", [])
    configured_bin = col_types.get("binary", [])

    num_cols = [c for c in configured_num if c in df.columns]
    cat_cols = [c for c in configured_cat if c in df.columns]
    dt_cols = [c for c in configured_dt if c in df.columns]
    bin_cols = [c for c in configured_bin if c in df.columns]

    for col in df.columns:
        if col in num_cols:
            continue

        numeric = coerce_numeric_series(df[col])
        non_null_ratio = numeric.notna().mean()
        unique_ratio = numeric.nunique(dropna=True) / max(len(numeric.dropna()), 1)
        looks_like_identifier = any(token in col.lower() for token in ["id", "code", "phone", "zip", "pin"])

        if non_null_ratio >= 0.65 and (unique_ratio < 0.98 or not looks_like_identifier):
            df[col] = numeric
            num_cols.append(col)
            if col in cat_cols:
                cat_cols.remove(col)
        elif col not in cat_cols:
            cat_cols.append(col)

    for col in df.columns:
        if col in dt_cols or col in num_cols:
            continue
        if not any(token in col.lower() for token in ["date", "time", "created", "updated"]):
            continue
        parsed = pd.to_datetime(df[col], errors="coerce")
        if parsed.notna().mean() >= 0.65:
            df[col] = parsed
            dt_cols.append(col)
            if col in cat_cols:
                cat_cols.remove(col)

    for col in num_cols:
        unique_vals = set(df[col].dropna().unique())
        if len(unique_vals) == 2 and unique_vals.issubset({0, 1, True, False}) and col not in bin_cols:
            bin_cols.append(col)

    return num_cols, cat_cols, dt_cols, bin_cols

def _build_planned_charts(df: pd.DataFrame, plan: dict) -> list:
    charts = []
    for spec in plan.get("charts", [])[:4] if isinstance(plan, dict) else []:
        chart_type = spec.get("type")
        x, y = spec.get("x"), spec.get("y")
        if x is not None and x not in df.columns:
            continue
        if y is not None and y not in df.columns:
            continue

        try:
            fig, ax = plt.subplots(figsize=(9, 4.8))
            title = str(spec.get("title") or "Data visualization")
            reason = str(spec.get("reason") or "Supports the verified report findings.")

            if chart_type == "histogram" and x:
                values = coerce_numeric_series(df[x]).dropna()
                if values.empty:
                    plt.close(fig)
                    continue
                ax.hist(values, bins=min(30, max(8, int(np.sqrt(len(values))))), color=TABLEAU10[0], alpha=0.85, edgecolor="white")
                ax.axvline(values.median(), color=TABLEAU10[2], linestyle="--", linewidth=1.5, label=f"Median {values.median():.2f}")
                ax.legend(fontsize=8)
                ax.set_xlabel(x)

            elif chart_type == "scatter" and x and y:
                x_values, y_values = coerce_numeric_series(df[x]), coerce_numeric_series(df[y])
                valid = x_values.notna() & y_values.notna()
                if valid.sum() < 2:
                    plt.close(fig)
                    continue
                ax.scatter(x_values[valid], y_values[valid], color=TABLEAU10[0], alpha=0.65, s=28)
                ax.set_xlabel(x)
                ax.set_ylabel(y)

            elif chart_type == "line" and x and y:
                values = pd.DataFrame({"x": df[x], "y": coerce_numeric_series(df[y])}).dropna()
                if values.empty:
                    plt.close(fig)
                    continue
                parsed = pd.to_datetime(values["x"], errors="coerce")
                if parsed.notna().mean() >= 0.65:
                    values["x"] = parsed
                values = values.sort_values("x")
                ax.plot(values["x"], values["y"], color=TABLEAU10[0], linewidth=2)
                ax.set_xlabel(x)
                ax.set_ylabel(y)
                fig.autofmt_xdate()

            elif chart_type == "box" and x and y:
                values = pd.DataFrame({x: df[x].astype(str), y: coerce_numeric_series(df[y])}).dropna()
                top_groups = values[x].value_counts().head(10).index
                values = values[values[x].isin(top_groups)]
                if values.empty:
                    plt.close(fig)
                    continue
                sns.boxplot(data=values, x=x, y=y, ax=ax, color=TABLEAU10[3])
                ax.tick_params(axis="x", rotation=30)

            elif chart_type == "heatmap":
                numeric = df.apply(coerce_numeric_series).dropna(axis=1, how="all")
                numeric = numeric.loc[:, numeric.nunique() > 1]
                if numeric.shape[1] < 2:
                    plt.close(fig)
                    continue
                sns.heatmap(numeric.corr().iloc[:12, :12], cmap="vlag", center=0, ax=ax, annot=numeric.shape[1] <= 7, fmt=".2f")

            elif chart_type in {"bar", "count"} and x:
                if chart_type == "count" or not y or spec.get("aggregation") == "count":
                    grouped = df[x].fillna("Unknown").astype(str).value_counts().head(12).sort_values()
                    ylabel = "Records"
                else:
                    values = pd.DataFrame({x: df[x].astype(str), y: coerce_numeric_series(df[y])}).dropna()
                    aggregation = spec.get("aggregation", "mean")
                    if aggregation not in {"mean", "sum", "median"}:
                        aggregation = "mean"
                    grouped = values.groupby(x)[y].agg(aggregation).nlargest(12).sort_values()
                    ylabel = f"{aggregation.title()} {y}"
                if grouped.empty:
                    plt.close(fig)
                    continue
                ax.barh(grouped.index.astype(str), grouped.values, color=[TABLEAU10[i % len(TABLEAU10)] for i in range(len(grouped))], alpha=0.88)
                ax.set_xlabel(ylabel)

            else:
                plt.close(fig)
                continue

            ax.set_title(title, fontsize=12, fontweight="bold")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            plt.tight_layout()
            charts.append({"title": title, "buf": _save(fig), "interpretation": reason})
        except (TypeError, ValueError, KeyError):
            plt.close("all")
            continue
    return charts

def build_charts(report_data: dict) -> list:
    """
    Examines the actual dataset structure and generates only charts that
    answer a real analytical question about THIS specific data.
    Returns: [{title, buf, interpretation}, ...]
    """
    # Check if there are pre-generated chart images from the agentic code-gen pipeline
    pregenerated_charts = report_data.get("report", {}).get("_meta", {}).get("chart_images", [])
    if pregenerated_charts:
        charts = []
        for ch in pregenerated_charts:
            try:
                img_bytes = base64.b64decode(ch["image_b64"])
                buf = io.BytesIO(img_bytes)
                charts.append({
                    "title": ch["title"],
                    "buf": buf,
                    "interpretation": ch["interpretation"]
                })
            except Exception:
                pass
        if charts:
            return charts

    charts = []
    records   = report_data.get("data_sample", [])
    col_types = report_data.get("col_types", {})
    stats     = report_data.get("stats", {})

    if not records:
        return []

    df = pd.DataFrame(records)
    num_cols, cat_cols, dt_cols, bin_cols = _infer_chart_columns(df, col_types)
    corr_map  = stats.get("correlations", {})

    for c in num_cols:
        df[c] = coerce_numeric_series(df[c])

    sns.set_style("whitegrid")

    visual_plan = report_data.get("report", {}).get("_visualPlan", {})
    charts.extend(_build_planned_charts(df, visual_plan))
    if len(charts) >= 2:
        return charts[:4]

    # ── CHART A: Binary target → violin per top-differentiating feature ────────
    if bin_cols and len(num_cols) >= 2:
        target     = bin_cols[0]
        non_target = [c for c in num_cols if c != target]
        c0 = df[df[target] == 0]
        c1 = df[df[target] == 1]
        diffs = sorted(
            [(abs(c1[c].mean() - c0[c].mean()) / (c0[c].std() + 1e-9), c)
             for c in non_target
             if pd.notna(c0[c].mean()) and pd.notna(c1[c].mean()) and c0[c].std() > 0],
            reverse=True
        )
        top4 = [d[1] for d in diffs[:4]]
        if top4:
            fig, axes = plt.subplots(1, len(top4), figsize=(4 * len(top4), 4))
            if len(top4) == 1:
                axes = [axes]
            class_vals = sorted(df[target].dropna().unique())
            labels = [f"Class {int(v)}" for v in class_vals]
            for i, col in enumerate(top4):
                data = [df[df[target] == v][col].dropna().values for v in class_vals]
                axes[i].violinplot(data, positions=range(len(data)), showmedians=True)
                axes[i].set_xticks(range(len(labels)))
                axes[i].set_xticklabels(labels, fontsize=8)
                axes[i].set_title(col[:18], fontsize=9, fontweight="bold")
                axes[i].spines["top"].set_visible(False)
                axes[i].spines["right"].set_visible(False)
            fig.suptitle(f"Top Features by '{target}' Class", fontsize=11, fontweight="bold")
            plt.tight_layout()

            parts = []
            for _, feat in diffs[:3]:
                m0, m1 = c0[feat].mean(), c1[feat].mean()
                parts.append(f"'{feat}' averages {m0:.2f} (class 0) vs {m1:.2f} (class 1)")
            interp = (
                f"Violin plots compare the distribution of each feature split by '{target}'. "
                "Wider sections show where most values cluster; the white dot is the median. "
                "Features shown were selected because they differ most between classes — "
                "they are the strongest natural predictors in this dataset. "
                + " | ".join(parts) + "."
            )
            charts.append({"title": f"Feature Distributions by {target}", "buf": _save(fig), "interpretation": interp})

    # ── CHART B: Time series if datetime exists ────────────────────────────────
    elif dt_cols and num_cols:
        try:
            dt_col = dt_cols[0]
            df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
            df_t = df.dropna(subset=[dt_col]).sort_values(dt_col)
            best_col = max(num_cols, key=lambda c: df_t[c].std() if df_t[c].std() > 0 else 0)
            trend = df_t.set_index(dt_col)[best_col].resample("D").mean().dropna()
            if len(trend) >= 3:
                fig, ax = plt.subplots(figsize=(9, 3.8))
                ax.fill_between(trend.index, trend.values, alpha=0.2, color=TABLEAU10[0])
                ax.plot(trend.index, trend.values, color=TABLEAU10[0], linewidth=1.5)
                ax.set_xlabel(dt_col, fontsize=9)
                ax.set_ylabel(best_col, fontsize=9)
                ax.set_title(f"{best_col} Over Time", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.xticks(rotation=25, fontsize=8)
                plt.tight_layout()
                peak = trend.idxmax().strftime("%Y-%m-%d")
                interp = (
                    f"Time series of '{best_col}' (selected as the most variable metric). "
                    f"Peak value occurred around {peak}. "
                    "Spikes may indicate seasonal patterns, data entry events, or external triggers worth investigating."
                )
                charts.append({"title": f"{best_col} Trend Over Time", "buf": _save(fig), "interpretation": interp})
        except Exception:
            pass

    # ── CHART C: Scatter of strongest correlated pair with regression line ─────
    if corr_map and len(num_cols) >= 2:
        best_r, col_a, col_b = 0.0, None, None
        keys = list(corr_map.keys())
        for i, a in enumerate(keys):
            for b in keys[i+1:]:
                r = corr_map.get(a, {}).get(b)
                if r is not None and abs(r) > abs(best_r):
                    best_r, col_a, col_b = r, a, b

        if col_a and col_b and abs(best_r) > 0.30 and col_a in df.columns and col_b in df.columns:
            plot_df = df[[col_a, col_b]].dropna()
            if len(plot_df) > 10:
                fig, ax = plt.subplots(figsize=(6.5, 4.5))
                color_note = ""
                if cat_cols and cat_cols[0] in df.columns:
                    groups = df[cat_cols[0]].dropna().unique()[:8]
                    for i, g in enumerate(groups):
                        sub = df[df[cat_cols[0]] == g][[col_a, col_b]].dropna()
                        ax.scatter(sub[col_a], sub[col_b], label=str(g),
                                   alpha=0.65, color=TABLEAU10[i % len(TABLEAU10)], s=28)
                    ax.legend(title=cat_cols[0], fontsize=8, title_fontsize=8)
                    color_note = f" Points colored by '{cat_cols[0]}'."
                else:
                    ax.scatter(plot_df[col_a], plot_df[col_b], alpha=0.5, color=TABLEAU10[0], s=28)

                z = np.polyfit(plot_df[col_a].fillna(0), plot_df[col_b].fillna(0), 1)
                xline = np.linspace(plot_df[col_a].min(), plot_df[col_a].max(), 100)
                ax.plot(xline, np.poly1d(z)(xline), "--", color="#E15759", linewidth=1.5, label=f"r={best_r:.2f}")
                ax.legend(fontsize=8)
                ax.set_xlabel(col_a, fontsize=9)
                ax.set_ylabel(col_b, fontsize=9)
                ax.set_title(f"Relationship: {col_a} vs {col_b}", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.tight_layout()

                strength  = "very strong" if abs(best_r) > 0.8 else "strong" if abs(best_r) > 0.6 else "moderate"
                direction = "positive" if best_r > 0 else "negative"
                interp = (
                    f"This scatter plot shows the {strength} {direction} correlation (r = {best_r:.2f}) between "
                    f"'{col_a}' and '{col_b}' — the strongest linear relationship in the dataset.{color_note} "
                    "The dashed line is the regression trend. Points close to the line confirm the relationship "
                    "is consistent; outliers far from it may deserve investigation."
                )
                charts.append({"title": f"Strongest Relationship: {col_a} vs {col_b}", "buf": _save(fig), "interpretation": interp})

    # ── CHART D: Category with biggest metric spread ───────────────────────────
    if cat_cols and num_cols:
        valid_cats = [(c, df[c].nunique()) for c in cat_cols if 2 <= df[c].nunique() <= 12]
        valid_cats.sort(key=lambda x: x[1])
        if valid_cats:
            best_cat = valid_cats[0][0]
            best_metric, best_spread = None, 0
            for nc in num_cols:
                gmeans = df.groupby(best_cat)[nc].mean()
                spread = gmeans.max() - gmeans.min()
                if pd.notna(spread) and spread > best_spread:
                    best_spread, best_metric = spread, nc

            if best_metric:
                gd = df.groupby(best_cat)[best_metric].agg(["mean", "std"]).dropna()
                gd = gd.sort_values("mean", ascending=True)
                fig, ax = plt.subplots(figsize=(8, max(3.5, len(gd) * 0.45)))
                ax.barh(gd.index.astype(str), gd["mean"],
                        xerr=gd["std"].fillna(0), capsize=4,
                        color=TABLEAU10[:len(gd)], alpha=0.85, height=0.6)
                ax.set_xlabel(f"Mean {best_metric}", fontsize=9)
                ax.set_title(f"{best_metric} by {best_cat}", fontsize=11, fontweight="bold")
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                plt.tight_layout()

                top_g = gd["mean"].idxmax()
                bot_g = gd["mean"].idxmin()
                pct   = ((gd.loc[top_g, "mean"] - gd.loc[bot_g, "mean"]) /
                          max(abs(gd.loc[bot_g, "mean"]), 1)) * 100
                interp = (
                    f"Horizontal bars compare average '{best_metric}' across each '{best_cat}' group. "
                    f"'{top_g}' is highest ({gd.loc[top_g,'mean']:.2f}) and '{bot_g}' is lowest ({gd.loc[bot_g,'mean']:.2f}) "
                    f"— a {pct:.0f}% difference. Error bars show ± one standard deviation. "
                    "Groups with wide bars are internally variable; narrow bars mean consistent behaviour within that group."
                )
                charts.append({"title": f"{best_metric} by {best_cat}", "buf": _save(fig), "interpretation": interp})

    # ── CHART E: Histograms of most skewed columns ────────────────────────────
    if num_cols:
        skews = sorted(
            [(abs(df[c].skew()), df[c].skew(), c) for c in num_cols if pd.notna(df[c].skew())],
            reverse=True
        )[:3]
        if skews:
            n = len(skews)
            fig, axes = plt.subplots(1, n, figsize=(5 * n, 4))
            if n == 1:
                axes = [axes]
            for i, (_, sk, col) in enumerate(skews):
                vals = df[col].dropna()
                axes[i].hist(vals, bins=30, color=TABLEAU10[i], alpha=0.82, edgecolor="white")
                axes[i].axvline(vals.mean(),   color="#E15759", lw=1.5, ls="--", label=f"Mean {vals.mean():.2f}")
                axes[i].axvline(vals.median(), color="#4E79A7", lw=1.5, ls=":",  label=f"Median {vals.median():.2f}")
                axes[i].legend(fontsize=7)
                axes[i].set_xlabel(col, fontsize=9)
                axes[i].set_title(f"{col[:16]} (skew={sk:.2f})", fontsize=9, fontweight="bold")
                axes[i].spines["top"].set_visible(False)
                axes[i].spines["right"].set_visible(False)
            fig.suptitle("Value Distribution — Most Skewed Columns", fontsize=11, fontweight="bold")
            plt.tight_layout()

            descs = []
            for _, sk, col in skews:
                if sk > 1:   descs.append(f"'{col}' is right-skewed (skew={sk:.2f})")
                elif sk < -1: descs.append(f"'{col}' is left-skewed (skew={sk:.2f})")
                else:         descs.append(f"'{col}' is near-symmetric (skew={sk:.2f})")
            interp = (
                "Histograms show the distribution shape of the most skewed numeric columns. "
                "Red dashed = mean; blue dotted = median. When they diverge, the data is skewed. "
                + " | ".join(descs) + ". "
                "Strongly skewed columns are good candidates for log-transformation before modeling."
            )
            charts.append({"title": "Value Distribution Analysis", "buf": _save(fig), "interpretation": interp})

    # ── CHART F: Categorical composition when numeric metrics are absent or sparse ──
    if len(charts) < 2 and cat_cols:
        valid_cats = [
            (c, df[c].nunique(dropna=True))
            for c in cat_cols
            if 2 <= df[c].nunique(dropna=True) <= 20
        ]
        valid_cats.sort(key=lambda x: x[1])
        for cat, _ in valid_cats[:2]:
            counts = df[cat].fillna("Unknown").astype(str).value_counts().head(12).sort_values()
            if counts.empty:
                continue

            fig, ax = plt.subplots(figsize=(8, max(3.5, len(counts) * 0.42)))
            ax.barh(counts.index, counts.values, color=[TABLEAU10[i % len(TABLEAU10)] for i in range(len(counts))], alpha=0.88)
            ax.set_xlabel("Records", fontsize=9)
            ax.set_title(f"Record Count by {cat}", fontsize=11, fontweight="bold")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            plt.tight_layout()

            top_label = counts.idxmax()
            top_count = int(counts.max())
            total = int(counts.sum())
            interp = (
                f"This chart shows how records are distributed across '{cat}'. "
                f"'{top_label}' is the largest group with {top_count:,} of the top {total:,} displayed records. "
                "This is useful for profile-style datasets where most fields are descriptive rather than numeric."
            )
            charts.append({"title": f"Record Count by {cat}", "buf": _save(fig), "interpretation": interp})

    return charts
