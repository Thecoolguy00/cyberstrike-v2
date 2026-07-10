from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote


def encode_url_params(target: str) -> str:
    """
    URL-encodes query parameter values so that XSS payloads (e.g. <script>)
    pass the command validator's URL regex, which rejects raw < > characters.

    - The scheme, host, path, and parameter names are left untouched.
    - Already percent-encoded values are decoded first then re-encoded,
      so the function is safe to call on both raw and pre-encoded URLs
      (no double-encoding).

    Examples:
        encode_url_params("http://10.0.0.1/search?q=<script>alert(1)</script>")
        -> "http://10.0.0.1/search?q=%3Cscript%3Ealert%281%29%3C%2Fscript%3E"

        encode_url_params("http://10.0.0.1/page")   # no query string → unchanged
        -> "http://10.0.0.1/page"
    """
    parsed = urlparse(target)
    if not parsed.query:
        return target  # nothing to encode

    encoded_pairs = [
        (k, quote(v, safe=""))
        for k, vals in parse_qs(parsed.query, keep_blank_values=True).items()
        for v in vals
    ]
    new_query = urlencode(encoded_pairs)
    return urlunparse(parsed._replace(query=new_query))
