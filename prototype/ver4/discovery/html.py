"""HTML normalization stage."""

from typing import Dict, List, Tuple

from prototype.ver4.parsers.html import parse_html
from prototype.ver4.schemas import Capability, Endpoint, HTTPObservation, InputPoint, Observation


def extract_html(responses: List[HTTPObservation]) -> Tuple[List[Observation], Dict[str, Endpoint], Dict[str, InputPoint], List[str]]:
    observations = []
    endpoints: Dict[str, Endpoint] = {}
    inputs: Dict[str, InputPoint] = {}
    scripts = set()
    for response in responses:
        if "html" not in response.content_type.lower() and "<html" not in response.body.lower():
            continue
        parsed = parse_html(response.body, response.final_url or response.requested_url)
        for link in parsed["links"] + parsed["api_references"]:
            endpoints.setdefault(link, Endpoint(url=link, status=response.status, source="html"))
        for form in parsed["forms"]:
            endpoints.setdefault(form["url"], Endpoint(url=form["url"], methods=[form["method"]], source="form"))
        for item in parsed["inputs"]:
            key = f"{item['method']}:{item['url']}:{item['param']}"
            inputs.setdefault(key, InputPoint(url=item["url"], param=item["param"], method=item["method"], input_type=item.get("type", ""), source="html"))
        scripts.update(parsed["scripts"])
        observations.append(Observation(capability=Capability.HTML, target=response.final_url or response.requested_url, evidence=parsed))
    return observations, endpoints, inputs, sorted(scripts)
