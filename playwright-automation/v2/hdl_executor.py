# hdl_executor.py
from playwright.sync_api import Page
import time, logging
from typing import Optional, Dict, Any

logger = logging.getLogger("HDLExecutor")
logger.setLevel(logging.INFO)

class HDLExecutor:
    def __init__(self, page: Page, max_retries: int = 2, retry_delay: float = 0.8):
        self.page = page
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _find_element_by_eid(self, dsl: Dict[str, Any], eid: str) -> Optional[Dict[str, Any]]:
        for el in dsl.get("elements", []):
            if el.get("eid") == eid:
                return el
        return None

    # ... (re-use the helper methods from your previous file: _try_click_by_query_all, _try_click_by_text, _try_click_by_xpath, _try_js_click, _click_by_bbox) ...
    # For brevity, assume they are implemented exactly as before. Paste your previous helper implementations here.

    # shorthand wrappers omitted in this snippet; include them from your previous hdl_executor implementation.

    def click_element(self, dsl: Dict[str, Any], selector: str) -> Dict[str,Any]:
        """
        selector: expected to be EID like 'el_...' OR a CSS selector string (legacy).
        Prefer EID. If CSS is provided, try CSS fallback path.
        """
        # EID path
        if selector and selector.startswith("el_"):
            el = self._find_element_by_eid(dsl, selector)
            if not el:
                return {"ok": False, "error": "eid not found"}
            sel = el.get("selector", {})
            # order: css -> css_alt -> text -> aria -> xpath -> js click -> bbox
            order = []
            if sel.get("css"): order.append(("css", sel.get("css")))
            if sel.get("css_alt"): order.append(("css", sel.get("css_alt")))
            if sel.get("text_selector"): order.append(("text", sel.get("text_selector")))
            if sel.get("aria"): order.append(("aria", sel.get("aria")))
            if sel.get("xpath"): order.append(("xpath", sel.get("xpath")))

            for typ, s in order:
                ok = False
                for r in range(self.max_retries+1):
                    if typ == "css":
                        ok = self._try_click_by_query_all(s)
                    elif typ == "text":
                        ok = self._try_click_by_text(s)
                    elif typ == "aria":
                        ok = self._try_click_by_query_all(s)
                    elif typ == "xpath":
                        ok = self._try_click_by_xpath(s)
                    if ok:
                        return {"ok": True, "method": typ, "selector": s}
                    time.sleep(self.retry_delay)

            # fallback JS click by initial css
            if sel.get("css"):
                if self._try_js_click(sel.get("css")):
                    return {"ok": True, "method": "js", "selector": sel.get("css")}

            # bounding box click
            if el.get("bounds"):
                if self._click_by_bbox(el["bounds"]):
                    return {"ok": True, "method": "bbox", "bounds": el["bounds"]}

            return {"ok": False, "error": "all attempts failed"}
        else:
            # treat selector as CSS fallback (legacy)
            logger.debug("selector not an eid; trying CSS fallback: %s", selector)
            # try query_all first (handles multiple)
            if self._try_click_by_query_all(selector):
                return {"ok": True, "method": "css", "selector": selector}
            # try text
            if selector.startswith("text="):
                if self._try_click_by_text(selector):
                    return {"ok": True, "method": "text", "selector": selector}
            # try JS click
            if self._try_js_click(selector):
                return {"ok": True, "method": "js", "selector": selector}
            return {"ok": False, "error": "css fallback failed"}

    def fill_input(self, dsl: Dict[str, Any], selector: str, text: str) -> Dict[str,Any]:
        # EID path
        if selector and selector.startswith("el_"):
            el = self._find_element_by_eid(dsl, selector)
            if not el:
                return {"ok": False, "error": "eid not found"}
            sel = el.get("selector", {})
            # try css then xpath then js
            if sel.get("css"):
                try:
                    self.page.fill(sel.get("css"), text, timeout=4000)
                    return {"ok": True, "method":"css", "selector": sel.get("css")}
                except Exception as e:
                    logger.debug("fill css failed: %s", e)
            if sel.get("xpath"):
                try:
                    elq = self.page.query_selector(f'xpath={sel.get("xpath")}')
                    if elq:
                        elq.fill(text, timeout=4000)
                        return {"ok": True, "method":"xpath", "selector": sel.get("xpath")}
                except Exception as e:
                    logger.debug("fill xpath failed: %s", e)
            # fallback: JS set value
            try:
                self.page.evaluate("(eid,txt) => { const el = [...document.querySelectorAll('input, textarea, select')].find(e=> e.dataset && e.dataset.eid===eid || e.id===eid || e.name===eid || e.placeholder===eid); if(el){ el.focus(); el.value = txt; el.dispatchEvent(new Event('input',{bubbles:true})); } }", selector, text)
                return {"ok": True, "method":"js", "selector": selector}
            except Exception as e:
                logger.debug("fill js fallback failed: %s", e)
                return {"ok": False, "error":"all fills failed"}
        else:
            # CSS fallback
            try:
                self.page.fill(selector, text, timeout=4000)
                return {"ok": True, "method":"css", "selector": selector}
            except Exception as e:
                logger.debug("css fill fallback failed: %s", e)
                return {"ok": False, "error": "css fill failed"}
