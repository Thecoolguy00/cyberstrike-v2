import httpx
import json
from typing import Optional, Dict, Any

PRESETS: Dict[str, Dict[str, str]] = {
    "browser": {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
    },
    "api": {
        "User-Agent": "python-httpx/0.27",
        "Accept": "application/json",
        "Content-Type": "application/json",
    },
    "plain": {},
    "webdav": {
        "User-Agent": "python-httpx/0.27",
        "Depth": "1",
    },
}

BODY_SIZE_LIMIT = 50_000

def http_request_action(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    body: Optional[str] = None,
    json_data: Optional[Any] = None,
    form_data: Optional[Dict[str, str]] = None,
    follow_redirects: bool = True,
    timeout: int = 30,
    preset: str = "plain",
) -> Dict[str, Any]:
    method = method.upper()
    preset_headers = PRESETS.get(preset, {})
    merged_headers = {**preset_headers, **(headers or {})}

    try:
        with httpx.Client(
            follow_redirects=follow_redirects,
            timeout=timeout,
            verify=False,
        ) as client:
            req_kwargs: Dict[str, Any] = {
                "headers": merged_headers,
                "params":  params,
                "cookies": cookies,
            }
            if json_data is not None:
                req_kwargs["json"] = json_data
            elif form_data is not None:
                req_kwargs["data"] = form_data
            elif body is not None:
                req_kwargs["content"] = body.encode()

            response = client.request(method, url, **req_kwargs)

        raw_body = response.text
        truncated = len(raw_body) > BODY_SIZE_LIMIT
        body_out  = raw_body[:BODY_SIZE_LIMIT] if truncated else raw_body

        return {
            "status":        response.status_code,
            "headers":       dict(response.headers),
            "body":          body_out,
            "cookies":       dict(response.cookies),
            "content_type":  response.headers.get("content-type", ""),
            "response_time": response.elapsed.total_seconds(),
            "redirects":     [str(r.url) for r in response.history],
            "truncated":     truncated,
            "error":         None,
        }

    except httpx.TimeoutException:
        return _error_response(f"Request timed out after {timeout}s")
    except httpx.RequestError as e:
        return _error_response(f"Request error: {e}")
    except Exception as e:
        return _error_response(f"Unexpected error: {e}")


def _error_response(msg: str) -> Dict[str, Any]:
    return {
        "status": None, "headers": {}, "body": "",
        "cookies": {}, "content_type": "", "response_time": None,
        "redirects": [], "truncated": False, "error": msg,
    }
