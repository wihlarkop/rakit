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


@dataclass(frozen=True)
class EndpointResult[TEndpointPayload]:
    payload: TEndpointPayload
    status_code: int = 200
