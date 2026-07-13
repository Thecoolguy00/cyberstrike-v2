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

def http_request_action(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    cookies: Optional[Dict[str, str]] = None,
    raw_data: Optional[str] = None,
    json_data: Optional[Any] = None,
    form_data: Optional[Dict[str, str]] = None,
    files: Optional[Dict[str, str]] = None,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    timeout: int = 30,
    max_body_size: Optional[int] = 50_000,
    preset: str = "plain",
) -> Dict[str, Any]:
    method = method.upper()
    preset_headers = PRESETS.get(preset, {})
    merged_headers = {**preset_headers, **(headers or {})}

    opened_files = []
    try:
        if files:
            req_files = {}
            for name, path in files.items():
                f = open(path, "rb")
                opened_files.append(f)
                req_files[name] = f
        else:
            req_files = None

        with httpx.Client(
            follow_redirects=follow_redirects,
            timeout=timeout,
            verify=verify_ssl,
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
            elif raw_data is not None:
                req_kwargs["content"] = raw_data.encode()

            if req_files is not None:
                req_kwargs["files"] = req_files

            response = client.request(method, url, **req_kwargs)

        raw_body = response.text
        body_truncated = False
        if max_body_size is not None and len(raw_body) > max_body_size:
            body_truncated = True
            body_out = raw_body[:max_body_size]
        else:
            body_out = raw_body

        content_length = None
        cl_header = response.headers.get("content-length")
        if cl_header is not None:
            try:
                content_length = int(cl_header)
            except ValueError:
                pass
        if content_length is None:
            content_length = len(response.content)

        return {
            "status":         response.status_code,
            "reason":         response.reason_phrase,
            "headers":        dict(response.headers),
            "body":           body_out,
            "cookies":        dict(response.cookies),
            "content_type":   response.headers.get("content-type", ""),
            "content_length": content_length,
            "url":            str(response.url),
            "redirects":      [str(r.url) for r in response.history],
            "response_time":  response.elapsed.total_seconds(),
            "body_truncated": body_truncated,
            "encoding":       response.encoding or "utf-8",
            "error":          None,
        }

    except httpx.TimeoutException:
        return _error_response(f"Request timed out after {timeout}s")
    except httpx.RequestError as e:
        return _error_response(f"Request error: {e}")
    except FileNotFoundError as e:
        return _error_response(f"File upload error: File not found: {e.filename}")
    except PermissionError as e:
        return _error_response(f"File upload error: Permission denied: {e.filename}")
    except Exception as e:
        return _error_response(f"Unexpected error: {e}")
    finally:
        for f in opened_files:
            try:
                f.close()
            except Exception:
                pass


def _error_response(msg: str) -> Dict[str, Any]:
    return {
        "status": None,
        "reason": None,
        "headers": {},
        "body": "",
        "cookies": {},
        "content_type": "",
        "content_length": 0,
        "url": "",
        "redirects": [],
        "response_time": None,
        "body_truncated": False,
        "encoding": "",
        "error": msg,
    }
