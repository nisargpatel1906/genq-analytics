import logging
import pandas as pd
import numpy as np
import json
import os
import requests
import re
from dotenv import load_dotenv

logger = logging.getLogger("genq_api.analyzer")

load_dotenv()

# Configure Ollama (Local LLM fallback)
ollama_model = os.environ.get("OLLAMA_MODEL") # e.g. 'llama3.1' or 'mistral'
ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

SYSTEM_PROMPT = """
You are a senior quantitative data analyst with 20 years of experience in financial and business analytics.

Your task:
1. UNDERSTAND the dataset: infer what the data represents from column names, types, and value ranges.
2. ANALYZE: surface the most meaningful patterns, trends, outliers, and correlations.
3. NARRATE: Write findings as a human analyst would — with specific numbers, percentages, comparisons.
4. RECOMMEND: Provide 3-5 specific, actionable recommendations grounded in the data.

You MUST:
- State the domain (e.g. "This appears to be healthcare patient data from...")
- Quote specific column values, group-by statistics, and exact anomaly values in your narrative.
- DO NOT use LaTeX formatting or math blocks like $\text{r} = 0.96$. Use plain text like "r = 0.96".
- Assign a confidence score (0-100) to each major claim
- Flag specific data anomalies with clear business impact.

Output ONLY this exact JSON schema:
{
  "domain": "string",
  "executiveSummary": "string (3-paragraph narrative, 400-600 words)",
  "keyFindings": [
    { "title": "string", "detail": "string (2-3 sentences, cite specific numbers)", "confidence": 85 }
  ],
  "anomalies": [
    { "column": "string", "description": "string", "severity": "low|medium|high", "businessImpact": "string" }
  ],
  "recommendations": [
    { "action": "string", "rationale": "string", "priority": "high|medium|low" }
  ]
}
"""

def map_schema(df: pd.DataFrame) -> dict:
    return {col: str(dtype) for col, dtype in df.dtypes.items()}

def parse_report_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    # Strip LaTeX formatting if the LLM hallucinates it
    content = re.sub(r'\$\\text\{([a-zA-Z]+)\}\s*=\s*([0-9\.]+)\$', r'\1 = \2', content)
    content = content.replace('$', '')
    content = content.replace('\\n', ' ')
    
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON output: {e}")
        logger.debug(f"Raw output: {content}")
        return {"error": "Failed to parse JSON", "raw": content}

def analyze_dataframe(df: pd.DataFrame) -> dict:
    if not ollama_model:
        return {"error": "OLLAMA_MODEL is not configured in backend/.env"}
        
    stats = extract_statistics(df)
    schema_summary = map_schema(df)
    
    prompt = f"Dataset schema: {schema_summary}\n\nStatistical summary: {json.dumps(stats, default=str)}\n\nGenerate report JSON:"
    
    logger.info(f"Sending prompt to local Ollama API (model: {ollama_model})...")
    try:
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": ollama_model,
                "system": SYSTEM_PROMPT,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "keep_alive": 0,  # Don't carry over context from previous requests
                "options": {
                    "num_gpu": 99  # Use all GPU layers (RTX 3060)
                }
            },
            timeout=1200 # Local generation can take a long time (up to 20 mins) for large models
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Received response from Ollama API.")
        return parse_report_json(data.get("response", "{}"))
    except Exception as e:
        logger.error(f"Ollama API Exception: {e}")
        return {"error": str(e)}

def extract_statistics(df: pd.DataFrame) -> dict:
    stats = {}
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    
    stats["shape"] = {"rows": len(df), "columns": len(df.columns)}
    stats["missing_values"] = df.isnull().sum().to_dict()
    
    # Replace NaN and Inf with None for JSON compliance
    if not numeric_cols.empty:
        desc = df[numeric_cols].describe().replace({np.nan: None, np.inf: None, -np.inf: None})
        stats["numeric_summary"] = desc.to_dict()
        
        if len(numeric_cols) > 1:
            corr = df[numeric_cols].corr().replace({np.nan: None, np.inf: None, -np.inf: None})
            stats["correlations"] = corr.to_dict()
    else:
        stats["numeric_summary"] = {}
        stats["correlations"] = {}
    
    # Outlier detection (Z-score > 3 sigma)
    anomalies = []
    for col in numeric_cols:
        mean = df[col].mean()
        std = df[col].std()
        if pd.isna(mean) or pd.isna(std) or std == 0: continue
        z_scores = np.abs((df[col] - mean) / std)
        outliers = df[z_scores > 3]
        if not outliers.empty:
            anomalies.append({
                "column": col,
                "outlier_count": len(outliers),
                "max_deviation_value": float(outliers[col].max() if outliers[col].max() > mean else outliers[col].min()),
                "mean": float(mean),
                "threshold_3sigma": float(mean + 3*std)
            })
    stats["statistical_anomalies"] = anomalies

    # Grouped stats for classification datasets
    cat_cols = df.select_dtypes(include=['object', 'category']).columns
    grouped_stats = {}
    for cat in cat_cols:
        if 1 < df[cat].nunique() <= 10:
            grouped = df.groupby(cat)[numeric_cols].mean().replace({np.nan: None, np.inf: None, -np.inf: None})
            grouped_stats[cat] = grouped.to_dict()
    if grouped_stats:
        stats["grouped_summary"] = grouped_stats

    return stats
