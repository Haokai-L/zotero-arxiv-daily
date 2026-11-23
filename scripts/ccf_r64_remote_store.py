"""R6-4 GitHub Contents-API optimistic-CAS ledger transport.

This module has NO SMTP code and is locked to synthetic test-only probe files.
It deliberately never writes data/ccf_sent_history.json or production ledger.
Remote acceptance is verified by reading back the resulting blob.
"""
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

BRANCH = "feature/ccf-a-daily"
PROBE_PATH = re.compile(r"^data/r64_probes/[0-9]{6,20}-[0-9]{1,3}\.json$")
REPO_PATH = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
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
            "User-Agent": "ccf-r64-no-email-persistence-probe",
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


class ProbeStore:
    """Write allowlist applies to *all* operations, not just command entrypoint."""

    def __init__(self, repo, branch, path, transport):
        if not isinstance(repo, str) or not REPO_PATH.fullmatch(repo):
            raise SafetyError("Invalid repository name")
        if branch != BRANCH or not isinstance(path, str) or not PROBE_PATH.fullmatch(path):
            raise SafetyError("R6-4 writes only isolated probe files on feature branch")
        if transport is None:
            raise SafetyError("Transport required")
        self.repo, self.branch, self.path, self.transport = repo, branch, path, transport
        self.route = "/repos/" + repo + "/contents/" + quote(path, safe="/")

    def read(self):
        raw = self.transport.request("GET", self.route + "?ref=" + quote(self.branch, safe=""))
        if raw is None:
            return None
        if not isinstance(raw, dict) or raw.get("encoding") != "base64":
            raise PersistenceError("GitHub content encoding is not base64")
        sha = raw.get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise PersistenceError("GitHub returned invalid blob SHA")
        try:
            binary = base64.b64decode(raw["content"], validate=False)
            ledger = json.loads(binary)
            check_ledger(ledger)
        except (KeyError, ValueError, TypeError, SafetyError) as exc:
            raise PersistenceError("GitHub ledger is unreadable or invalid") from exc
        return Snapshot(ledger, sha)

    def write(self, ledger, expected_sha, reason):
        content = canonical_bytes(ledger)
        if expected_sha is not None and (not isinstance(expected_sha, str) or
                                         not re.fullmatch(r"[a-f0-9]{40}", expected_sha)):
            raise SafetyError("Invalid expected blob SHA")
        if not isinstance(reason, str) or not reason or len(reason) > 100:
            raise SafetyError("Invalid persistence reason")
        payload = {
            "message": "test(r6-4): " + reason + " [skip ci]",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.branch
        }
        if expected_sha is not None:
            payload["sha"] = expected_sha
        reply = self.transport.request("PUT", self.route, payload)
        new_sha = (reply or {}).get("content", {}).get("sha")
        if not isinstance(new_sha, str):
            raise PersistenceError("GitHub did not return a committed file SHA")
        # A successful PUT alone isn't sufficient: re-read remote HEAD.
        current = self.read()
        if current is None or current.sha != new_sha:
            raise PersistenceError("GitHub read-after-write SHA mismatch")
        if canonical_bytes(current.ledger) != content:
            raise PersistenceError("GitHub read-after-write contents mismatch")
        return current


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
