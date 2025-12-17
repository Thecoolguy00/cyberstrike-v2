"""
dsl_gen_v3.py
Smarter DSL generator for general + dashboard-style sites.
Keeps structured links (nav menus, dashboards, episode lists) without spamming footers.
"""

#this one skips some tags, so we will not use this for now

import argparse, json, re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from typing import Optional
from pydantic import BaseModel, Field

class UIElement(BaseModel):
    label: str
    selector: str
    type: str
    placeholder: Optional[str] = None
    text: Optional[str] = None
    aria_label: Optional[str] = None
    nearby_text: Optional[str] = None

class PageDSL(BaseModel):
    url: str
    elements: list[UIElement]

# --- Utility helpers ---
def css_selector(tag):
    if tag.get("id"):
        return f"#{tag['id']}"
    if tag.get("name"):
        return f"[name='{tag['name']}']"
    if tag.get("class"):
        c = ".".join(tag.get("class")[:2])
        return f"{tag.name}.{c}"
    return tag.name

def neighbour_text(tag, limit=2):
    texts = []
    for sib in tag.find_all_previous(string=True, limit=limit):
        if sib.strip():
            texts.append(sib.strip())
    for sib in tag.find_all_next(string=True, limit=limit):
        if sib.strip():
            texts.append(sib.strip())
    return " ".join(texts[:3]) if texts else None

# --- Core DSL builder ---
def build_ui_dsl(html: str, url: str) -> PageDSL:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    elements = []

    # Inputs
    for tag in soup.find_all(["input", "textarea", "select"]):
        if tag.get("type") == "hidden":
            continue
        label = (
            tag.get("aria-label")
            or tag.get("placeholder")
            or tag.get("name")
            or tag.get("id")
        )
        if not label:
            lab = tag.find_previous("label")
            if lab:
                label = lab.get_text(strip=True)
        label = (label or "unlabeled input").strip()
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

    # Buttons
    for tag in soup.find_all("button"):
        if tag.get("type") == "hidden":
            continue
        text = tag.get_text(strip=True)
        label = text or tag.get("aria-label") or "button"
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

    # Links
    for tag in soup.find_all("a"):
        if tag.get("type") == "hidden":
            continue
        text = tag.get_text(strip=True)
        href = tag.get("href", "")
        label = text or href or "link"

        # Skip trivial junk only
        skip_words = ["privacy", "cookie", "terms", "policy", "ads", "login/?redirect", "feed"]
        if any(w in href.lower() or w in label.lower() for w in skip_words):
            continue
        if not label.strip():
            continue
        # keep navs, categories, dashboards
        if len(label) > 120:
            continue
        if label.strip().isdigit():
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

    # Deduplicate
    unique = {}
    for el in elements:
        key = (el.selector, el.label.lower())
        if key not in unique:
            unique[key] = el
    elements = list(unique.values())

    # Rank gently: don't kill navs, just float priority stuff up
    def score(el):
        s = el.label.lower()
        if any(k in s for k in ["login", "sign in", "dashboard", "submit", "search", "next"]):
            return 10
        if any(k in s for k in ["home", "menu", "category", "series","profile"]):
            return 7
        return 5

    elements.sort(key=score, reverse=True)
    return PageDSL(url=url, elements=elements)

def main():
    parser = argparse.ArgumentParser(description="Generate DSL for interactive webpage elements.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        print(f"[INFO] Navigating to {args.url} ...")
        page.goto(args.url, wait_until="load")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        html = page.eval_on_selector_all("*", "els => els.filter(e => e.offsetParent !== null).map(e => e.outerHTML).join('')")
        browser.close()

    print("[INFO] Building DSL ...")
    dsl = build_ui_dsl(html, args.url)
    print(json.dumps(dsl.model_dump(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
