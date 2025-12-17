"""
Playwright + DSL Orchestrator (Gemini Integration)

Enhanced version: regenerates DSL after every action and passes it to Gemini.

Flow:
1. Load page.
2. Generate simplified DSL via `build_ui_dsl()` (instead of full DOM).
3. Feed DSL to Gemini -> get JSON plan of actions + flags.
4. Execute safely via Playwright.
5. After every action (click/goto/type/wait), regenerate DSL to reflect new UI state.
6. Continue until goal complete or stop flag.

Usage:
    python dsl_playwright_agent.py --url "https://example.com" --goal "search for cats"
"""


import argparse, json, os, sys, logging, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
from dsl_gen import build_ui_dsl
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from dotenv import load_dotenv

load_dotenv()

# ----------------- Logging -----------------
FINDINGS_DIR = Path("temp")
LOG_FILE = "dsl_agent.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("DSLPlaywrightAgent")

# ----------------- Schema -----------------
ActionType = Literal["goto", "click", "type", "wait", "keyboard", "screenshot"]

class Action(BaseModel):
    type: ActionType
    selector: Optional[str] = None
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

# ----------------- Gemini Config -----------------
SYSTEM_PROMPT = """
You are an expert automation agent that plans Playwright actions using the provided DSL.

Your goal: interpret the user's task and generate a JSON plan with `actions` and `flags`.

Rules:
- Output strictly JSON matching the schema.
- Only use selectors from the DSL.
- Supported action types: "goto", "click", "type", "wait", "keyboard", "screenshot".
- For screenshots, include: {"type": "screenshot", "path": "filename.png"}.
- Avoid guessing selectors not in the DSL.
- Use `type` to fill inputs, `click` for buttons/links.
- If finished or stuck, set flags.stop=true and include a helpful status.
- Inputs with placeholder values like "email", "username", or "password" should be used when typing login credentials.
"""

class GeminiClient:
    def __init__(self, model="gemini-2.5-flash", temp=0.2):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Set GEMINI_API_KEY in environment.")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=Plan,
            temperature=temp,
            max_output_tokens=2048,
        )

    def ask(self, goal: str, dsl_json: str, flags: Flags) -> Plan:
        prompt = (
            f"Goal: {goal}\n"
            f"Current progress: {flags.model_dump_json()}\n\n"
            "Current page DSL (use only these selectors):\n"
            "---------------- DSL START ----------------\n"
            f"{dsl_json}\n"
            "---------------- DSL END ----------------\n"
            "Return ONLY JSON with `actions` and `flags`."
        )
        logger.info("Prompt len: %d chars", len(prompt))
        resp = self.client.models.generate_content(
            model=self.model, contents=prompt, config=self.config)
        try:
            return resp.parsed
        except Exception:
            data = json.loads(resp.text)
            return Plan.model_validate(data)

# ----------------- Executor -----------------
class DSLExecutor:
    def __init__(self, page, llm: GeminiClient, max_steps=8):
        self.page = page
        self.llm = llm
        self.max_steps = max_steps
        self.dsl = None  # keep current DSL dict

    def regenerate_dsl(self, url: str):
        html = self.page.content()
        dsl = build_ui_dsl(html, url, max_elements=50)
        dsl_dict = dsl.model_dump()
        dsl_json = json.dumps(dsl_dict, indent=2, ensure_ascii=False)
        logger.info("DSL regenerated (%d chars).", len(dsl_json))
        print(dsl_dict) # only for debugging
        return dsl_dict  # return dict, not JSON string

    def run(self, goal, url):
        logger.info("[STEP 1] Generating DSL for %s", url)
        self.dsl = self.regenerate_dsl(url)
        dsl_json = json.dumps(self.dsl, indent=2, ensure_ascii=False)
        flags = Flags()

        for step in range(1, self.max_steps + 1):
            logger.info("== Step %d ==", step)
            try:
                plan = self.llm.ask(goal, dsl_json, flags)
            except Exception as e:
                logger.error("LLM error: %s", e)
                break

            logger.info("Received plan:\n%s", json.dumps(plan.model_dump(), indent=2))

            for action in plan.actions:
                try:
                    if action.type == "click":
                        logger.info("Clicking: %s", action.selector)
                        try:
                            # find visible elements
                            elements = self.page.query_selector_all(action.selector)
                            visible = [e for e in elements if e.is_visible()]
                            if visible:
                                visible[0].scroll_into_view_if_needed()
                                visible[0].click(timeout=5000)
                                logger.info("Clicked visible element for selector: %s", action.selector)
                            else:
                                raise Exception("No visible element found.")
                        except Exception as e:
                            logger.warning("Standard click failed: %s", e)
                            # fallback synthetic click
                            self.page.evaluate("""
                                (sel) => {
                                    const el = [...document.querySelectorAll(sel)].find(e => e.offsetParent !== null);
                                    if (el) el.click();
                                }
                            """, action.selector)
                            self.page.wait_for_timeout(2000)

                        self.page.wait_for_timeout(2000)

                    elif action.type == "type":
                        logger.info("Typing into %s: %s", action.selector, action.text)
                        self.page.fill(action.selector, action.text or "")

                    elif action.type == "goto":
                        logger.info("Navigating to: %s", action.url)
                        self.page.goto(action.url, wait_until="load")

                    elif action.type == "keyboard":
                        logger.info("Pressing key: %s", action.key)
                        self.page.keyboard.press(action.key or "Enter")

                    elif action.type == "wait":
                        logger.info("Waiting %d ms", action.timeout or 1000)
                        self.page.wait_for_timeout(action.timeout or 1000)

                    elif action.type == "screenshot":
                        FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
                        fname = action.path or f"step_{step}.png"
                        path = FINDINGS_DIR / fname
                        self.page.screenshot(path=str(path))
                        logger.info("Screenshot saved: %s", path)

                    # Always regenerate DSL after visible actions
                    if action.type in ["click", "goto", "wait", "type", "keyboard"]:
                        self.dsl = self.regenerate_dsl(url)
                        dsl_json = json.dumps(self.dsl, indent=2, ensure_ascii=False)

                except Exception as e:
                    logger.error("Action failed: %s", e)

            # --- Stop handling ---
            if plan.flags.stop:
                logger.info("Stopping: %s", plan.flags.status or "")

                new_dsl = self.regenerate_dsl(url)

                def extract_keys(dsl):
                    return set(
                        e.get("selector")
                        for e in dsl.get("elements", [])
                        if e.get("type") in ("input", "button", "select")
                    )

                old_keys = extract_keys(self.dsl)
                new_keys = extract_keys(new_dsl)

                status = (plan.flags.status or "").lower()
                asks_for_dsl = "provide the dsl" in status or "please provide" in status

                # --- force rerun if new input/button appeared ---
                ui_changed = bool(new_keys - old_keys)
                password_appeared = any(
                    "password" in (e.get("label", "").lower() + str(e.get("placeholder", "")).lower())
                    for e in new_dsl.get("elements", [])
                )

                if asks_for_dsl or ui_changed or password_appeared:
                    logger.info(
                        "New elements detected (Δ=%d). UI changed or password field appeared — re-running Gemini immediately.",
                        len(new_keys - old_keys),
                    )
                    self.dsl = new_dsl
                    dsl_json = json.dumps(self.dsl, indent=2, ensure_ascii=False)
                    flags.stop = False  # let loop continue
                    continue  # immediately rerun model with updated DSL
                else:
                    logger.info("No significant change. Exiting.")
                    break



        print(json.dumps(flags.model_dump(), indent=2))


# ----------------- Main -----------------
def main():
    parser = argparse.ArgumentParser(description="DSL + Playwright + Gemini automation")
    parser.add_argument("--url", required=True, help="Target page URL")
    parser.add_argument("--goal", required=True, help="User goal or task")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    args = parser.parse_args()

    llm = GeminiClient()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        logger.info("Navigating to %s", args.url)
        page.goto(args.url, wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        executor = DSLExecutor(page, llm)
        executor.run(args.goal, args.url)
        browser.close()

if __name__ == "__main__":
    main()
