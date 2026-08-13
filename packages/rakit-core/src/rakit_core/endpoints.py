"""Typed endpoint declaration primitives without a web runtime."""

from dataclasses import dataclass
from enum import StrEnum


class EndpointInputSource(StrEnum):
    QUERY = "query"
    JSON = "json"
    FORM = "form"


class EndpointMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class EndpointAccessPolicy(StrEnum):
    """Endpoint exposure is private unless a definition opts in explicitly."""

    PRIVATE = "private"
    PUBLIC = "public"


class EndpointResponseKind(StrEnum):
    """Semantic result transport; web adapters map these to concrete responses."""

    JSON = "json"
    FILE = "file"
    STREAM = "stream"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class EndpointResult[TEndpointPayload]:
    payload: TEndpointPayload
    status_code: int = 200
    kind: EndpointResponseKind = EndpointResponseKind.JSON
