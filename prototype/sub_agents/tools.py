import subprocess
import tempfile
import textwrap
import sys
import asyncio

def execute_python(code: str, timeout=15):
    """Executes python code"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(textwrap.dedent(code))
        path = f.name

    try:
        proc = subprocess.run(
            #sys.executable returns the python path for the current environment, ensures code runs in main process python environment
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "Execution timed out"
        }
    

def extract_python_code(llm_output: str) -> str:
    """for python, extracts code from markdown"""
    if "```python" in llm_output:
        return llm_output.split("```python")[1].split("```")[0].strip()
    raise ValueError("No python code block found")


async def wait_for(minutes: float) -> str:
    """
    Wait/sleep for a specified duration in minutes (between 1.0 and 6.0 minutes).
    Useful to wait for background tasks/scans to progress.

    Args:
        minutes (float): The number of minutes to wait (between 1.0 and 6.0).
    """
    clamped_minutes = max(1.0, min(6.0, minutes))
    seconds = clamped_minutes * 60.0
    print(f"[wait_for] Sleeping for {clamped_minutes} minutes ({seconds} seconds)...")
    await asyncio.sleep(seconds)
    return f"Successfully waited/slept for {clamped_minutes} minutes."


# Exploit Intel Tools
import httpx
from typing import Optional
from prototype.sub_agents.search_actions import search_tavily

def search_vulnerabilities(technology: str, version: Optional[str] = None) -> str:
    """
    Search Tavily for known vulnerabilities, CVEs, and advisories for a technology.

    Args:
        technology: Technology name e.g. "copyparty", "Apache", "OpenSSH"
        version:    Version string e.g. "1.16.6" (optional but improves results)

    Returns:
        str: Combined search results from multiple targeted queries
    """
    queries = [
        f"{technology} vulnerabilities",
        f"{technology} CVE exploit",
    ]
    if version:
        queries.insert(0, f"{technology} {version} vulnerabilities")

    results = []
    for q in queries:
        try:
            r = search_tavily(q)
            results.append(f"[Query: {q}]\n{r}")
        except Exception as e:
            results.append(f"[Query: {q}] ERROR: {e}")

    return "\n\n".join(results)


def github_search_poc(technology: str, version: Optional[str] = None) -> str:
    """
    Search GitHub for public PoCs, exploit scripts, and nuclei templates.

    Args:
        technology: Technology name e.g. "copyparty"
        version:    Version string (optional)

    Returns:
        str: Matching GitHub repositories with descriptions and star counts
    """
    terms = [
        f"{technology} exploit",
        f"{technology} poc",
        f"{technology} CVE",
    ]
    if version:
        terms.insert(0, f"{technology} {version} exploit")

    results = []
    for term in terms[:3]:
        try:
            url = "https://api.github.com/search/repositories"
            resp = httpx.get(
                url,
                params={"q": term, "sort": "updated", "per_page": 5},
                headers={"Accept": "application/vnd.github+json"},
                timeout=15,
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                for item in items:
                    results.append(
                        f"  {item['full_name']} — {item.get('description', '')} "
                        f"[★{item.get('stargazers_count', 0)}] "
                        f"{item.get('html_url', '')}"
                    )
            elif resp.status_code == 403:
                results.append("GitHub rate limit hit — skipping remaining queries")
                break
            else:
                results.append(f"GitHub search error: HTTP {resp.status_code}")
        except Exception as e:
            results.append(f"GitHub search error: {e}")

    return (
        f"GitHub PoC search for '{technology}':\n" + "\n".join(results)
        if results else f"No GitHub results for '{technology}'"
    )


def nvd_lookup(cve_id: str) -> str:
    """
    Look up a CVE in the NVD API for authoritative metadata.

    Args:
        cve_id: CVE identifier e.g. "CVE-2023-38501"

    Returns:
        str: CVSS score, severity, CWE, description, and references
    """
    try:
        url = f"https://services.nvd.nist.gov/rest/json/cves/2.0"
        resp = httpx.get(
            url,
            params={"cveId": cve_id},
            timeout=20,
        )
        if resp.status_code != 200:
            return f"NVD lookup failed: HTTP {resp.status_code}"

        data = resp.json()
        vulns = data.get("vulnerabilities", [])
        if not vulns:
            return f"CVE {cve_id} not found in NVD"

        cve = vulns[0]["cve"]
        descriptions = cve.get("descriptions", [])
        desc = next((d["value"] for d in descriptions if d["lang"] == "en"), "No description")

        metrics = cve.get("metrics", {})
        cvss_score = "N/A"
        severity   = "N/A"
        for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if key in metrics and metrics[key]:
                m = metrics[key][0]["cvssData"]
                cvss_score = m.get("baseScore", "N/A")
                severity   = m.get("baseSeverity", "N/A")
                break

        weaknesses = [
            w["description"][0]["value"]
            for w in cve.get("weaknesses", [])
            if w.get("description")
        ]

        refs = [r["url"] for r in cve.get("references", [])[:5]]

        return (
            f"CVE: {cve_id}\n"
            f"Description: {desc[:300]}\n"
            f"CVSS Score: {cvss_score} ({severity})\n"
            f"CWE: {', '.join(weaknesses) or 'None'}\n"
            f"References:\n" + "\n".join(f"  {r}" for r in refs)
        )
    except Exception as e:
        return f"NVD lookup error: {e}"