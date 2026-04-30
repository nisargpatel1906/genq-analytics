import pandas as pd

def generate_chart_configs(df: pd.DataFrame, ai_report: dict) -> list:
    """
    Returns list of Recharts-compatible config objects for frontend rendering.
    Now AI-driven: uses the suggestedCharts array from the Gemini report.
    """
    suggested = ai_report.get("suggestedCharts", [])
    
    # Fallback if AI didn't provide charts or failed
    if not suggested:
        return _fallback_configs(df)

    configs = []
    for chart in suggested:
        col_x = chart.get("xKey")
        col_y = chart.get("yKey")
        
        # Validate columns exist
        if not col_x or not col_y or col_x not in df.columns or col_y not in df.columns:
            continue
            
        try:
            # Drop NaNs and take a reasonable sample size for frontend performance
            chart_df = df[[col_x, col_y]].dropna()
            
            # If it's categorical on X, we might need to aggregate
            if df[col_x].dtype == 'object' and chart.get("type") in ["BarChart", "PieChart"]:
                # Get top categories by mean or count
                top_cats = chart_df[col_x].value_counts().head(10).index
                filtered = chart_df[chart_df[col_x].isin(top_cats)]
                if pd.api.types.is_numeric_dtype(df[col_y]):
                    data = filtered.groupby(col_x)[col_y].mean().reset_index().to_dict('records')
                else:
                    # If y is also categorical, we just count occurrences
                    data = filtered.groupby(col_x)[col_y].count().reset_index().to_dict('records')
            else:
                data = chart_df.head(100).to_dict('records')

            configs.append({
                "type": chart.get("type", "BarChart"),
                "title": chart.get("title", f"{col_y} by {col_x}"),
                "rationale": chart.get("rationale", ""),
                "data": data,
                "xKey": col_x,
                "yKey": col_y
            })
        except Exception as e:
            print(f"Error generating chart for {col_x} and {col_y}: {e}")
            continue
            
    # Add Heatmap if AI suggested it but didn't provide specific x/y keys
    heatmap_requested = any(c.get("type") == "Heatmap" for c in suggested)
    if heatmap_requested:
        numeric_cols = df.select_dtypes(include='number').columns.tolist()
        if len(numeric_cols) >= 3:
            import numpy as np
            corr = df[numeric_cols[:6]].corr().replace({np.nan: 0, np.inf: 0, -np.inf: 0})
            configs.append({
                "type": "Heatmap",
                "title": "Correlation Matrix",
                "rationale": "Displays relationships between key numerical variables to identify potential drivers.",
                "data": corr.to_dict(),
                "columns": numeric_cols[:6]
            })

    return configs if configs else _fallback_configs(df)

def _fallback_configs(df: pd.DataFrame) -> list:
    """Old hardcoded rules as a fallback mechanism"""
    configs = []
    numeric_cols = df.select_dtypes(include='number').columns.tolist()
    datetime_cols = df.select_dtypes(include='datetime').columns.tolist()
    cat_cols = df.select_dtypes(include='object').columns.tolist()
    
    if datetime_cols and numeric_cols:
        configs.append({
            "type": "AreaChart",
            "title": f"{numeric_cols[0]} Over Time",
            "data": df.groupby(datetime_cols[0])[numeric_cols[0]].mean().reset_index().to_dict('records'),
            "xKey": datetime_cols[0],
            "yKey": numeric_cols[0]
        })
    
    if cat_cols and numeric_cols:
        top_cat = df[cat_cols[0]].value_counts().head(8).index
        bar_data = df[df[cat_cols[0]].isin(top_cat)].groupby(cat_cols[0])[numeric_cols[0]].mean()
        configs.append({
            "type": "BarChart",
            "title": f"{numeric_cols[0]} by {cat_cols[0]}",
            "data": bar_data.reset_index().to_dict('records'),
            "xKey": cat_cols[0],
            "yKey": numeric_cols[0],
        })
    return configs
