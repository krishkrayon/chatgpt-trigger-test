"""
Phase A + B — SMA Review Loop: comment validation.

Reads the GitHub event JSON from GITHUB_EVENT_PATH, validates
SMA_REVIEW_COMPLETED protocol fields, and:
  - Logs ACCEPT or REJECT with reason (stdout)
  - Writes validated metadata to GITHUB_OUTPUT (no free-form text)
  - On ACCEPT+CHANGES_REQUESTED: writes bounded context JSON to
    $RUNNER_TEMP/sma-context.json for inter-job artifact transfer

No shell interpolation of comment data; no execution of content from comments.
Findings and Recommendations are treated as untrusted free-form text,
bounded to 500 chars each, and only stored in the JSON artifact — never in
GITHUB_OUTPUT or shell variables.

Exit codes: 0 always (rejection is logged cleanly; never fails the job).
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error


EXPECTED_REPO = "krishkrayon/chatgpt-trigger-test"
SELF_TRIGGER_LOGIN = "krish7-dev"
ALLOWED_STATUSES = {"ACCEPTED", "CHANGES_REQUESTED", "UNRESOLVABLE"}
PLAN_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-_]{2,63}$')
SHA_RE = re.compile(r'^[0-9a-f]{40}$', re.IGNORECASE)
MAX_FEEDBACK_CHARS = 500


def _safe_str(v, max_len=80):
    return str(v)[:max_len].replace('\n', ' ').replace('\r', ' ')


def write_github_output(**fields):
    """Write validated metadata fields to GITHUB_OUTPUT. No free-form text."""
    path = os.environ.get("GITHUB_OUTPUT", "")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in fields.items():
            f.write(f"{k}={v}\n")


def write_context_artifact(plan_id, round_n, head_sha, status, findings, recommendations):
    """
    Write bounded review context JSON to $RUNNER_TEMP/sma-context.json.
    Findings and recommendations are stored here only — not in GITHUB_OUTPUT.
    Bounded to MAX_FEEDBACK_CHARS each to limit injection surface.
    """
    dest_dir = os.environ.get("RUNNER_TEMP", "/tmp")
    dest = os.path.join(dest_dir, "sma-context.json")
    context = {
        "plan_id": plan_id,
        "round": round_n,
        "head_sha": head_sha,
        "status": status,
        "findings": (findings or "none")[:MAX_FEEDBACK_CHARS],
        "recommendations": (recommendations or "none")[:MAX_FEEDBACK_CHARS],
    }
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=True, indent=2)
    print(f"Context artifact written: {dest}", flush=True)
    return dest


def log_reject(reason, **ctx):
    print(f"RESULT=REJECT reason={reason!r}", flush=True)
    for k, v in ctx.items():
        print(f"  {k}={_safe_str(v)}", flush=True)
    write_github_output(accepted="false")
    sys.exit(0)


def log_accept(plan_id, round_n, actual_sha, status, commenter):
    print("RESULT=ACCEPT", flush=True)
    for k, v in [("plan_id", plan_id), ("round", round_n), ("sha", actual_sha[:12]),
                 ("status", status), ("commenter", commenter),
                 ("reviewer_identity", "UNVERIFIED")]:
        print(f"  {k}={_safe_str(v)}", flush=True)


def parse_protocol_field(body, field_name, value_pattern=r'\S+'):
    """
    Extract a value from a line exactly matching "Field-Name: value".
    Returns None if absent or if the field appears more than once.
    Never evaluates the value.
    """
    pattern = rf'^{re.escape(field_name)}:\s*({value_pattern})\s*$'
    matches = re.findall(pattern, body, re.MULTILINE)
    if len(matches) == 1:
        return matches[0].strip()
    return None


def parse_feedback_field(body, field_name):
    """
    Extract a single-line free-form field value.
    Returns None if absent or duplicated; "none" if value is blank.
    Bounded to MAX_FEEDBACK_CHARS before storage.
    """
    # Match any non-empty content on the same line as the field name.
    pattern = rf'^{re.escape(field_name)}:\s*([^\r\n]+)'
    matches = re.findall(pattern, body, re.MULTILINE)
    if len(matches) == 1:
        return matches[0].strip()[:MAX_FEEDBACK_CHARS] or "none"
    return "none"


def main():
    # 1. Load event JSON from disk (never from shell env interpolation)
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        log_reject("GITHUB_EVENT_PATH not set")

    try:
        with open(event_path, encoding="utf-8") as f:
            event = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log_reject("cannot load event JSON", error=str(e))

    # 2. Correct repository
    repo = event.get("repository", {}).get("full_name", "")
    if repo != EXPECTED_REPO:
        log_reject("wrong repository", repo=repo)

    # 3. Must be a PR comment (issue.pull_request is present for PR comments)
    issue = event.get("issue", {})
    if not issue.get("pull_request"):
        log_reject("not a PR comment", issue_number=issue.get("number", "?"))

    pr_number = issue.get("number")
    if not isinstance(pr_number, int):
        log_reject("issue.number missing or not an integer")

    # 4. Reject self-trigger
    commenter = event.get("comment", {}).get("user", {}).get("login", "")
    if commenter == SELF_TRIGGER_LOGIN:
        log_reject("self-comment rejected", commenter=commenter, pr=pr_number)

    # 5. Extract comment body — never interpolated into shell
    body = event.get("comment", {}).get("body", "")
    if not isinstance(body, str):
        log_reject("comment body is not a string", pr=pr_number)

    # 6. Marker must appear as its own line
    lines = [line.strip() for line in body.splitlines()]
    if "SMA_REVIEW_COMPLETED" not in lines:
        log_reject("SMA_REVIEW_COMPLETED marker absent or not on its own line", pr=pr_number)

    # 7. Parse all required structured fields
    plan_id  = parse_protocol_field(body, "Plan-ID")
    round_s  = parse_protocol_field(body, "Round", r'\d+')
    pr_field = parse_protocol_field(body, "PR", r'\d+')
    head_sha = parse_protocol_field(body, "Head-SHA", r'[0-9a-fA-F]{40}')
    status   = parse_protocol_field(body, "Status", r'[A-Z_]+')

    missing = [name for name, val in [
        ("Plan-ID", plan_id), ("Round", round_s), ("PR", pr_field),
        ("Head-SHA", head_sha), ("Status", status)
    ] if val is None]

    if missing:
        log_reject(f"missing or duplicate protocol fields: {missing}", pr=pr_number)

    # 8. Plan-ID format
    if not PLAN_ID_RE.match(plan_id):
        log_reject("Plan-ID format invalid", plan_id=plan_id[:40], pr=pr_number)

    # 9. Round in valid range
    try:
        round_n = int(round_s)
    except ValueError:
        log_reject("Round is not an integer", round_raw=round_s, pr=pr_number)
    if not (1 <= round_n <= 3):
        log_reject("Round out of range 1-3", round=round_n, pr=pr_number)

    # 10. PR field matches event PR number
    if int(pr_field) != pr_number:
        log_reject("PR field mismatch", pr_field=pr_field, event_pr=pr_number)

    # 11. Head-SHA format
    if not SHA_RE.match(head_sha):
        log_reject("Head-SHA format invalid", head_sha=head_sha[:12], pr=pr_number)

    # 12. Status must be an allowed value
    if status not in ALLOWED_STATUSES:
        log_reject("Status not in allowed set", status=status, pr=pr_number)

    # 13. Fetch current PR head SHA via read-only API call (not from comment text)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        log_reject("GITHUB_TOKEN not available", pr=pr_number)

    api_url = f"https://api.github.com/repos/{EXPECTED_REPO}/pulls/{pr_number}"
    req = urllib.request.Request(
        api_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "sma-review-loop-phase-ab/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            pr_data = json.load(resp)
    except urllib.error.HTTPError as e:
        log_reject("PR API call failed", http_status=e.code, pr=pr_number)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        log_reject("PR API call error", error=str(e)[:80], pr=pr_number)

    actual_sha = pr_data.get("head", {}).get("sha", "")
    if not actual_sha:
        log_reject("could not retrieve PR head SHA from API", pr=pr_number)

    # Fork guard — reject PRs from forks not owned by krishkrayon
    fork_owner = pr_data.get("head", {}).get("repo", {}).get("owner", {}).get("login", "")
    if fork_owner != "krishkrayon":
        log_reject("fork PR rejected", fork_owner=fork_owner[:40], pr=pr_number)

    head_ref = pr_data.get("head", {}).get("ref", "")

    if head_sha.lower() != actual_sha.lower():
        log_reject(
            "Head-SHA mismatch",
            comment_sha=head_sha[:12],
            actual_sha=actual_sha[:12],
            pr=pr_number,
        )

    # All guards passed — write structured outputs (no free-form text in outputs)
    write_github_output(
        accepted="true",
        plan_id=plan_id,
        round=str(round_n),
        head_sha=actual_sha,
        head_ref=head_ref,
        status=status,
    )
    log_accept(plan_id, round_n, actual_sha, status, commenter)

    # Write context artifact only when Phase B will run (CHANGES_REQUESTED, round < 3)
    if status == "CHANGES_REQUESTED" and round_n < 3:
        findings = parse_feedback_field(body, "Findings")
        recommendations = parse_feedback_field(body, "Recommendations")
        write_context_artifact(plan_id, round_n, actual_sha, status, findings, recommendations)


if __name__ == "__main__":
    main()
