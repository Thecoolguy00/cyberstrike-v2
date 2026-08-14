from prototype.ver4.schemas import HTTPObservation, Technology


class OpenAPIFingerprint:
    name = "openapi"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        value = (observation.final_url + " " + observation.body).lower()
        if "swagger" in value or "openapi" in value:
            return [Technology(name="OpenAPI/Swagger", category="api", confidence=0.85, evidence=["url/body: swagger or openapi marker"])]
        return []
