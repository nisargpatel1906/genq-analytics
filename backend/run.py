import sys
import os
import subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <path_to_script.py>")
        print("Example: python run.py scratch/test_agent_graph.py")
        sys.exit(1)

    script_path = sys.argv[1]
    
    if not os.path.exists(script_path):
        print(f"Error: Script '{script_path}' not found.")
        sys.exit(1)

    env = os.environ.copy()
    
    # Add the current directory (backend/) to PYTHONPATH 
    # to prevent ModuleNotFoundError when importing app or services.
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = f"{backend_dir}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = backend_dir

    print(f"--- Executing {script_path} ---")
    result = subprocess.run([sys.executable, script_path] + sys.argv[2:], env=env)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
