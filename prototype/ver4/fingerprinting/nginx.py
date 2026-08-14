from prototype.ver4.schemas import HTTPObservation, Technology


class NginxFingerprint:
    name = "nginx"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        value = observation.headers.get("server", "")
        if "nginx" not in value.lower():
            return []
        version = value.split("/", 1)[1] if "/" in value else None
        return [Technology(name="nginx", category="server", version=version, confidence=0.98, evidence=[f"header: server={value}"])]
