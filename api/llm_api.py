# llm_api.py
import google.generativeai as genai
import os
import json
import logging
from typing import Optional, List

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
MODEL_NAME = 'gemini-2.5-flash'
# Prompt Files
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# Go up one level to PSYCHOLOGY_RDR, then into data/prompts
PROMPTS_DIR = os.path.join(CURRENT_DIR, '..','prompts')

# Define full paths for prompt files
CHECK_PROMPT_FILE = os.path.join(PROMPTS_DIR, 'prompt_condition.txt')
DIFF_PROMPT_FILE = os.path.join(PROMPTS_DIR, 'prompt_differentiate.txt')
SUMMARY_PROMPT_FILE = os.path.join(PROMPTS_DIR, 'prompt_summary.txt')
MERGE_PROMPT_FILE = os.path.join(PROMPTS_DIR, 'prompt_merge.txt')


class LLMError(RuntimeError):
    """The oracle could not be asked, or its answer could not be read.

    Gap 9. Previously a timeout, a rate-limit, a quota error or an unparseable
    reply all came back as `False` / `[]`, which is exactly what the model says
    when it genuinely disagrees or finds nothing. The traversal then took the
    left branch on what was really an outage, and any rule saved during that
    walk was attached against a path the tree would never otherwise have taken.

    Raising instead means a failed call can never be mistaken for an answer.
    Every caller either surfaces it to the clinician or logs it; nothing
    silently proceeds on a guess.
    """

    def __init__(self, operation: str, detail: str):
        self.operation = operation
        self.detail = detail
        super().__init__(f"{operation} failed: {detail}")


# --- Setup ---
try:
    api_key = os.environ["API_KEY"]
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)
except Exception as e:
    raise EnvironmentError(f"Setup failed: {e}")

# --- Load Prompts ---
def load_prompt(filename):
    try:
        with open(filename, "r") as f:
            return f.read()
    except Exception as e:
        logging.error(f"Error loading {filename}: {e}")
        return ""

CHECK_TEMPLATE = load_prompt(CHECK_PROMPT_FILE)
DIFF_TEMPLATE = load_prompt(DIFF_PROMPT_FILE)
SUMMARY_TEMPLATE = load_prompt(SUMMARY_PROMPT_FILE)
MERGE_TEMPLATE = load_prompt(MERGE_PROMPT_FILE)

# --- Core Functions ---

def llm_generate_summary(transcript_text: str) -> str:
    """
    Reads raw docx transcript and generates a Clinical Prototype Summary.
    """
    try:
        prompt = SUMMARY_TEMPLATE.format(transcript_content=transcript_text)
        #need to finetune these values
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 1.0, "top_p": 1.0} 
        )
        return response.text.strip()
    except Exception as e:
        logging.error(f"Summary generation failed: {e}")
        return ""

def llm_check_condition(summary_text: str, condition_string: str) -> bool:
    """
    Checks if a SUMMARY satisfies ONE condition.

    This is the paper's `lambda.Evaluate(x, c_i)`: one condition in, one
    TRUE/FALSE out. Algorithm 3 calls it once per conjunct, so the caller is
    responsible for the AND -- see RDREngine.evaluate_rule.

    Raises LLMError if the call itself fails (Gap 9). A returned False now
    always means the model said FALSE.
    """
    prompt = CHECK_TEMPLATE.format(
        summary_content=summary_text, 
        condition_string=condition_string
    )
    try: #temperature and top p being modified
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 1.0, "top_p": 1.0} 
        )
        text = response.text.strip().upper()
    except Exception as e:
        # Gap 9: an outage is not a FALSE. Say so, rather than branching on it.
        raise LLMError("condition check", f"{type(e).__name__}: {e}") from e

    logging.info(f"LLM Check: '{condition_string}' -> {text}")
    return 'TRUE' in text

def llm_merge_summaries(old_summary: str, new_summary: str) -> str:
    """
    Merges a new patient profile into an existing consolidated group profile.
    """
    prompt = MERGE_TEMPLATE.format(
        old_summary=old_summary,
        new_summary=new_summary
    )
    try: # need to finetune these values
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 1.0, "top_p": 1.0} 
        )
        return response.text.strip()
    except Exception as e:
        logging.error(f"Merge failed: {e}")
        return old_summary # Fallback: keep old summary

def llm_get_differentiating_conditions(new_summary: str, ref_summary: str) -> List[str]:
    """
    Compares NEW summary vs REFERENCE summary to find differences.

    These are *candidates* only. Algorithm 5 then verifies each one against the
    new case and against every stored case before it may be offered to the
    clinician -- see RDREngine.find_differences.

    Raises LLMError if the call fails or the reply is not a JSON list of
    strings (Gap 9), so an unreadable answer can no longer pass as "no
    differences found".
    """
    prompt = DIFF_TEMPLATE.format(
        summary_new=new_summary,
        summary_ref=ref_summary if ref_summary else "None"
    )
    
    try: #top p temperature added
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 1.0, 
                "top_p": 1.0,
            }
        )
        text = response.text.strip()
    except Exception as e:
        raise LLMError("difference extraction", f"{type(e).__name__}: {e}") from e

    # Clean markdown code blocks if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0]

    try:
        parsed = json.loads(text)
    except Exception as e:
        # An unparseable reply is an error, not an empty result.
        raise LLMError("difference extraction", f"reply was not JSON: {text[:200]}") from e

    if not isinstance(parsed, list):
        raise LLMError("difference extraction", f"reply was not a JSON list: {text[:200]}")

    return [str(c).strip() for c in parsed if str(c).strip()]
