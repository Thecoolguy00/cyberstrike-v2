"""Static, intentionally boring technology fingerprint registry."""

from prototype.ver4.fingerprinting.base import Fingerprint
from prototype.ver4.fingerprinting.generic import GenericFingerprint
from prototype.ver4.fingerprinting.graphql import GraphQLFingerprint
from prototype.ver4.fingerprinting.laravel import LaravelFingerprint
from prototype.ver4.fingerprinting.nginx import NginxFingerprint
from prototype.ver4.fingerprinting.openapi import OpenAPIFingerprint
from prototype.ver4.fingerprinting.spring import SpringFingerprint
from prototype.ver4.fingerprinting.wordpress import WordPressFingerprint

FINGERPRINTS: list[Fingerprint] = [
    GenericFingerprint(),
    NginxFingerprint(),
    WordPressFingerprint(),
    LaravelFingerprint(),
    SpringFingerprint(),
    OpenAPIFingerprint(),
    GraphQLFingerprint(),
]

__all__ = ["FINGERPRINTS", "Fingerprint"]
