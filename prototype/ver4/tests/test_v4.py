import unittest

from prototype.ver4.adapter import to_planner_input
from prototype.ver4.discovery.orchestrator import run_discovery
from prototype.ver4.parsers.ferox import parse_ferox
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.schemas import DiscoveryBudget


class FakeRuntime:
    def __init__(self):
        self.calls = []

    async def network_scan(self, target):
        self.calls.append(("network", target))
        return "80/tcp open http nginx\n22/tcp open ssh OpenSSH 9.0"

    async def service_scan(self, target, ports):
        self.calls.append(("service", target, ports))
        return "80/tcp open http nginx 1.25.0\n22/tcp open ssh OpenSSH 9.0"

    async def http_request(self, method, url, max_body_size, max_redirects):
        self.calls.append(("http", method, url))
        body = """
        <html><head><title>Demo</title><script src='/app.js'></script></head>
        <body><a href='/admin'>Admin</a><form action='/login' method='post'>
        <input name='username' type='text'></form></body></html>
        """
        if url.endswith("app.js"):
            body = "const endpoint = '/api/users'; const graph = '/graphql';"
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

    async def test_discovery_order_and_adapter(self):
        runtime = FakeRuntime()
        result = await run_discovery("example.test", runtime=runtime, budget=DiscoveryBudget(max_http_requests=40, max_js_files=5, max_ferox_hits=5))
        self.assertEqual(runtime.calls[0][0], "network")
        phases = [call[0] for call in runtime.calls]
        content_index = phases.index("content")
        self.assertGreater(content_index, phases.index("http"))
        self.assertIn("http", phases[content_index + 1:])
        self.assertIn("80", result.ports)
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

    async def test_target_rejects_shell_fragments(self):
        with self.assertRaises(ValueError):
            await run_discovery("example.test; whoami", runtime=FakeRuntime())


if __name__ == "__main__":
    unittest.main()
