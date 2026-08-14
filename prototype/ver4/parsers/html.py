"""HTML surface extraction without browser execution."""

from typing import Any, Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def parse_html(body: str, base_url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(body or "", "html.parser")
    links = sorted({urljoin(base_url, tag.get("href")) for tag in soup.find_all("a", href=True)})
    scripts = sorted({urljoin(base_url, tag.get("src")) for tag in soup.find_all("script", src=True)})
    forms = []
    inputs = []
    for form in soup.find_all("form"):
        action = urljoin(base_url, form.get("action") or base_url)
        method = (form.get("method") or "GET").upper()
        forms.append({"url": action, "method": method})
        for field in form.find_all(["input", "textarea", "select"]):
            name = field.get("name")
            if name:
                inputs.append({"url": action, "param": name, "method": method, "type": field.get("type", field.name)})

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta = {tag.get("name", "").lower(): tag.get("content", "") for tag in soup.find_all("meta", attrs={"name": True, "content": True})}
    api_references = sorted({urljoin(base_url, value) for value in links if any(token in value.lower() for token in ("api", "swagger", "openapi", "graphql"))})
    return {"links": links, "scripts": scripts, "forms": forms, "inputs": inputs, "title": title, "meta": meta, "api_references": api_references}
