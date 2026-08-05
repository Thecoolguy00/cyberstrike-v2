import unittest

from prototype.ver4.adapter import to_planner_input
from prototype.ver4.discovery.orchestrator import run_discovery
from prototype.ver4.discovery.http import candidate_urls
from prototype.ver4.parsers.ferox import parse_ferox
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.schemas import DiscoveryBudget


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def network_scan(self, target, ports=None):
        self.calls.append(("network", target, ports))
        if ports:
            return "8080/tcp open http-alt nginx 1.25\n3923/tcp open rtsp"
        return "80/tcp open http nginx\n22/tcp open ssh OpenSSH 9.0"

    async def service_scan(self, target, ports):
        self.calls.append(("service", target, ports))
        return "80/tcp open http nginx 1.25.0\n22/tcp open ssh OpenSSH 9.0"

    async def http_request(self, method, url, max_body_size, max_redirects, timeout=5, verify_ssl=True):
        self.calls.append(("http", method, url))
        body = """
        <html><head><title>Demo</title><script src='/app.js'></script></head>
        <body><a href='/admin'>Admin</a><form action='/login' method='post'>
        <input name='username' type='text'></form></body></html>
        """
        if url.endswith("app.js"):
            body = "const endpoint = '/api/users'; const graph = '/graphql';"
        if url.startswith("https://") and verify_ssl:
            return {"error": "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed certificate"}
        return {
            "status": 200,
            "headers": {"server": "nginx/1.25.0", "content-type": "text/html" if not url.endswith("app.js") else "application/javascript"},
            "cookies": {"laravel_session": "abc"},
            "redirects": [],
            "content_type": "text/html" if not url.endswith("app.js") else "application/javascript",
            "body": body,
            "url": url,
            "error": None,
        }

    async def content_scan(self, url, max_runtime):
        self.calls.append(("content", url))
        return f"200      GET      123l      456w      789c {url}/swagger"


class V4Tests(unittest.IsolatedAsyncioTestCase):
    def test_parsers(self):
        self.assertEqual(parse_nmap("80/tcp open http nginx 1.25")[0]["port"], 80)
        self.assertEqual(parse_ferox("200 GET 123 http://example.test/admin")[0]["url"], "http://example.test/admin")

    def test_nonstandard_ports_get_http_and_https_candidates(self):
        urls = candidate_urls("example.test", {"22": {"state": "open", "service": "ssh"}, "3923": {"state": "open", "service": "rtsp"}, "9000": {"state": "closed"}})
        self.assertEqual(urls, ["http://example.test:3923", "https://example.test:3923"])

    async def test_discovery_order_and_adapter(self):
        runtime = FakeRuntime()
        result = await run_discovery("example.test", runtime=runtime, ports=["8080"], budget=DiscoveryBudget(max_http_requests=40, max_js_files=5, max_ferox_hits=5))
        self.assertEqual(runtime.calls[0][0], "network")
        network_calls = [call for call in runtime.calls if call[0] == "network"]
        self.assertEqual(len(network_calls), 2)
        self.assertEqual(network_calls[1][2], ["8080"])
        phases = [call[0] for call in runtime.calls]
        content_index = phases.index("content")
        self.assertGreater(content_index, phases.index("http"))
        self.assertIn("http", phases[content_index + 1:])
        self.assertIn("80", result.ports)
        self.assertIn("8080", result.ports)
        self.assertIn("Laravel", result.technologies)
        self.assertIn("nginx", result.technologies)
        self.assertIn("/api/users", " ".join(result.endpoints))
        planner_input = to_planner_input(result)
        try:
            from prototype.ver4.adapter import to_legacy_knowledge
            legacy = to_legacy_knowledge(planner_input)
        except ModuleNotFoundError as exc:
            if exc.name not in {"langgraph", "langchain_core"}:
                raise
        else:
            self.assertIn("80", legacy["ports"])
        self.assertTrue(legacy["endpoints"])

        tls_retries = [call for call in runtime.calls if call[0] == "http" and call[2].startswith("https://")]
        self.assertTrue(tls_retries)

    async def test_target_rejects_shell_fragments(self):
        with self.assertRaises(ValueError):
            await run_discovery("example.test; whoami", runtime=FakeRuntime())


if __name__ == "__main__":
    unittest.main()
