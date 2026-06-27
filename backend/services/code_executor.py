# backend/services/code_executor.py

import os
import sys
import ast
import json
import tempfile
import pickle
import subprocess
import shutil
import logging
import pandas as pd
from typing import Dict, Any, List, Optional

logger = logging.getLogger("genq_api.code_executor")

# Modules that the LLM code is allowed to import
WHITELISTED_MODULES = {
    "pandas", "numpy", "matplotlib", "seaborn", "scipy", "json", "math",
    "collections", "itertools", "os", "re", "datetime",
    "base64", "string", "io"
}


# Functions/names that are forbidden in the LLM code
FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "globals", "locals", "__import__",
    "importlib", "shutil", "subprocess", "getattr", "setattr", "delattr", "hasattr"
}

class SecurityError(Exception):
    pass

class ExecutionResult:
    """
    Result of running agent-generated code in the sandbox.

    agent_outputs is the primary way callers should consume results.
    Each entry is a dict:
      {
        "filename": str,          # original filename in sandbox
        "type": str,              # declared type: "analysis_results"|"image"|"data"|"other"
        "purpose": str,           # human description of what the file contains
        "data": bytes | dict,     # raw bytes for images/data; parsed dict for JSON files
        "finding_title": str,     # (images only) finding this chart visualises
        "interpretation": str,    # (images only) paragraph explanation
        "insight_text": str,      # (images only) one-line callout
        "primary": bool,          # True if agent marked this as the primary analysis file
      }

    results_json and charts are kept for backward compatibility but are now derived
    from agent_outputs by the AgentGraph rather than being hardcoded file lookups.
    """
    def __init__(
        self,
        success: bool,
        stdout: str,
        stderr: str,
        results_json: Optional[Dict[str, Any]] = None,
        charts: Optional[List[Dict[str, Any]]] = None,
        agent_outputs: Optional[List[Dict[str, Any]]] = None,
        error_message: Optional[str] = None
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.results_json = results_json          # kept for compat
        self.charts = charts or []               # kept for compat
        self.agent_outputs = agent_outputs or [] # primary output
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "results_json": self.results_json,
            "charts": self.charts,
            "agent_outputs": [
                {k: v for k, v in o.items() if k != "data"}
                for o in self.agent_outputs
            ],
            "error_message": self.error_message
        }


def check_ast_safety(code: str) -> None:
    """
    Parses code using AST and throws SecurityError if unsafe constructs are found:
    - Imports outside the whitelisted packages
    - Calls to eval(), exec(), compile(), etc.
    - Access to dangerous os/sys attributes via any alias
    - File operations that try to traverse directories or use absolute paths.
    """
    try:
        root = ast.parse(code)
    except SyntaxError as e:
        raise SecurityError(f"Syntax error in generated code: {e}")

    # BUG-10 fix: collect all local names that are bound to dangerous modules
    # so alias tricks like `import os as operating_system` are still caught.
    os_aliases: set[str] = {"os"}
    sys_aliases: set[str] = {"sys"}

    # First pass: gather aliases
    for node in ast.walk(root):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split('.')[0]
                bound_name = alias.asname if alias.asname else alias.name
                if root_module == "os":
                    os_aliases.add(bound_name)
                elif root_module == "sys":
                    sys_aliases.add(bound_name)

    # Second pass: full security check
    for node in ast.walk(root):
        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split('.')[0]
                if root_module not in WHITELISTED_MODULES:
                    raise SecurityError(f"Import of module '{alias.name}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_module = node.module.split('.')[0]
                if root_module not in WHITELISTED_MODULES:
                    raise SecurityError(f"Import from module '{node.module}' is not allowed.")
                # Extra check: do not allow 'from os import ...' to prevent importing system/environ directly
                if root_module == "os":
                    raise SecurityError("Importing directly from 'os' module attributes is forbidden. Use 'import os' and access 'os.path' instead.")

        # Check for forbidden builtin/function calls and attribute access
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_CALLS:
                    raise SecurityError(f"Calling function '{node.func.id}' is forbidden.")
            elif isinstance(node.func, ast.Attribute):
                # e.g., os.system, subprocess.run — check against ALL known aliases
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id in os_aliases and node.func.attr != "path":
                        raise SecurityError(f"Accessing '{node.func.value.id}.{node.func.attr}' is forbidden. Only 'os.path' is allowed.")
                    if node.func.value.id in sys_aliases and node.func.attr in {"exit", "settrace", "setprofile"}:
                        raise SecurityError(f"Calling {node.func.value.id}.{node.func.attr}() is forbidden.")
        
        # Check non-call attribute accesses (e.g. os.environ) — also via aliases
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                if node.value.id in os_aliases and node.attr != "path":
                    raise SecurityError(f"Accessing '{node.value.id}.{node.attr}' is forbidden. Only 'os.path' is allowed.")

        # Check file path literals in open() to ensure they don't access external directories
        # Only simple checks for path traversal.
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            is_path_traversal = "../" in val or "..\\" in val or val == ".."
            
            # Windows drive path or unix absolute path
            is_drive_path = len(val) > 1 and val[1] == ":" and val[0].isalpha()
            
            is_unix_abs = False
            if val.startswith("/"):
                # A valid Unix path should not contain spaces, brackets, or punctuation
                if not any(c in val for c in " ()[]{}|*+?^$\\"):
                    is_unix_abs = True
            
            # Windows UNC path: starts with \\ and has host and share parts without regex characters.
            is_unc = False
            if val.startswith("\\\\"):
                parts = val.replace("/", "\\").split("\\")
                if len(parts) >= 4 and parts[2] and parts[3]:
                    host_and_share = parts[2] + parts[3]
                    if not any(c in host_and_share for c in "[]()*+?{}|$^"):
                        is_unc = True
            
            if is_path_traversal or is_drive_path or is_unix_abs or is_unc:
                raise SecurityError(f"Potentially unsafe path literal detected: '{val}'")



def execute_analysis_code(
    code: str,
    df: pd.DataFrame,
    timeout_seconds: int = 60
) -> ExecutionResult:
    """
    Executes Python code generated by the LLM in a temporary sandbox.
    1. Validates code safety using AST.
    2. Writes the dataframe to input_df.pkl inside a temp directory.
    3. Prepends DataFrame load code.
    4. Runs code in a subprocess with resource limits.
    5. Collects results (results.json, charts, logs) and returns them.
    """
    # Auto-correct seaborn bar_label hallucination safely
    code = code.replace("ax.bar_label(ax.patches", "ax.bar_label(ax.containers[0]")
    try:
        check_ast_safety(code)
    except SecurityError as se:
        logger.warning(f"Security validation failed: {se}")
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_message=f"Security Validation Error: {se}"
        )

    # Create temporary directory for sandboxing
    sandbox_dir = tempfile.mkdtemp(prefix="genq_sandbox_")
    
    # Save input dataframe to the temp directory
    df_path = os.path.join(sandbox_dir, "input_df.pkl")
    try:
        with open(df_path, "wb") as f:
            pickle.dump(df, f)
    except Exception as e:
        shutil.rmtree(sandbox_dir)
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_message=f"Failed to prepare input DataFrame: {e}"
        )

    # Build the full script content
    full_script_content = f"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import json
import pickle
import os

# --- RUNTIME SECURITY ISOLATION ---
import socket
def _blocked_socket(*args, **kwargs):
    raise RuntimeError("Network access is disabled in the sandbox.")
socket.socket = _blocked_socket
socket.create_connection = _blocked_socket

# Strip dangerous execution functions from os module
_dangerous_os_funcs = {
    'system', 'popen', 'kill', 'killpg', 'startfile',
    'fork', 'forkpty', 'plock',
    'spawnl', 'spawnle', 'spawnlp', 'spawnlpe', 'spawnv', 'spawnve', 'spawnvp', 'spawnvpe',
    'execl', 'execle', 'execlp', 'execlpe', 'execv', 'execve', 'execvp', 'execvpe'
}
for _f in _dangerous_os_funcs:
    if hasattr(os, _f):
        try:
            delattr(os, _f)
        except Exception:
            pass
# ----------------------------------

# Set matplotlib backend to Agg to avoid UI popup errors in background thread
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['figure.facecolor'] = 'white'
matplotlib.rcParams['axes.facecolor'] = 'white'
matplotlib.rcParams['savefig.facecolor'] = 'white'

# Load the DataFrame
with open("input_df.pkl", "rb") as f:
    df = pickle.load(f)

# --- LLM GENERATED CODE ---
{code}
# --- END LLM GENERATED CODE ---
"""

    script_path = os.path.join(sandbox_dir, "sandbox_run.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(full_script_content)

    # Use the current python executable (venv Python) to run the script
    python_exe = sys.executable

    try:
        # Run script in subprocess
        # Working directory is sandbox_dir so any relative file paths are local to sandbox
        proc = subprocess.run(
            [python_exe, "sandbox_run.py"],
            cwd=sandbox_dir,
            capture_output=True,
            text=True,
            timeout=timeout_seconds
        )
        
        stdout_content = proc.stdout
        stderr_content = proc.stderr
        success = (proc.returncode == 0)
        
        agent_outputs: List[Dict[str, Any]] = []
        results_json = None   # backward-compat: set from primary analysis_results output
        chart_data_list = []  # backward-compat: set from image outputs
        error_msg = None

        if not success:
            error_msg = f"Execution failed with exit code {proc.returncode}.\nStderr: {stderr_content}"
        else:
            manifest_path = os.path.join(sandbox_dir, "manifest.json")

            if os.path.exists(manifest_path):
                # ── Manifest-based discovery (agent declared its own outputs) ──
                try:
                    with open(manifest_path, "r", encoding="utf-8") as mf:
                        manifest = json.load(mf)
                except Exception as me:
                    logger.warning(f"Failed to parse manifest.json: {me}. Falling back to file scan.")
                    manifest = {"outputs": []}

                # Log any files the agent declared for deletion
                for deleted in manifest.get("deleted_files", []):
                    logger.info(f"Agent declared deletion of: {deleted} (sandbox will be wiped; no action taken)")

                for entry in manifest.get("outputs", []):
                    fname = entry.get("filename", "")
                    ftype = entry.get("type", "other")
                    fpath = os.path.join(sandbox_dir, fname)

                    if not os.path.exists(fpath):
                        logger.warning(f"Manifest declared '{fname}' but file not found in sandbox.")
                        continue

                    try:
                        if ftype == "image" or fname.lower().endswith(".png"):
                            with open(fpath, "rb") as f:
                                raw = f.read()
                            output_entry = {
                                "filename": fname,
                                "type": "image",
                                "purpose": entry.get("purpose", ""),
                                "finding_title": entry.get("finding_title", ""),
                                "interpretation": entry.get("interpretation", ""),
                                "insight_text": entry.get("insight_text", ""),
                                "primary": entry.get("primary", False),
                                "data": raw,
                            }
                            chart_data_list.append({"name": fname, "data": raw})  # compat
                        elif ftype in ("analysis_results", "json", "other") or fname.lower().endswith(".json"):
                            with open(fpath, "r", encoding="utf-8") as f:
                                parsed = json.load(f)
                            output_entry = {
                                "filename": fname,
                                "type": ftype if ftype != "other" else "json",
                                "purpose": entry.get("purpose", ""),
                                "primary": entry.get("primary", False),
                                "data": parsed,
                            }
                            if ftype == "analysis_results" and (results_json is None or entry.get("primary")):
                                results_json = parsed  # compat
                        else:
                            # data files (CSV, etc.) — store as raw bytes
                            with open(fpath, "rb") as f:
                                raw = f.read()
                            output_entry = {
                                "filename": fname,
                                "type": ftype,
                                "purpose": entry.get("purpose", ""),
                                "primary": entry.get("primary", False),
                                "data": raw,
                            }
                        agent_outputs.append(output_entry)
                    except Exception as fe:
                        logger.warning(f"Failed to load declared file '{fname}': {fe}")

            else:
                # ── Fallback: no manifest — scan sandbox for known file types ──
                logger.info("No manifest.json found. Falling back to legacy file scan.")

                for legacy_name in ("results.json", "viz_results.json"):
                    legacy_path = os.path.join(sandbox_dir, legacy_name)
                    if os.path.exists(legacy_path):
                        try:
                            with open(legacy_path, "r", encoding="utf-8") as f:
                                parsed = json.load(f)
                            results_json = parsed
                            agent_outputs.append({
                                "filename": legacy_name,
                                "type": "analysis_results",
                                "purpose": "Legacy output (no manifest)",
                                "primary": True,
                                "data": parsed,
                            })
                        except Exception as je:
                            logger.warning(f"Failed to parse legacy {legacy_name}: {je}")

                for file in os.listdir(sandbox_dir):
                    if file.lower().endswith(".png"):
                        fpath = os.path.join(sandbox_dir, file)
                        try:
                            with open(fpath, "rb") as f:
                                raw = f.read()
                            chart_data_list.append({"name": file, "data": raw})
                            agent_outputs.append({
                                "filename": file,
                                "type": "image",
                                "purpose": "Chart (no manifest)",
                                "primary": False,
                                "data": raw,
                            })
                        except Exception as ce:
                            logger.warning(f"Failed to read fallback chart {file}: {ce}")

        return ExecutionResult(
            success=success,
            stdout=stdout_content,
            stderr=stderr_content,
            results_json=results_json,
            charts=chart_data_list,
            agent_outputs=agent_outputs,
            error_message=error_msg
        )

    except subprocess.TimeoutExpired as te:
        return ExecutionResult(
            success=False,
            stdout=te.stdout or "",
            stderr=te.stderr or "",
            error_message=f"Execution timed out after {timeout_seconds} seconds."
        )
    except Exception as e:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            error_message=f"Internal executor error: {e}"
        )
    finally:
        # Cleanup the temp sandbox directory
        try:
            shutil.rmtree(sandbox_dir)
        except Exception as e:
            logger.warning(f"Failed to cleanup sandbox dir {sandbox_dir}: {e}")




