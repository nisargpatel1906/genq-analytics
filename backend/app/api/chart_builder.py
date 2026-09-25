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

# ── Currency Detection for Chart Labels ────────────────────────────────────────

def _detect_column_currency(col_name: str, df=None) -> str:
    """Detects the likely currency symbol for a column based on its name.
    Returns the symbol string (e.g., '₹', '$', '€', '£') or '' if not monetary."""
    col_lower = col_name.lower().replace('_', ' ').replace('-', ' ')
    
    currency_map = {
        'inr': '₹', 'rs': '₹', 'rupee': '₹', 'rupees': '₹',
        'usd': '$', 'dollar': '$', 'dollars': '$',
        'eur': '€', 'euro': '€', 'euros': '€',
        'gbp': '£', 'pound': '£', 'pounds': '£',
    }
    for indicator, symbol in currency_map.items():
        if indicator in col_lower.split():
            return symbol
    return ''


def _format_axis_label(col_name: str) -> str:
    """Creates a descriptive axis label with units/currency if detectable."""
    currency = _detect_column_currency(col_name)
    # Clean up the column name for display
    display_name = col_name.replace('_', ' ').title()
    if currency:
        return f"{display_name} ({currency})"
    return display_name


def _format_chart_professional(fig, ax, title: str, subtitle: str = "",
                                x_label: str = "", y_label: str = ""):
    """Applies professional formatting to a matplotlib chart for publication quality."""
    import matplotlib.ticker as ticker
    
    # Title and subtitle
    ax.set_title(title, fontsize=14, fontweight='bold', pad=20, loc='left', color='#1a1a2e')
    if subtitle:
        ax.text(0.0, 1.02, subtitle, transform=ax.transAxes,
                fontsize=9, color='#6B7280', style='italic', va='bottom')
    
    # Axis labels
    if x_label:
        ax.set_xlabel(x_label, fontsize=11, labelpad=8, color='#374151')
    if y_label:
        ax.set_ylabel(y_label, fontsize=11, labelpad=8, color='#374151')
    
    # Grid and spines
    ax.grid(True, alpha=0.25, linestyle='-', linewidth=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#D1D5DB')
    ax.spines['bottom'].set_color('#D1D5DB')
    
    # Tick formatting
    ax.tick_params(axis='both', labelsize=9, colors='#4B5563')
    
    # Format large numbers with thousand separators on y-axis
    try:
        if ax.get_ylim()[1] > 1000:
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(
                lambda x, p: f'{x:,.0f}' if x >= 1 else f'{x:.2f}'
            ))
    except Exception:
        pass
    
    # Source footer
    fig.text(0.99, 0.01, 'GenQ Analytics', fontsize=7, color='#9CA3AF',
             ha='right', va='bottom', style='italic')


def _save(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
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
            fig, ax = plt.subplots(figsize=(10, 5.5))
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

            x_label = _format_axis_label(x) if x else ""
            y_label = _format_axis_label(y) if y else ""
            n_points = len(df)
            subtitle = f"n = {n_points:,} records"
            _format_chart_professional(fig, ax, title, subtitle=subtitle,
                                       x_label=x_label, y_label=y_label)
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
    pregenerated_charts = (
        report_data.get("report", {}).get("_meta", {}).get("chart_images", [])
        or report_data.get("chart_images", [])
        or report_data.get("report", {}).get("chart_images", [])
    )
    charts = []
    if pregenerated_charts:
        for ch in pregenerated_charts:
            try:
                if "data" in ch and isinstance(ch["data"], (bytes, bytearray)):
                    buf = io.BytesIO(ch["data"])
                elif "image_b64" in ch:
                    img_bytes = base64.b64decode(ch["image_b64"])
                    buf = io.BytesIO(img_bytes)
                else:
                    continue
                charts.append({
                    "title": ch.get("title") or ch.get("finding_title") or "Visualization",
                    "buf": buf,
                    "interpretation": ch.get("interpretation") or ch.get("insight_text", "")
                })
            except Exception:
                pass
        if len(charts) >= 3:
            return charts[:5]

    records   = report_data.get("data_sample", [])
    col_types = report_data.get("col_types", {})
    stats     = report_data.get("stats", {})

    if not records:
        return charts

    df = pd.DataFrame(records)
    num_cols, cat_cols, dt_cols, bin_cols = _infer_chart_columns(df, col_types)
    corr_map  = stats.get("correlations", {})

    for c in num_cols:
        df[c] = coerce_numeric_series(df[c])

    sns.set_style("whitegrid")

    visual_plan = report_data.get("report", {}).get("_visualPlan", {})
    planned = _build_planned_charts(df, visual_plan)
    if planned:
        charts.extend(planned)
    if len(charts) >= 4:
        return charts[:4]

    # ── CHART A: Binary target → violin per top-differentiating feature ────────
    if len(charts) < 4 and bin_cols and len(num_cols) >= 2:
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
            fig.suptitle(f"Top Features by '{target}' Class", fontsize=13, fontweight="bold")
            plt.tight_layout()
            fig.text(0.99, 0.01, 'GenQ Analytics', fontsize=7, color='#9CA3AF',
                     ha='right', va='bottom', style='italic')

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
    if len(charts) < 4 and dt_cols and num_cols:
        try:
            dt_col = dt_cols[0]
            df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
            df_t = df.dropna(subset=[dt_col]).sort_values(dt_col)
            best_col = max(num_cols, key=lambda c: df_t[c].std() if df_t[c].std() > 0 else 0)
            trend = df_t.set_index(dt_col)[best_col].resample("D").mean().dropna()
            if len(trend) >= 3:
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.fill_between(trend.index, trend.values, alpha=0.15, color=TABLEAU10[0])
                ax.plot(trend.index, trend.values, color=TABLEAU10[0], linewidth=2)
                
                # Annotate peak and trough
                peak_idx = trend.idxmax()
                trough_idx = trend.idxmin()
                ax.annotate(f'Peak: {trend.max():.1f}',
                           xy=(peak_idx, trend.max()), xytext=(10, 15),
                           textcoords='offset points', fontsize=8, color=TABLEAU10[2],
                           arrowprops=dict(arrowstyle='->', color=TABLEAU10[2], lw=1.2))
                ax.annotate(f'Low: {trend.min():.1f}',
                           xy=(trough_idx, trend.min()), xytext=(10, -20),
                           textcoords='offset points', fontsize=8, color=TABLEAU10[0],
                           arrowprops=dict(arrowstyle='->', color=TABLEAU10[0], lw=1.2))
                
                y_label = _format_axis_label(best_col)
                subtitle = f"Daily average | {len(trend)} data points"
                _format_chart_professional(fig, ax, f"{best_col} Over Time", subtitle=subtitle,
                                           x_label=dt_col, y_label=y_label)
                plt.xticks(rotation=25, fontsize=8)
                plt.tight_layout()
                peak = peak_idx.strftime("%Y-%m-%d")
                interp = (
                    f"Time series of '{best_col}' (selected as the most variable metric). "
                    f"Peak value of {trend.max():.2f} occurred around {peak}. "
                    f"The range spans from {trend.min():.2f} to {trend.max():.2f}. "
                    "Spikes may indicate seasonal patterns, data entry events, or external triggers worth investigating."
                )
                charts.append({"title": f"{best_col} Trend Over Time", "buf": _save(fig), "interpretation": interp})
        except Exception:
            pass

    # ── CHART C: Scatter of strongest correlated pair with regression line ─────
    if len(charts) < 4 and corr_map and len(num_cols) >= 2:
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
                fig, ax = plt.subplots(figsize=(8, 5.5))
                color_note = ""
                if cat_cols and cat_cols[0] in df.columns:
                    groups = df[cat_cols[0]].dropna().unique()[:8]
                    for i, g in enumerate(groups):
                        sub = df[df[cat_cols[0]] == g][[col_a, col_b]].dropna()
                        ax.scatter(sub[col_a], sub[col_b], label=str(g),
                                   alpha=0.65, color=TABLEAU10[i % len(TABLEAU10)], s=32)
                    ax.legend(title=cat_cols[0].replace('_', ' ').title(), fontsize=8, title_fontsize=9,
                             frameon=True, fancybox=True, framealpha=0.9)
                    color_note = f" Points colored by '{cat_cols[0]}'."
                else:
                    ax.scatter(plot_df[col_a], plot_df[col_b], alpha=0.5, color=TABLEAU10[0], s=32)

                z = np.polyfit(plot_df[col_a].fillna(0), plot_df[col_b].fillna(0), 1)
                xline = np.linspace(plot_df[col_a].min(), plot_df[col_a].max(), 100)
                ax.plot(xline, np.poly1d(z)(xline), "--", color="#E15759", linewidth=1.8, label=f"Trend (r={best_r:.2f})")
                ax.legend(fontsize=8)
                
                # Add R² annotation text box
                r_squared = best_r ** 2
                textstr = f'r = {best_r:.3f}\nR² = {r_squared:.3f}\nn = {len(plot_df):,}'
                props = dict(boxstyle='round,pad=0.5', facecolor='#F0F4FF', alpha=0.85, edgecolor='#D1D5DB')
                ax.text(0.97, 0.03, textstr, transform=ax.transAxes, fontsize=9,
                        verticalalignment='bottom', horizontalalignment='right', bbox=props)
                
                x_label = _format_axis_label(col_a)
                y_label = _format_axis_label(col_b)
                strength  = "very strong" if abs(best_r) > 0.8 else "strong" if abs(best_r) > 0.6 else "moderate"
                direction = "positive" if best_r > 0 else "negative"
                subtitle = f"{strength.title()} {direction} correlation | r = {best_r:.2f}, R² = {r_squared:.2f}"
                _format_chart_professional(fig, ax, f"Relationship: {col_a} vs {col_b}",
                                           subtitle=subtitle, x_label=x_label, y_label=y_label)
                plt.tight_layout()

                interp = (
                    f"This scatter plot shows the {strength} {direction} correlation (r = {best_r:.2f}) between "
                    f"'{col_a}' and '{col_b}' — the strongest linear relationship in the dataset.{color_note} "
                    f"R² = {r_squared:.2f} means {col_a} explains {r_squared*100:.1f}% of the variance in {col_b}. "
                    "The dashed line is the regression trend. Points close to the line confirm the relationship "
                    "is consistent; outliers far from it may deserve investigation."
                )
                charts.append({"title": f"Strongest Relationship: {col_a} vs {col_b}", "buf": _save(fig), "interpretation": interp})

    # ── CHART D: Category with biggest metric spread ───────────────────────────
    if len(charts) < 4 and cat_cols and num_cols:
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
                fig, ax = plt.subplots(figsize=(9, max(4, len(gd) * 0.5)))
                bars = ax.barh(gd.index.astype(str), gd["mean"],
                        xerr=gd["std"].fillna(0), capsize=4,
                        color=TABLEAU10[:len(gd)], alpha=0.88, height=0.6)
                
                # Add value labels on bars
                currency_symbol = _detect_column_currency(best_metric)
                for i, (idx, row) in enumerate(gd.iterrows()):
                    label = f"{currency_symbol}{row['mean']:,.1f}" if currency_symbol else f"{row['mean']:,.1f}"
                    ax.text(row['mean'] + gd['std'].max() * 0.1, i, label,
                           va='center', ha='left', fontsize=8, color='#374151', fontweight='bold')
                
                x_label = _format_axis_label(best_metric)
                subtitle = f"Mean values with ±1 std dev | {len(gd)} groups"
                _format_chart_professional(fig, ax, f"{best_metric} by {best_cat}",
                                           subtitle=subtitle, x_label=x_label, y_label="")
                plt.tight_layout()

                top_g = gd["mean"].idxmax()
                bot_g = gd["mean"].idxmin()
                pct   = ((gd.loc[top_g, "mean"] - gd.loc[bot_g, "mean"]) /
                          max(abs(gd.loc[bot_g, "mean"]), 1)) * 100
                interp = (
                    f"Horizontal bars compare average '{best_metric}' across each '{best_cat}' group. "
                    f"'{top_g}' is highest ({currency_symbol}{gd.loc[top_g,'mean']:,.2f}) and '{bot_g}' is lowest ({currency_symbol}{gd.loc[bot_g,'mean']:,.2f}) "
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
            fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 4.5))
            if n == 1:
                axes = [axes]
            for i, (_, sk, col) in enumerate(skews):
                vals = df[col].dropna()
                axes[i].hist(vals, bins=30, color=TABLEAU10[i], alpha=0.82, edgecolor="white")
                axes[i].axvline(vals.mean(),   color="#E15759", lw=1.8, ls="--", label=f"Mean {vals.mean():.2f}")
                axes[i].axvline(vals.median(), color="#4E79A7", lw=1.8, ls=":",  label=f"Median {vals.median():.2f}")
                axes[i].legend(fontsize=8, frameon=True, fancybox=True, framealpha=0.9)
                x_label = _format_axis_label(col)
                axes[i].set_xlabel(x_label, fontsize=9)
                axes[i].set_ylabel('Frequency', fontsize=9)
                axes[i].set_title(f"{col[:18]} (skew={sk:.2f})", fontsize=10, fontweight="bold")
                axes[i].spines["top"].set_visible(False)
                axes[i].spines["right"].set_visible(False)
                axes[i].grid(True, alpha=0.2)
            fig.suptitle("Value Distribution — Most Skewed Columns", fontsize=13, fontweight="bold")
            plt.tight_layout()
            fig.text(0.99, 0.01, 'GenQ Analytics', fontsize=7, color='#9CA3AF',
                     ha='right', va='bottom', style='italic')

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

            fig, ax = plt.subplots(figsize=(9, max(4, len(counts) * 0.45)))
            bars = ax.barh(counts.index, counts.values, color=[TABLEAU10[i % len(TABLEAU10)] for i in range(len(counts))], alpha=0.88)
            
            # Add value labels on bars
            for i, (idx, val) in enumerate(zip(counts.index, counts.values)):
                ax.text(val + counts.max() * 0.02, i, f'{int(val):,}',
                       va='center', ha='left', fontsize=8, color='#374151', fontweight='bold')
            
            subtitle = f"{len(counts)} categories shown"
            _format_chart_professional(fig, ax, f"Record Count by {cat}",
                                       subtitle=subtitle, x_label="Records", y_label="")
            plt.tight_layout()

            top_label = counts.idxmax()
            top_count = int(counts.max())
            total = int(counts.sum())
            interp = (
                f"This chart shows how records are distributed across '{cat}'. "
                f"'{top_label}' is the largest group with {top_count:,} of the top {total:,} displayed records "
                f"({top_count/total*100:.1f}% share). "
                "This is useful for profile-style datasets where most fields are descriptive rather than numeric."
            )
            charts.append({"title": f"Record Count by {cat}", "buf": _save(fig), "interpretation": interp})

    return charts
