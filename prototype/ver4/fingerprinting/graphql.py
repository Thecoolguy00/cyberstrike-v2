from prototype.ver4.schemas import HTTPObservation, Technology


class GraphQLFingerprint:
    name = "graphql"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        value = (observation.final_url + " " + observation.body).lower()
        if "graphql" in value:
            return [Technology(name="GraphQL", category="api", confidence=0.85, evidence=["url/body: graphql marker"])]
        return []
