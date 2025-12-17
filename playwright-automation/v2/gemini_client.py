# gemini_client.py
from google import genai
from google.genai import types
import os, json
from pydantic import BaseModel
from typing import List, Optional
from dotenv import load_dotenv
load_dotenv()

# re-use Action/Flags/Plan if defined elsewhere, otherwise define minimal copies
class Action(BaseModel):
    type: str
    selector: Optional[str] = None  # this MUST be an EID (el_...)
    text: Optional[str] = None
    url: Optional[str] = None
    key: Optional[str] = None
    path: Optional[str] = None
    timeout: Optional[int] = 1000

class Flags(BaseModel):
    action_completed: bool = False
    tasks_done: int = 0
    total_tasks: int = 1
    stop: bool = False
    status: Optional[str] = None
    next_hint: Optional[str] = None

class Plan(BaseModel):
    actions: List[Action]
    flags: Flags

class GeminiClient:
    def __init__(self, model="gemini-2.5-flash", temp=0.15):
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY_2")
        if not api_key:
            raise RuntimeError("Set GEMINI_API_KEY in environment.")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.config = types.GenerateContentConfig(
            system_instruction="You are a careful DSL-driven Playwright planner. Output JSON matching Plan schema exactly.",
            response_mime_type="application/json",
            response_schema=Plan,
            temperature=temp,
            max_output_tokens=2048,
        )

    def _build_dsl_summary(self, dsl_obj: dict) -> str:
        """
        Return a concise mapping of EID -> (label, type) so the LLM is forced to use EIDs.
        """
        lines = []
        for el in dsl_obj.get("elements", [])[:200]:
            eid = el.get("eid")
            label = el.get("label") or ""
            typ = el.get("type") or ""
            lines.append(f"- {eid} : {typ} : \"{label}\"")
        return "\n".join(lines)

    def ask(self, goal: str, dsl_obj: dict, flags: Flags) -> Plan:
        # dsl_obj is the full DSL dict; we pass summary first, then full DSL
        dsl_summary = self._build_dsl_summary(dsl_obj)
        dsl_json = json.dumps(dsl_obj, indent=2, ensure_ascii=False)

        # IMPORTANT: enforce EID usage strongly in prompt
        prompt = (
            "CONTEXT: Your only job is to produce a sequence of actions (Plan) that operate on the page using the Hybrid DSL.\n\n"
            "HARD RULES (obey exactly):\n"
            "1) You MUST reference page elements ONLY by their EID values (like 'el_input_3_ab12cd34').\n"
            "2) The 'selector' field in every action MUST be exactly the EID, not a CSS or xpath. If you output any CSS, xpath or class selectors, it will be ignored by the executor.\n"
            "3) The executor handles mapping EIDs -> actual selectors. Do not try to guess how to click; pick the correct EID for the element you want.\n"
            "4) Allowed action types: click, type, goto, wait, keyboard, screenshot.\n"
            "5) Output STRICT JSON only and conform to the Plan schema.\n\n"
            f"Reference file (context): /mnt/data/Cyberstrike v2.pdf\n\n"
            "DSL SUMMARY (use EIDs below):\n"
            f"{dsl_summary}\n\n"
            "FULL DSL (for completeness, do NOT reference selectors directly - use EIDs):\n"
            f"{dsl_json}\n\n"
            f"Current goal: {goal}\n"
            f"Current progress flags: {flags.model_dump_json()}\n\n"
            "Return only the JSON Plan (actions and flags)."
        )

        resp = self.client.models.generate_content(model=self.model, contents=prompt, config=self.config)
        try:
            return resp.parsed
        except Exception:
            return Plan.model_validate(json.loads(resp.text))
