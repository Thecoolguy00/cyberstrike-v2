from prototype.ver4.schemas import HTTPObservation, Technology


class GenericFingerprint:
    name = "generic"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        results = []
        server = observation.headers.get("server", "")
        powered = observation.headers.get("x-powered-by", "")
        if server:
            results.append(Technology(name=server.split("/")[0], category="server", confidence=0.8, evidence=[f"header: server={server}"]))
        if powered:
            results.append(Technology(name=powered.split("/")[0], category="runtime", confidence=0.7, evidence=[f"header: x-powered-by={powered}"]))
        return results
