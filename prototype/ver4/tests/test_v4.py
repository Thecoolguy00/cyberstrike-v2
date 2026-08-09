import unittest

from prototype.ver4.adapter import to_planner_input
from prototype.ver4.attack.strategic import target_tokens
from prototype.ver4.attack.tactical import filter_task_list
from prototype.ver4.decision.rules import confirmed_web_targets, has_web_evidence, rule_decision
from prototype.ver4.discovery.http import candidate_urls
from prototype.ver4.discovery.orchestrator import run_discovery
from prototype.ver4.intelligence import _apply_intel_result, exploit_key, intel_task, parse_intel_report
from prototype.ver4.parsers.ferox import parse_ferox
from prototype.ver4.parsers.nmap import parse_nmap
from prototype.ver4.report import build_report
from prototype.ver4.schemas import (
    DecisionAction,
    DiscoveryBudget,
    DiscoveryKnowledge,
    Endpoint,
    Finding,
    HTTPObservation,
    Task,
)


class FakeRuntime:
    def __init__(self, sweep="80/tcp open http\n8080/tcp open http-alt\n2222/tcp open unknown"):
        self.calls = []
        self.sweep = sweep

    async def network_scan(self, target, ports=None):
        self.calls.append(("network", target, ports))
        if ports:
            return "8080/tcp open http-alt nginx 1.25\n3923/tcp open rtsp"
        return "80/tcp open http nginx\n22/tcp open ssh OpenSSH 9.0"

    async def service_scan(self, target, ports):
        self.calls.append(("service", target, ports))
        if ports == "8080,2222":
            return "8080/tcp open http-alt nginx 1.25\n2222/tcp open http MiniServ"
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

    async def content_scan(self, url):
        self.calls.append(("content", url))
        return f"200      GET      123l      456w      789c {url}/swagger"

    async def start_long_port_scan(self, target, ports, max_runtime=900):
        self.calls.append(("l2_start", target, ports))
        return {"task_id": "l2_task_1", "status": "started"}

    async def get_task(self, task_id):
        self.calls.append(("l2_status", task_id))
        return {"id": task_id, "completed": True}

    async def get_task_output(self, task_id):
        self.calls.append(("l2_output", task_id))
        return self.sweep


def _knowledge_with_web() -> DiscoveryKnowledge:
    kb = DiscoveryKnowledge(target="example.test")
    kb.http_observations.append(HTTPObservation(method="GET", requested_url="http://example.test:80/", final_url="http://example.test:80/", status=200))
    return kb


class V4Tests(unittest.IsolatedAsyncioTestCase):
    def test_parsers(self):
        self.assertEqual(parse_nmap("80/tcp open http nginx 1.25")[0]["port"], 80)
        self.assertEqual(parse_ferox("200 GET 123 http://example.test/admin")[0]["url"], "http://example.test/admin")

    def test_nonstandard_ports_get_http_and_https_candidates(self):
        urls = candidate_urls("example.test", {"22": {"state": "open", "service": "ssh"}, "3923": {"state": "open", "service": "rtsp"}, "9000": {"state": "closed"}})
        self.assertEqual(urls, ["http://example.test:3923", "https://example.test:3923"])

    # ── Discovery order / L1 pipeline ───────────────────────────────────────

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

    # ── L2: full sweep, new-ports-only downstream, no L1 clobber ────────────

    async def test_l1_then_l2_dedup(self):
        runtime = FakeRuntime()
        result = await run_discovery("example.test", runtime=runtime, budget=DiscoveryBudget(max_http_requests=40, max_js_files=5, max_ferox_hits=5))

        l2 = await run_discovery("example.test", level=2, runtime=runtime, budget=DiscoveryBudget(max_http_requests=40, max_js_files=5, max_ferox_hits=5), knowledge=result)

        service_calls = [call for call in runtime.calls if call[0] == "service"]
        self.assertEqual(len(service_calls), 2)
        self.assertEqual(service_calls[-1][2], "8080,2222")
        self.assertNotIn("22", service_calls[-1][2].split(","))
        self.assertNotIn("80", service_calls[-1][2].split(","))

        # L1 fingerprints preserved on known ports
        self.assertEqual(l2.ports["80"]["version"], "nginx 1.25.0")
        self.assertIn("8080", l2.ports)
        self.assertIn("2222", l2.ports)
        self.assertEqual(l2.coverage["recon"]["network_l2"]["completed"], True)

        # ferox ran on the new web surface, and L1's :80 was NOT re-scanned (only once total)
        content_urls = [call[1] for call in runtime.calls if call[0] == "content"]
        self.assertEqual([url for url in content_urls if url.rstrip("/") == "http://example.test:80"], ["http://example.test:80"])
        self.assertTrue(any("8080" in url for url in content_urls))
        self.assertIn("http://example.test:2222", content_urls)

    async def test_l2_with_no_new_ports_probes_nothing(self):
        runtime = FakeRuntime(sweep="80/tcp open http\n22/tcp open ssh")
        result = await run_discovery("example.test", runtime=runtime, budget=DiscoveryBudget(max_http_requests=40))
        before = len(runtime.calls)
        await run_discovery("example.test", level=2, runtime=runtime, knowledge=result, budget=DiscoveryBudget(max_http_requests=40))
        new_http = [call for call in runtime.calls[before:] if call[0] == "http"]
        # No NEW ports were discovered in L2, so no HTTP probing is repeated.
        self.assertEqual(new_http, [])

    # ── Decision rules (deterministic, no LLM) ──────────────────────────────

    def test_rules_low_information_routes_to_l2(self):
        kb = DiscoveryKnowledge(target="example.test")
        kb.ports["22"] = {"state": "open", "service": "ssh", "version": "OpenSSH 9.0"}
        self.assertFalse(has_web_evidence(kb))
        decision = rule_decision(kb, full_scan_done=False)
        self.assertEqual(decision.action, DecisionAction.NETWORK_L2)

    def test_rules_no_web_after_l2_routes_to_report(self):
        kb = DiscoveryKnowledge(target="example.test")
        kb.ports["22"] = {"state": "open", "service": "ssh"}
        decision = rule_decision(kb, full_scan_done=True)
        self.assertEqual(decision.action, DecisionAction.REPORT)

    def test_rules_meaningful_surface_defers_to_llm(self):
        kb = _knowledge_with_web()
        self.assertTrue(has_web_evidence(kb))
        self.assertEqual(rule_decision(kb, full_scan_done=False), None)

    def test_confirmed_web_targets(self):
        kb = _knowledge_with_web()
        self.assertEqual(confirmed_web_targets(kb), ["http://example.test:80"])

    # ── Exploit intel node helpers ──────────────────────────────────────────

    def test_intel_report_parsing(self):
        sample = """EXPLOIT INTEL REPORT
technology: copyparty
version: 1.8.6
known_vulnerabilities: [CVE-2023-38501]
public_exploit: false
github_poc: true
exploitdb: false
severity: High
recommended_tests:
  - Check /api endpoint for path traversal
  - Look for unauthenticated admin endpoints
confidence: High
summary: copyparty 1.8.6 ships a known critical vulnerability.
"""
        parsed = parse_intel_report(sample)
        self.assertEqual(parsed["technology"], "copyparty")
        self.assertEqual(parsed["version"], "1.8.6")
        self.assertIn("CVE-2023-38501", parsed["cve"])
        self.assertEqual(parsed["severity"], "High")
        self.assertTrue(parsed["recommended_tests"])

        kb = DiscoveryKnowledge(target="example.test")
        self.assertTrue(_apply_intel_result(kb, sample))
        self.assertIn(exploit_key("copyparty", "1.8.6"), kb.exploit_intelligence)
        self.assertFalse(kb.exploit_intelligence["copyparty 1.8.6"].tested)

    def test_intel_task_scoping(self):
        exact = intel_task("nginx", "1.25")
        self.assertIn("nginx 1.25", exact["task_description"])
        self.assertEqual(exact["agent"], "intel_a")
        unknown = intel_task("python", None)
        self.assertIn("unknown version", unknown["task_description"])

    # ── Scoped attack: target allowlist / agent allowlist ───────────────────

    def test_filter_task_list_scoping(self):
        state = {"target": "http://example.test:80", "execution_history": []}
        tasks = [
            Task(agent="http_a", task_description="[vuln_analysis] Probe /admin on http://example.test:80", task_id="t1"),
            Task(agent="http_a", task_description="[vuln_analysis] Probe /admin on http://evil.example", task_id="t2"),
            Task(agent="nmap_a", task_description="[vuln_analysis] Scan http://example.test:80", task_id="t3"),
        ]
        kept, dropped, off_target = filter_task_list(tasks, state)
        self.assertEqual([task.task_id for task in kept], ["t1"])
        self.assertEqual(dropped, 2)
        self.assertEqual(off_target, 1)
        self.assertNotIn("evil.example", "|".join(task.task_description for task in kept))

    def test_target_tokens(self):
        tokens = target_tokens("http://example.test:80")
        self.assertIn("example.test", tokens)
        self.assertIn("example.test:80", tokens)
        self.assertIn("http://example.test:80", tokens)

    # ── Deterministic report builder ────────────────────────────────────────

    def test_report_builder(self):
        kb = DiscoveryKnowledge(target="example.test")
        kb.ports["80"] = {"state": "open", "service": "http", "version": "nginx 1.25.0"}
        kb.endpoints["http://example.test:80/"] = Endpoint(url="http://example.test:80/", status=200, source="http")
        kb.findings["f1"] = Finding(
            id="f1",
            type="Reflected XSS",
            location="http://example.test:80/?q=",
            severity="High",
            confirmed=True,
            description="Input reflected unescaped.",
            evidence="<script>alert(1)</script>",
            source="xss_a",
        )
        report = build_report(kb)
        self.assertIn("Penetration Test Report", report)
        self.assertIn("Findings", report)
        self.assertIn("Reflected XSS", report)
        self.assertIn("http://example.test:80", report)


if __name__ == "__main__":
    unittest.main()