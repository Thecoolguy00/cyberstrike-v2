# hdl_extractor.py
from playwright.sync_api import Page, sync_playwright
from bs4 import BeautifulSoup
import hashlib, json, re, time
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
import html
import math

# Pydantic models for structured DSL
class SelectorSet(BaseModel):
    css: Optional[str] = None
    css_alt: Optional[str] = None
    xpath: Optional[str] = None
    aria: Optional[str] = None
    text_selector: Optional[str] = None

class ElementHDL(BaseModel):
    eid: str
    type: str
    label: Optional[str] = None
    text: Optional[str] = None
    placeholder: Optional[str] = None
    selector: SelectorSet
    bounds: Optional[Dict[str, int]] = None
    visible: bool = True
    actionable: bool = False
    hierarchy: Optional[List[str]] = None
    confidence: float = 0.8
    keywords: Optional[List[str]] = None
    nearby_text: Optional[str] = None

class PageHDL(BaseModel):
    page_url: str
    timestamp: float
    elements: List[ElementHDL]


# Helpers
def _norm_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s2 = " ".join(s.split())
    return s2.strip() if s2.strip() else None

def _shorten_classes(cls_list):
    return ".".join(cls_list[:3]) if cls_list else None

def _safe_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf8")).hexdigest()[:8]

def _make_eid(tag_name: str, index: int, base: str) -> str:
    return f"el_{tag_name}_{index}_{_safe_hash(base)}"

def _text_keywords(s: Optional[str]):
    if not s: return []
    s = s.lower()
    kws = []
    for k in ["login","signin","search","submit","next","continue","register","signup","email","password","user","profile","dashboard","admin","menu","settings","download","upload","confirm","apply","order"]:
        if k in s:
            kws.append(k)
    return kws

# XPath builder via JS path
JS_XPATH = """
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  function xpathForElement(element) {
    if (element.id) return '//*[@id="'+element.id+'"]';
    const parts = [];
    for (; element && element.nodeType == 1; element = element.parentNode) {
      let nb = 0;
      let sib;
      for (sib = element.previousSibling; sib; sib = sib.previousSibling) {
        if (sib.nodeType == 1 && sib.nodeName == element.nodeName) nb++;
      }
      const idx = nb ? '[' + (nb+1) + ']' : '';
      parts.splice(0, 0, element.nodeName.toLowerCase() + idx);
    }
    return '/' + parts.join('/');
  }
  return xpathForElement(el);
}
"""

# Main DSL extractor
def extract_hybrid_dsl_from_page(page: Page, url: str, max_elements: int = 100) -> PageHDL:
    ts = time.time()
    # get list of visible element info from page - use boundingClientRect and ARIA/role
    elements_info = page.evaluate("""() => {
        const els = [...document.querySelectorAll('input, textarea, select, button, a, [role="button"], [role="link"]')];
        return els.map((el,i) => {
            const rect = el.getBoundingClientRect();
            return {
                index: i,
                tag: el.tagName.toLowerCase(),
                id: el.id || null,
                name: el.getAttribute && el.getAttribute('name'),
                classes: el.className ? el.className.split(/\\s+/).filter(Boolean) : [],
                text: (el.innerText || el.textContent || '').trim(),
                placeholder: el.getAttribute && el.getAttribute('placeholder'),
                aria: el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('role') || el.getAttribute('aria-labelledby')),
                x: Math.round(rect.x || 0), y: Math.round(rect.y || 0), w: Math.round(rect.width || 0), h: Math.round(rect.height || 0),
                visible: !!(rect.width && rect.height && (rect.bottom>0 || rect.top>0)),
                dataset: el.dataset || {},
                tabindex: el.getAttribute && el.getAttribute('tabindex'),
            }
        });
    }""")

    # gather outerHTML for labeling via BS
    html_snippets = []
    for info in elements_info:
        # fallback outerHTML slice
        try:
            outer = page.evaluate("(i) => document.querySelectorAll('input, textarea, select, button, a, [role=\"button\"], [role=\"link\"]')[i].outerHTML", info["index"])
        except Exception:
            outer = ""
        html_snippets.append(outer)

    # Build entries
    hdls = []
    for i, info in enumerate(elements_info):
        # basic label heuristics
        label = info.get("aria") or info.get("placeholder") or (info.get("text")[:80] if info.get("text") else None) or info.get("name") or info.get("id")
        label = _norm_text(label) or (info.get("tag"))
        # selectors
        css = None
        if info.get("id"):
            css = f"#{info['id']}"
        elif info.get("name"):
            css = f"[name='{info['name']}']"
        else:
            cl = _shorten_classes(info.get("classes"))
            css = f"{info['tag']}.{cl}" if cl else info['tag']

        css_alt = None
        if info.get("name") and info.get("id"):
            css_alt = f"{info['tag']}#{info['id']}, {info['tag']}[name='{info['name']}']"
        elif info.get("classes"):
            css_alt = f"{info['tag']}.{_shorten_classes(info.get('classes'))}, {info['tag']}"
        else:
            css_alt = info['tag']

        # text selector
        text_sel = None
        if info.get("text"):
            # create text= style selector for playwright
            text_candidate = info.get("text").strip()
            if len(text_candidate) < 100:
                text_sel = f"text={text_candidate}"

        # xpath via running JS (use css if exists)
        xpath = None
        try:
            # try with css if resolvable, else pass built selector
            test_sel = css if css else info.get("tag")
            xpath = page.evaluate(JS_XPATH, test_sel)
        except Exception:
            xpath = None

        # bounding box
        bounds = {"x": info.get("x",0), "y": info.get("y",0), "w": info.get("w",0), "h": info.get("h",0)}

        eid = _make_eid(info.get("tag","el"), i, (info.get("id") or info.get("name") or info.get("text") or str(i)))

        elhdl = ElementHDL(
            eid=eid,
            type=("input" if info["tag"] in ("input","textarea","select") else ("button" if info["tag"] in ("button",) or info.get("aria") and "button" in str(info.get("aria")).lower() else ("link" if info["tag"]=="a" or (info.get("aria") and "link" in str(info.get("aria")).lower()) else info["tag"]))),
            label=label,
            text=_norm_text(info.get("text")),
            placeholder=_norm_text(info.get("placeholder")),
            selector=SelectorSet(css=css, css_alt=css_alt, xpath=xpath, aria=_norm_text(info.get("aria")), text_selector=text_sel),
            bounds=bounds,
            visible=bool(info.get("visible")),
            actionable=bool(info.get("visible") and (info.get("w",0)>2 and info.get("h",0)>2)),
            hierarchy=[f"index:{i}"],
            confidence=0.8,
            keywords=_text_keywords(" ".join(filter(None,[label, info.get("text") or ""]))),
            nearby_text=None
        )
        hdls.append(elhdl)

    # dedupe by label/type and prefer visible
    seen = {}
    out = []
    for el in hdls:
        key = ( (el.label or "").lower(), el.type )
        prev = seen.get(key)
        if prev:
            # prefer visible
            if prev.visible and not el.visible:
                continue
            if el.visible and not prev.visible:
                seen[key] = el
                continue
            # prefer larger
            if (prev.bounds and el.bounds) and ( (el.bounds['w']*el.bounds['h']) > (prev.bounds['w']*prev.bounds['h']) ):
                seen[key] = el
                continue
            else:
                continue
        seen[key] = el

    out = list(seen.values())
    # score sort - buttons/inputs first
    def score(e: ElementHDL):
        base = 0
        if e.type == "button": base += 100
        if e.type == "input": base += 90
        if any(k in (e.label or "").lower() for k in ["login","sign","search","submit","save","next","continue"]): base += 30
        base += int(e.visible)*10
        return base

    out.sort(key=score, reverse=True)
    out = out[:max_elements]

    phdl = PageHDL(page_url=url, timestamp=ts, elements=out)
    return phdl

# convenience runner
def fetch_and_extract(url: str, headless: bool = True, max_elements: int = 80) -> PageHDL:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, wait_until="load", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        dsl = extract_hybrid_dsl_from_page(page, url, max_elements=max_elements)
        browser.close()
    return dsl

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--max", type=int, default=50)
    args = ap.parse_args()
    p = fetch_and_extract(args.url, headless=args.headless, max_elements=args.max)
    print(json.dumps(p.model_dump(), indent=2, ensure_ascii=False))
