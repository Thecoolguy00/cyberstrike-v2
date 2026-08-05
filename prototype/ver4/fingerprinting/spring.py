from prototype.ver4.schemas import HTTPObservation, Technology


class SpringFingerprint:
    name = "spring"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        body = observation.body.lower()
        evidence = []
        if "whitelabel error page" in body:
            evidence.append("body: Whitelabel Error Page")
        if "spring boot" in body:
            evidence.append("body: Spring Boot")
        if evidence:
            return [Technology(name="Spring Boot", category="framework", confidence=0.9, evidence=evidence)]
        return []
