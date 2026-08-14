from prototype.ver4.schemas import HTTPObservation, Technology


class LaravelFingerprint:
    name = "laravel"

    def match(self, observation: HTTPObservation) -> list[Technology]:
        if any("laravel_session" in key.lower() for key in observation.cookies):
            return [Technology(name="Laravel", category="framework", confidence=0.95, evidence=["cookie: laravel_session"])]
        if "laravel" in observation.body.lower():
            return [Technology(name="Laravel", category="framework", confidence=0.75, evidence=["body: laravel marker"])]
        return []
