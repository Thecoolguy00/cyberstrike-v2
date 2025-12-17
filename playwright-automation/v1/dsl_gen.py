"""
dsl_gen.py

goal/purpose:
    take a webpage url, extract key interactive UI elements, and generate a simple
    DSL(domain-specific language) represntation of the page.

usage:
    python dsl_gen.py --url "https://example.com"

output:
    JSON object to stdout describing inputs, buttons, and links.

example output:
{
  "url": "https://example.com",
  "elements": [
    {"label": "search bar", "selector": "#q", "type": "input", "placeholder": "Search"},
    {"label": "submit", "selector": "button.submit-btn", "type": "button", "text": "Submit"}
  ]
}

"""

import argparse
import json
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from typing import List, Optional
from pydantic import BaseModel, Field


#-------------------------DSL SCHEMA------------------------
#Each UIElement is a simplified representation of something the LLM can interact with.
class UIElement(BaseModel):
    label: str=Field(..., description="Readable label or role, eg: 'search bar' or 'login button'")
    selector: str=Field(...,description="CSS selector that can be used by Playwright")
    type: str=Field(..., description="imput | button | link")
    placeholder: Optional[str]=None
    text: Optional[str]=None
    aria_label: Optional[str]=None
    nearby_text: Optional[str]=None

class PageDSL(BaseModel):
    url: str
    elements: list[UIElement]


#-------------------------SELECTOR BUILDER------------------------
def css_selector(tag):
    """
    Generate a simple, readable CSS selector for an element.
    
    priority:
    1. id-> #id
    2. name-> [name='x']
    3.class-> tag.class1.class2(only first 2-3 classes)
    4.fallback-> tag name
    """
    if tag.get("id"):
        return f"#{tag['id']}"
    elif tag.get("name"):
        return f"[name='{tag['name']}']"
    elif tag.get("class"):
        #join a few classes(avoid long tailwind garbage)
        classes=".".join(tag.get("class")[:2])
        return F"{tag.name}.{classes}"
    else:
        return tag.name
    
def neighbour_text(tag, limit=2):
    """
    Grab nearby text nodes around an element for better context.
    This helps label unnamed elements(like buttons with only icons)
    """
    texts=[]
    #take a few previous and next siblings
    for sib in tag.find_all_previous(string=True, limit=limit):
        if sib.strip():
            s=sib.strip()
            if s and s not in texts:
                texts.append(sib.strip())
    for sib in tag.find_all_next(string=True, limit=limit):
        if sib.strip():
            s=sib.strip()
            if s and s not in texts:
                texts.append(sib.strip())
    
    return " ".join(texts[:3]) if texts else None


#-------------------------SELECTOR BUILDER------------------------
def build_ui_dsl(html:str, url:str, max_elements:int)->PageDSL:
    """
    parse the given html and extract key interactive elements.

    we'll target:
        -input/textarea/select(for typing)
        -button(for actions)
        -a(for navigation)
    """
    soup=BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    elements=[]

    #-----------------INPUTS--------------------
    for tag in soup.find_all(["input","textarea","select"]):

        if tag.get("type") == "hidden":
            continue

        #pick the best possbile human-readable label
        label=(
            tag.get("aria-label")
            or tag.get("placeholder")
            or tag.get("name")
            or tag.get("id")
        )

        #try to find an associated <label>
        if not label:
            label_tag=tag.find_previous("label")
            if label_tag:
                label=label_tag.get_text(strip=True)
        
        label=(label or "unlabeled input").strip()

        elements.append(
            UIElement(
                label=label,
                selector=css_selector(tag),
                type="input",
                placeholder=tag.get("placeholder"),
                aria_label=tag.get("aria-label"),
                nearby_text=neighbour_text(tag),
            )
        )

    #-----------------BUTTONS--------------------
    for tag in soup.find_all("button"):

        if tag.get("type") == "hidden":
            continue

        text=tag.get_text(strip=True)
        label=text or tag.get("aria-label") or "button"

        elements.append(
            UIElement(
                label=label.strip(),
                selector=css_selector(tag),
                type="button",
                text=text,
                aria_label=tag.get("aria-label"),
                nearby_text=neighbour_text(tag),
            )
        )

    #-----------------LINKS--------------------
    for tag in soup.find_all("a"):
        #skipping headden tags
        if tag.get("type") == "hidden":
            continue

        text=tag.get_text(strip=True)
        href=tag.get("href","")

        #skip invisible or meaningless links
        if not text and not re.search(r"login|sign|next|prev|home|", href, re.I):
            continue

        label=text or href or "link"

        skip_words = ["privacy", "terms", "cookies", "advertise", "language", "footer", "donate"]
        if any(w in label.lower() for w in skip_words):
            continue
        if len(label) > 60 or not re.search(r"[A-Za-z]", label):
            continue
        
        elements.append(
            UIElement(
                label=label.strip(),
                selector=css_selector(tag),
                type="link",
                text=text,
                nearby_text=neighbour_text(tag),
            )
        )
    
    # ----------------- DEDUPLICATION + CONTEXT FILTER -----------------
    unique = {}
    for el in elements:
        norm_label = re.sub(r'[^a-z0-9]+', '', el.label.lower())
        key = (norm_label, el.type)

        # Prefer elements not buried in footer/sidebar
        bad_zones = ["footer", "sidebar", "bottom", "ads"]
        bad_context = any(w in (el.selector + " " + (el.nearby_text or "")).lower() for w in bad_zones)
        if bad_context:
            continue

        # Keep first instance of each normalized label-type combo
        if key not in unique:
            unique[key] = el

    elements = list(unique.values())

    # --- Rank by importance ---
    def priority(el):
        t = el.type.lower()
        label = el.label.lower()
        score = 0

        # base by element type
        if t == "button": score += 100
        elif t == "input": score += 80
        elif t == "select": score += 70
        elif t == "link": score += 60
        else: score += 50

        # contextual keyword boost
        if any(k in label for k in ["login", "sign", "submit", "search", "next", "continue"]):
            score += 30
        if any(k in label for k in ["menu", "dashboard", "profile", "settings", "apply"]):
            score += 20
        if any(k in label for k in ["category"]):
            score += 10

        # slight penalty for too long labels
        if len(label) > 80:
            score -= 15

        return score

    elements.sort(key=priority, reverse=True)

    elements=elements[:max_elements]

    return PageDSL(url=url, elements=elements)


#-------------------------SELECTOR BUILDER------------------------
def main():
    parser=argparse.ArgumentParser(description="Generate simple DSL for webpage elements.")
    parser.add_argument("--url", required=True, help="target webpage URL")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    parser.add_argument("--max",type=int,default=50,help="The maximum tags to be returned")
    args=parser.parse_args()

    #launch playwright and fetch the page
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=args.headless)
        page=browser.new_page()

        print(f"[INFO] Navgating to t{args.url} ...")
        page.goto(args.url, wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # html=page.content()
        html = page.eval_on_selector_all("*", "els => els.filter(e => e.offsetParent !== null).map(e => e.outerHTML).join('')") #remove if tags not found
        browser.close()

    #build DSL from the fectched html
    print("[INFO] Building DSL ...")
    dsl=build_ui_dsl(html,args.url,max_elements=args.max)

    #pretty-print final JSON
    print(json.dumps(dsl.model_dump(), indent=2, ensure_ascii=False))

if __name__=="__main__":
    main()