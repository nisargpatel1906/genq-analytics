import sys
import os

sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

def test_notebook_mode_removal():
    # 1. Verify DATA_SCIENTIST_NOTEBOOK_PROMPT does not exist in agent_prompts
    try:
        from services.agent_prompts import DATA_SCIENTIST_NOTEBOOK_PROMPT
        assert False, "DATA_SCIENTIST_NOTEBOOK_PROMPT should be removed!"
    except ImportError:
        print("--> Verification: DATA_SCIENTIST_NOTEBOOK_PROMPT has been successfully removed.")

    # 2. Verify execute_notebook_code does not exist in code_executor
    try:
        from services.code_executor import execute_notebook_code
        assert False, "execute_notebook_code should be removed!"
    except ImportError:
        print("--> Verification: execute_notebook_code has been successfully removed.")

    # 3. Verify use_notebook_mode is not defined in agent_graph
    from services.agent_graph import AnalysisState
    import inspect
    init_sig = inspect.signature(AnalysisState.__init__)
    assert "use_notebook_mode" not in init_sig.parameters, "AnalysisState __init__ should not accept use_notebook_mode!"
    print("--> Verification: AnalysisState does not accept use_notebook_mode parameter anymore.")

    # 4. Verify we can still run code_executor safely
    from services.code_executor import check_ast_safety
    check_ast_safety("print('Hello World')")
    print("--> Verification: check_ast_safety remains working.")

    print("\nALL NOTEBOOK MODE REMOVAL VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_notebook_mode_removal()
