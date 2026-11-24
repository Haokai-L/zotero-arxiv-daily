"""Shared GitHub optimistic-CAS transport for delivery state."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ccf_r63_delivery import SafetyError, check_ledger

API_ORIGIN = "https://api.github.com"


class CASConflict(SafetyError):
    """The expected Github file version is no longer current."""


class PersistenceError(SafetyError):
    """Remote persistence is unavailable or unverified; do not send."""


@dataclass(frozen=True)
class Snapshot:
    ledger: dict
    sha: str


def canonical_bytes(ledger):
    check_ledger(ledger)
    return (json.dumps(ledger, ensure_ascii=False, sort_keys=True,
                       indent=2, separators=(",", ": ")) + "\n").encode("utf-8")


class GithubTransport:
    """Minimal synchronous GitHub REST transport; all errors fail closed."""

    def __init__(self, token):
        if not isinstance(token, str) or not token:
            raise PersistenceError("GitHub token unavailable")
        self._token = token

    def request(self, method, route, payload=None):
        if not route.startswith("/repos/") or "://" in route:
            raise PersistenceError("Unexpected GitHub API route")
        url = API_ORIGIN + route
        data = None if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        req = Request(url, data=data, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self._token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ccf-delivery",
            "Content-Type": "application/json"
        })
        try:
            with urlopen(req, timeout=30) as result:
                return json.load(result)
        except HTTPError as exc:
            # Never log response bodies or bearer token.
            if method == "GET" and exc.code == 404:
                return None
            if method == "PUT" and exc.code in (409, 422):
                raise CASConflict("GitHub optimistic-CAS update rejected") from None
            raise PersistenceError("GitHub persistence HTTP " + str(exc.code)) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise PersistenceError("GitHub transport unavailable: " + type(exc).__name__) from None

