import sys
sys.path.append(r"c:\Users\Nisarg Patel\Documents\genq-analytics\backend")

from services.agent_prompts import DATA_SCIENTIST_PROMPT

def test_open_ended_prompt():
    # Try formatting
    formatted = DATA_SCIENTIST_PROMPT.format(
        domain="E-Commerce",
        purpose="Analyze sales cohort retention",
        dataset_type="transactional",
        important_columns="['date', 'customer_id', 'amount']",
        schema="date: datetime64, customer_id: int64, amount: float64",
        sample_rows="[ {'date': '2026-01-01', 'customer_id': 1, 'amount': 100} ]",
        missing_values="{'date': 0, 'customer_id': 0, 'amount': 0}",
        numeric_summary="{}",
        grouped_summary="{}",
        feedback=""
    )
    
    # Assert placeholders formatted correctly
    assert "E-Commerce" in formatted
    assert "Analyze sales cohort retention" in formatted
    
    # Assert open-ended description exists
    assert "Your goal is to investigate the dataset" in formatted
    assert "dynamically decide your analytical approach" in formatted
    
    # Assert prescriptive limits are absent
    assert "minimum 4" not in formatted, "Prescriptive minimum findings limit was not removed"
    assert "maximum 8" not in formatted, "Prescriptive maximum findings limit was not removed"
    assert "Phase 1" not in formatted, "Prescriptive Phase 1 was found in prompt"
    assert "Phase 2" not in formatted, "Prescriptive Phase 2 was found in prompt"
    
    print("DATA_SCIENTIST_PROMPT Verification:")
    print("-" * 40)
    print(formatted[:500] + "\n...")
    print("-" * 40)
    print("\nALL OPEN-ENDED PROMPT VERIFICATIONS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_open_ended_prompt()
