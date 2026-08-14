from prototype.ver4.schemas import HTTPObservation, Technology


class WordPressFingerprint:
    name = "wordpress"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        body = observation.body.lower()
        evidence = []
        if "wp-content" in body:
            evidence.append("html: wp-content")
        if "wp-includes" in body:
            evidence.append("html: wp-includes")
        if any("wordpress" in value.lower() for value in observation.headers.values()):
            evidence.append("header: wordpress marker")
        if evidence:
            return [Technology(name="WordPress", category="cms", confidence=0.95, evidence=evidence)]
        return []
