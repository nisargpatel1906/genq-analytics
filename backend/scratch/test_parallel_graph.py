import sys
sys.path.insert(0, '.')

import time
import pandas as pd
import json
import logging
import threading
from unittest.mock import patch, MagicMock

# Configure basic logging to see timestamps
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s"
)
logger = logging.getLogger("test_parallel")

from services.agent_graph import AnalysisState, AgentGraph
from services.code_executor import ExecutionResult

def test_parallel_execution():
    logger.info("Setting up mock analysis state...")
    df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
    
    state = AnalysisState(
        df=df,
        schema={"col1": "int64", "col2": "object"},
        sample_rows=[{"col1": 1, "col2": "a"}],
        domain_brief={"domain": "Test Domain", "datasetPurpose": "Testing concurrency", "datasetType": "cross-sectional"},
        stats={},
        progress_callback=lambda event: logger.info(f"Progress Callback: {event['currentAgent']} - {event['status']} - {event['detail']}"),
        use_notebook_mode=False  # use flat script to test viz coder and report writer easily
    )
    
    # Mock responses for chat_completion
    def mock_chat_completion(messages, task, json_mode=False, timeout=600):
        agent_thread = threading.current_thread().name
        logger.info(f"mock_chat_completion invoked for task '{task}' on thread '{agent_thread}'")
        
        if task == "analysis":
            return "```python\n# dummy analysis code\n```"
            
        elif task == "review": # Reflector / Auditor
            is_reflector = any("reflector" in m.get("content", "").lower() or "reflect" in m.get("content", "").lower() for m in messages)
            if is_reflector:
                return json.dumps({"needs_more_analysis": False, "feedback": "", "follow_up_tasks": []})
            else: # auditor
                return json.dumps({
                    "approved": True,
                    "score": 95,
                    "sectionScores": {"analytical_depth": 95, "specificity": 95, "formatting_and_alignment": 95},
                    "summary": "Perfect report.",
                    "issues": [],
                    "retryTargets": []
                })
                
        elif task == "visual":
            logger.info("Viz Coder LLM call start (simulating 2s latency)...")
            time.sleep(2)
            logger.info("Viz Coder LLM call complete.")
            return "```python\n# dummy visual code\n```"
            
        elif task == "report":
            # Differentiate Report Writer from Narrative Stitcher by system prompt contents
            is_stitcher = any("executive editor" in m.get("content", "").lower() for m in messages)
            if not is_stitcher:
                logger.info("Report Writer LLM call start (simulating 2s latency)...")
                time.sleep(2)
                logger.info("Report Writer LLM call complete.")
                return json.dumps({
                    "domain": "Test Domain",
                    "executiveSummary": "Paragraph 1\n\nParagraph 2\n\nParagraph 3",
                    "keyFindings": [
                        {
                            "title": "Engagement Peak",
                            "detail": "Peak is observed at 6 PM based on high transaction volume.",
                            "confidence": 95,
                            "impact_score": 9,
                            "supporting_chart": None
                        }
                    ],
                    "anomalies": [],
                    "recommendations": []
                })
            else:
                logger.info("Narrative Stitcher LLM call start...")
                return "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
            
        return "{}"

    # Mock responses for execute_analysis_code
    def mock_execute_analysis_code(code, df, timeout_seconds=90):
        agent_thread = threading.current_thread().name
        logger.info(f"mock_execute_analysis_code invoked on thread '{agent_thread}'")
        
        # Determine if it's the data scientist node or viz coder node executing
        if "visual" in code or "viz" in code or "chart" in code or len(state.analysis_results) > 0:
            # Viz coder execution output
            return ExecutionResult(
                success=True,
                stdout="",
                stderr="",
                agent_outputs=[{
                    "filename": "peak_chart.png",
                    "type": "image",
                    "purpose": "Shows peak engagement",
                    "finding_title": "Engagement Peak",
                    "interpretation": "Clearly shows peak at 6 PM",
                    "insight_text": "Peak at 6 PM",
                    "primary": False,
                    "data": b"dummy image bytes"
                }]
            )
        else:
            # Data scientist execution output
            return ExecutionResult(
                success=True,
                stdout="",
                stderr="",
                agent_outputs=[{
                    "filename": "instagram_engagement_analysis.json",
                    "type": "analysis_results",
                    "purpose": "Test",
                    "primary": True,
                    "data": {"findings": [{"title": "Engagement Peak", "evidence": "Peak at 6 PM"}], "anomalies": [], "recommendations": []}
                }]
            )

    original_parallel_func = AgentGraph._run_visuals_and_report_in_parallel
    parallel_duration = [0.0]
    
    def timed_parallel(self):
        t_p_start = time.perf_counter()
        original_parallel_func(self)
        parallel_duration[0] = time.perf_counter() - t_p_start

    logger.info("Starting pipeline execution with mocked LLMs and execution engine...")
    with patch("services.agent_graph.chat_completion", side_effect=mock_chat_completion), \
         patch("services.agent_graph.execute_analysis_code", side_effect=mock_execute_analysis_code), \
         patch.object(AgentGraph, "_run_visuals_and_report_in_parallel", new=timed_parallel):
         
        graph = AgentGraph(state)
        report = graph.run()
        
    logger.info(f"Parallel section duration: {parallel_duration[0]:.2f} seconds.")
    
    # Assertions to verify correctness
    assert "error" not in report, f"Graph execution failed: {report.get('error')}"
    
    # Check that viz coder and report writer ran concurrently
    # If they ran in parallel, the total duration for the parallel section should be around 2 seconds.
    # If they ran sequentially, it would take at least 4.0 seconds (2s sleep for visual + 2s sleep for report).
    logger.info(f"Parallel section time taken: {parallel_duration[0]:.2f}s (Expected < 3.0s for parallel, vs > 4.0s for sequential)")
    assert parallel_duration[0] < 3.0, f"Parallel execution took {parallel_duration[0]:.2f}s, which indicates sequential execution (expected < 3.0s)."
    
    # Check matching/stitching of charts to findings
    findings = report.get("keyFindings", [])
    assert len(findings) == 1, "Expected 1 key finding in report."
    finding = findings[0]
    assert finding.get("supporting_chart") == "peak_chart.png", f"Chart stitching failed! Got: {finding.get('supporting_chart')}"
    
    logger.info("SUCCESS: Viz Coder and Report Writer ran concurrently and charts were stitched correctly!")

if __name__ == "__main__":
    test_parallel_execution()
