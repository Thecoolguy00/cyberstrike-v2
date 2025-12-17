# playwright_agent_runner.py
import json, time, os, logging
from playwright.sync_api import sync_playwright
from hdl_extractor import extract_hybrid_dsl_from_page
from hdl_executor import HDLExecutor
from gemini_client import GeminiClient, Flags
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Runner")
FINDINGS = Path("findings")
FINDINGS.mkdir(exist_ok=True)

def run_session(url: str, goal: str, headless: bool = True, max_steps: int = 8):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        logger.info("Navigating to %s", url)
        page.goto(url, wait_until="load", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        # initial DSL (full)
        page_hdl = extract_hybrid_dsl_from_page(page, url, max_elements=120)
        dsl = page_hdl.model_dump()
        client = GeminiClient()
        execer = HDLExecutor(page)

        flags = Flags()
        for step in range(1, max_steps+1):
            logger.info("=== STEP %d ===", step)
            # GeminiClient.ask will enforce EID usage (see gemini_client.py)
            plan = client.ask(goal, dsl, flags)
            logger.info("Plan: %s", json.dumps(plan.model_dump(), indent=2))

            # Execute actions in order
            for action in plan.actions:
                action_data = action.model_dump()
                logger.info("Executing action: %s", action_data)
                sel = action.selector
                if not sel:
                    logger.warning("Action missing selector (eid or css). Skipping.")
                    continue

                if action.type == "click":
                    res = execer.click_element(dsl, sel)
                    logger.info("click result: %s", res)
                elif action.type == "type":
                    if action.text is None:
                        logger.warning("type action missing text; skipping.")
                        continue
                    res = execer.fill_input(dsl, sel, action.text)
                    logger.info("type result: %s", res)
                elif action.type == "goto":
                    page.goto(action.url, wait_until="load")
                elif action.type == "wait":
                    time.sleep((action.timeout or 1000)/1000.0)
                elif action.type == "screenshot":
                    path = FINDINGS / (action.path or f"step_{step}.png")
                    page.screenshot(path=str(path))
                    logger.info("Saved screenshot %s", path)
                else:
                    logger.warning("Unhandled action type: %s", action.type)

                # regenerate DSL after mutation to keep model in sync
                page_hdl = extract_hybrid_dsl_from_page(page, url, max_elements=120)
                dsl = page_hdl.model_dump()

            if plan.flags.stop:
                logger.info("Plan requested stop: %s", plan.flags.status)
                break

        browser.close()
        return {"final_dsl": dsl}

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--goal", required=True)
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()
    run_session(args.url, args.goal, headless=args.headless)
