"""Fingerprint interface."""

from typing import List, Protocol

from prototype.ver4.schemas import HTTPObservation, Technology


class Fingerprint(Protocol):
    name: str

    def match(self, observation: HTTPObservation) -> List[Technology]: ...
