"""The only V4-to-legacy planner compatibility boundary."""

from typing import Any, Dict, TYPE_CHECKING

from prototype.ver4.schemas import DiscoveryKnowledge, PlannerInput

if TYPE_CHECKING:
    from prototype.sub_agents.schemas import TargetKnowledge


def to_planner_input(discovery: DiscoveryKnowledge) -> PlannerInput:
    services = dict(discovery.services)
    for technology in discovery.technologies.values():
        services.setdefault(technology.name, {"version": technology.version or "unknown", "tech_stack": [technology.name], "confidence": technology.confidence, "evidence": technology.evidence})
    knowledge: Dict[str, Any] = {
        "ports": discovery.ports,
        "services": services,
        "endpoints_dict": {key: value.model_dump(mode="json") for key, value in discovery.endpoints.items()},
        "inputs": {key: value.model_dump(mode="json") for key, value in discovery.inputs.items()},
        "notes": list(discovery.errors),
        "coverage": discovery.coverage,
        "technologies": {key: value.model_dump(mode="json") for key, value in discovery.technologies.items()},
    }
    return PlannerInput(target=discovery.target, knowledge=knowledge, observations=discovery.observations, errors=discovery.errors)


def to_legacy_knowledge(planner_input: PlannerInput) -> "TargetKnowledge":
    from prototype.sub_agents.schemas import void_knowledge

    base = void_knowledge()
    incoming = planner_input.knowledge
    base["ports"].update(incoming.get("ports", {}))
    base["services"].update(incoming.get("services", {}))
    base["endpoints_dict"].update(incoming.get("endpoints_dict", {}))
    base["inputs"].update(incoming.get("inputs", {}))
    base["notes"].extend(incoming.get("notes", []))
    for phase, checks in incoming.get("coverage", {}).items():
        base["coverage"].setdefault(phase, {}).update(checks)
    base["open_ports"] = [{"port": int(port), **value} for port, value in base["ports"].items()]
    base["web_services"] = [{"url": value.get("url", ""), "port": value.get("port", 80), "tech_stack": value.get("tech_stack", [])} for value in base["services"].values()]
    base["endpoints"] = list(base["endpoints_dict"])
    base["input_points"] = list(base["inputs"].values())
    return base
