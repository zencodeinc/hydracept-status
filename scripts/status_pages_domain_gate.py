"""GitHub Pages domain gate (strict) + public-repo attestation for DNS safety."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

DEFAULT_STATUS_REPO = "zencodeinc/hydracept-status"
EXPECTED_CNAME = "status.hydracept.com"
ATTESTATION_PATH = ".hydracept/pages-domain-attestation.json"
ATTESTATION_REF = "main"
ATTESTATION_VERSION = 1
MAX_ATTESTATION_AGE_SECONDS = 24 * 3600
MAX_ATTESTATION_FUTURE_SECONDS = 5 * 60
MAX_COMMIT_ATTESTATION_DRIFT_SECONDS = 5 * 60
GITHUB_ACTIONS_BOT_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_BOT_EMAILS = frozenset(
    {
        "41898282+github-actions[bot]@users.noreply.github.com",
        "github-actions[bot]@users.noreply.github.com",
    }
)


class PagesGateError(SystemExit):
    """Raised when Pages state fails closed (maps to exit code 1 via SystemExit)."""


def _parse_github_timestamp(raw: str) -> datetime:
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PagesGateError(f"invalid timestamp: {raw!r}") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def validate_pages_payload(payload: dict[str, Any], *, expected_cname: str = EXPECTED_CNAME) -> None:
    """Fail closed unless Pages is built, Actions-deployed, cname matches, domain verified."""
    if not isinstance(payload, dict):
        raise PagesGateError("Pages payload must be a JSON object")

    status = payload.get("status")
    if status != "built":
        raise PagesGateError(f"GitHub Pages status must be 'built', got {status!r}")

    cname_raw = payload.get("cname")
    if not cname_raw:
        raise PagesGateError(f"GitHub Pages cname is missing; expected {expected_cname!r}")
    cname = str(cname_raw).rstrip(".").lower()
    if cname != expected_cname.rstrip(".").lower():
        raise PagesGateError(
            f"GitHub Pages cname is {cname_raw!r}, expected {expected_cname!r} "
            "(custom domain must be verified before public DNS)"
        )

    domain_state = payload.get("protected_domain_state")
    if domain_state != "verified":
        raise PagesGateError(
            f"GitHub Pages protected_domain_state must be exactly 'verified', got {domain_state!r}"
        )

    build_type = payload.get("build_type")
    if build_type is None:
        raise PagesGateError(
            "GitHub Pages build_type is null — set Pages source to GitHub Actions, run status-probe "
            "deploy successfully, then re-run pages-domain-attestation"
        )
    if build_type != "workflow":
        raise PagesGateError(
            f"GitHub Pages build_type must be 'workflow' (Actions deploy), got {build_type!r}"
        )


def build_attestation_document(pages_payload: dict[str, Any], *, repo: str) -> dict[str, Any]:
    validate_pages_payload(pages_payload)
    return {
        "version": ATTESTATION_VERSION,
        "attested_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "github_repository": repo,
        "pages": {
            "status": pages_payload.get("status"),
            "cname": pages_payload.get("cname"),
            "protected_domain_state": pages_payload.get("protected_domain_state"),
            "build_type": pages_payload.get("build_type"),
            "https_enforced": pages_payload.get("https_enforced"),
            "html_url": pages_payload.get("html_url"),
        },
    }


def _validate_attested_at_freshness(attested_at: str) -> datetime:
    moment = _parse_github_timestamp(attested_at)
    now = datetime.now(tz=UTC)
    age = (now - moment).total_seconds()
    if age < -MAX_ATTESTATION_FUTURE_SECONDS:
        raise PagesGateError(
            f"attestation attested_at is {int(-age)}s in the future (max {MAX_ATTESTATION_FUTURE_SECONDS}s)"
        )
    if age > MAX_ATTESTATION_AGE_SECONDS:
        raise PagesGateError(
            f"attestation too old ({int(age)}s); re-run public pages-domain-attestation workflow "
            f"(max age {MAX_ATTESTATION_AGE_SECONDS}s)"
        )
    return moment


def validate_attestation_document(doc: dict[str, Any], *, expected_repo: str = DEFAULT_STATUS_REPO) -> None:
    if doc.get("version") != ATTESTATION_VERSION:
        raise PagesGateError(f"unsupported attestation version: {doc.get('version')!r}")
    if doc.get("github_repository") != expected_repo:
        raise PagesGateError(
            f"attestation repo {doc.get('github_repository')!r} != expected {expected_repo!r}"
        )
    attested_at = doc.get("attested_at")
    if not attested_at:
        raise PagesGateError("attestation missing attested_at")
    _validate_attested_at_freshness(str(attested_at))
    pages = doc.get("pages")
    if not isinstance(pages, dict):
        raise PagesGateError("attestation missing pages object")
    validate_pages_payload(pages)


def validate_attestation_commit_binding(doc: dict[str, Any], commit_entry: dict[str, Any]) -> None:
    """Bind attested_at to the latest github-actions commit that touched the file."""
    attested_at = _validate_attested_at_freshness(str(doc.get("attested_at") or ""))
    commit = commit_entry.get("commit")
    if not isinstance(commit, dict):
        raise PagesGateError("attestation commit metadata missing commit object")
    author_block = commit.get("author")
    if not isinstance(author_block, dict):
        raise PagesGateError("attestation commit missing author")
    login = str((commit_entry.get("author") or {}).get("login") or "")
    email = str(author_block.get("email") or "").lower()
    name = str(author_block.get("name") or "")
    if login != GITHUB_ACTIONS_BOT_LOGIN and email not in GITHUB_ACTIONS_BOT_EMAILS:
        raise PagesGateError(
            f"attestation commit author must be {GITHUB_ACTIONS_BOT_LOGIN!r}, "
            f"got login={login!r} email={email!r} name={name!r}"
        )
    commit_date_raw = author_block.get("date")
    if not commit_date_raw:
        raise PagesGateError("attestation commit missing author date")
    commit_moment = _parse_github_timestamp(str(commit_date_raw))
    now = datetime.now(tz=UTC)
    commit_age = (now - commit_moment).total_seconds()
    if commit_age < -MAX_ATTESTATION_FUTURE_SECONDS:
        raise PagesGateError("attestation commit date is in the future")
    if commit_age > MAX_ATTESTATION_AGE_SECONDS:
        raise PagesGateError(
            f"attestation commit is too old ({int(commit_age)}s); re-run pages-domain-attestation on public main"
        )
    drift = abs((commit_moment - attested_at).total_seconds())
    if drift > MAX_COMMIT_ATTESTATION_DRIFT_SECONDS:
        raise PagesGateError(
            f"attestation attested_at and commit date differ by {int(drift)}s "
            f"(max {MAX_COMMIT_ATTESTATION_DRIFT_SECONDS}s)"
        )


def github_api_get(path: str, *, token: str | None = None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "hydracept-status-pages-gate/1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PagesGateError(f"GitHub API {path} HTTP {exc.code}: {body[:400]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PagesGateError(f"GitHub API {path} failed: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PagesGateError(f"GitHub API {path} returned non-JSON body: {raw[:200]!r}") from exc


def fetch_pages_for_repo(repo: str, *, token: str) -> dict[str, Any]:
    if not token.strip():
        raise PagesGateError("GITHUB_TOKEN required to read Pages for this repository")
    payload = github_api_get(f"/repos/{repo}/pages", token=token)
    if not isinstance(payload, dict):
        raise PagesGateError("GitHub Pages API returned unexpected payload")
    return payload


def fetch_attestation_from_public_repo(
    repo: str = DEFAULT_STATUS_REPO,
    path: str = ATTESTATION_PATH,
    *,
    token: str | None = None,
) -> dict[str, Any]:
    """Read attestation JSON from a public repo (Contents API; no cross-repo Pages scope)."""
    payload = github_api_get(f"/repos/{repo}/contents/{path}", token=token)
    if isinstance(payload, list):
        raise PagesGateError(
            f"attestation path {path!r} is a directory listing; expected a single file object from Contents API"
        )
    if not isinstance(payload, dict):
        raise PagesGateError("attestation Contents API payload must be an object")
    if payload.get("type") not in {None, "file"}:
        raise PagesGateError(f"attestation path is not a file (type={payload.get('type')!r})")
    if payload.get("encoding") != "base64":
        raise PagesGateError("attestation content is not base64-encoded")
    raw = base64.b64decode(payload.get("content") or "")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PagesGateError(f"attestation JSON invalid: {exc}") from exc
    if not isinstance(doc, dict):
        raise PagesGateError("attestation root must be an object")
    return doc


def fetch_attestation_file_commit(
    repo: str = DEFAULT_STATUS_REPO,
    path: str = ATTESTATION_PATH,
    *,
    ref: str = ATTESTATION_REF,
    token: str | None = None,
) -> dict[str, Any]:
    quoted_path = urllib.parse.quote(path, safe="")
    quoted_ref = urllib.parse.quote(ref, safe="")
    commits = github_api_get(
        f"/repos/{repo}/commits?path={quoted_path}&sha={quoted_ref}&per_page=1",
        token=token,
    )
    if not isinstance(commits, list) or not commits:
        raise PagesGateError(f"no commit found for attestation file {path!r} on {ref!r}")
    entry = commits[0]
    if not isinstance(entry, dict):
        raise PagesGateError("commits API returned unexpected entry")
    return entry


def assert_pages_attestation_for_dns(
    *,
    repo: str | None = None,
    path: str | None = None,
    token: str | None = None,
) -> None:
    target = (repo or os.environ.get("HYDRACEPT_STATUS_GITHUB_REPO") or DEFAULT_STATUS_REPO).strip()
    att_path = (path or os.environ.get("HYDRACEPT_STATUS_PAGES_ATTESTATION_PATH") or ATTESTATION_PATH).strip()
    tok = (token if token is not None else (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "")).strip()
    auth_tok = tok or None
    doc = fetch_attestation_from_public_repo(target, att_path, token=auth_tok)
    commit_entry = fetch_attestation_file_commit(target, att_path, token=auth_tok)
    validate_attestation_document(doc, expected_repo=target)
    validate_attestation_commit_binding(doc, commit_entry)
