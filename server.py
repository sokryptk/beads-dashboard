#!/usr/bin/env python3
"""Local dashboard for the bd (beads) issue tracker.

    cd <any repo using bd>
    python3 ~/projects/beads-dashboard/server.py [--repo PATH] [--port 7766] [--no-open]

Serves a page on 127.0.0.1 that lists every pending issue and lets a person
reprioritise, defer, close, reopen, release, flag and delete them. Every
change runs the real `bd` CLI in the chosen folder, so the dashboard holds
no state of its own. The page can switch to any folder with a .beads dir. Python 3 standard library only.

Only this machine can reach it: the server binds to loopback, refuses foreign
Host headers (DNS rebinding) and requires a per-run token on every write.
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import secrets
import subprocess
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_REPO = pathlib.Path.cwd()
PAGE = pathlib.Path(__file__).with_name("index.html")
TOKEN = secrets.token_urlsafe(24)
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
UNTIL_RE = re.compile(r"^[A-Za-z0-9 +:._-]{1,40}$")
RECENT_DAYS = 3


class BdError(Exception):
    pass


def resolve_repo(raw):
    """Turn a folder typed in the page into a repo that holds a .beads dir."""
    if not raw:
        return DEFAULT_REPO
    if not isinstance(raw, str) or len(raw) > 1024 or "\0" in raw:
        raise BdError("bad folder")
    path = pathlib.Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise BdError(f"no such folder: {path}")
    if not (path / ".beads").is_dir():
        raise BdError(f"no .beads folder in {path}; run bd init there first")
    return path


def find_repos():
    """Folders with a .beads dir next to the default repo and in ~/projects."""
    found = {DEFAULT_REPO} if (DEFAULT_REPO / ".beads").is_dir() else set()
    for base in {DEFAULT_REPO.parent, pathlib.Path.home() / "projects"}:
        try:
            found.update(p for p in base.iterdir() if (p / ".beads").is_dir())
        except OSError:
            pass
    return sorted(str(p) for p in found)


def bd(repo, command, *args, parse=True):
    # --json goes before args so a trailing "--" cannot swallow it.
    proc = subprocess.run(
        ["bd", command, "--json", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = proc.stdout.strip()
    data = None
    if out:
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict) and data.get("error"):
        raise BdError(data["error"])
    if proc.returncode != 0:
        raise BdError((proc.stderr or out or "bd failed").strip())
    return data if parse else out


def ids_from(body):
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise BdError("no issues selected")
    for i in ids:
        if not isinstance(i, str) or not ID_RE.match(i):
            raise BdError(f"bad issue id: {i!r}")
    return ids


def text_from(body, key, limit=2000):
    value = body.get(key) or ""
    if not isinstance(value, str) or len(value) > limit:
        raise BdError(f"bad {key}")
    return value.strip()


def snapshot(repo):
    # Two bd calls: each takes a database lock, so fewer calls is faster.
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECENT_DAYS)
    every = bd(repo, "list", "--flat", "--limit", "0", "--all") or []
    blocked = bd(repo, "blocked") or []
    blocked_by = {b["id"]: b.get("blocked_by") or [] for b in blocked}
    issues = []
    for issue in every:
        if issue.get("status") == "closed":
            closed_at = issue.get("closed_at") or issue.get("updated_at") or ""
            try:
                if dt.datetime.fromisoformat(closed_at.replace("Z", "+00:00")) < cutoff:
                    continue
            except ValueError:
                continue
        issue["blocked_by"] = blocked_by.get(issue["id"], [])
        issue["ready"] = issue.get("status") == "open" and not issue["blocked_by"]
        issues.append(issue)
    return {
        "repo": str(repo),
        "issues": issues,
        "recent_days": RECENT_DAYS,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def act(body):
    repo = resolve_repo(body.get("repo"))
    op = body.get("op")
    ids = ids_from(body)
    if op == "delete_preview":
        # Without --force bd only previews; an error names the dependents.
        try:
            return {"preview": bd(repo, "delete", *ids, "--dry-run")}
        except BdError as e:
            return {"preview": None, "warning": str(e)}
    if op == "delete":
        args = ["delete", *ids, "--force"]
        if body.get("cascade"):
            args.append("--cascade")
        return bd(repo, *args)
    if op == "close":
        reason = text_from(body, "reason") or "Closed from the dashboard"
        return bd(repo, "close", *ids, "--reason", reason)
    if op == "reopen":
        return bd(repo, "reopen", *ids)
    if op == "priority":
        p = body.get("priority")
        if p not in (0, 1, 2, 3, 4):
            raise BdError("priority must be 0-4")
        return bd(repo, "update", *ids, "--priority", str(p))
    if op == "defer":
        args = ["defer", *ids]
        until = text_from(body, "until", 40)
        if until:
            if not UNTIL_RE.match(until):
                raise BdError("bad defer date")
            args += ["--until", until]
        return bd(repo, *args)
    if op == "status":
        status = body.get("status")
        if status not in ("open", "in_progress"):
            raise BdError("status must be open or in_progress")
        return bd(repo, "update", *ids, "--status", status)
    if op == "undefer":
        return bd(repo, "undefer", *ids)
    if op == "unclaim":
        return bd(repo, "unclaim", *ids, "--force")
    if op == "flag_human":
        return bd(repo, "update", *ids, "--add-label", "human")
    if op == "unflag_human":
        return bd(repo, "update", *ids, "--remove-label", "human")
    if op == "comment":
        text = text_from(body, "text", 8000)
        if not text or len(ids) != 1:
            raise BdError("a comment needs text and one issue")
        return bd(repo, "comment", ids[0], "--", text)
    raise BdError(f"unknown action: {op!r}")


class Handler(BaseHTTPRequestHandler):
    server_version = "beads-dashboard"

    def log_message(self, fmt, *args):
        if self.command != "GET":
            sys.stderr.write("%s %s\n" % (self.command, fmt % args))

    def host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "forbidden host"})
        url = urlparse(self.path)
        try:
            if url.path == "/":
                html = PAGE.read_text().replace("__TOKEN__", TOKEN)
                return self.send(200, html.encode(), "text/html; charset=utf-8")
            query = parse_qs(url.query)
            if url.path == "/api/repos":
                return self.send(200, {"default": str(DEFAULT_REPO), "found": find_repos()})
            if url.path == "/api/issues":
                return self.send(200, snapshot(resolve_repo(query.get("repo", [""])[0])))
            if url.path == "/api/issue":
                repo = resolve_repo(query.get("repo", [""])[0])
                issue_id = query.get("id", [""])[0]
                if not ID_RE.match(issue_id):
                    raise BdError("bad issue id")
                shown = bd(repo, "show", issue_id, "--include-comments")
                return self.send(200, shown[0] if shown else {})
        except BdError as e:
            return self.send(400, {"error": str(e)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.host_ok() or self.headers.get("X-Dashboard-Token") != TOKEN:
            return self.send(403, {"error": "forbidden"})
        if urlparse(self.path).path != "/api/action":
            return self.send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(length, 65536)) or b"{}")
            return self.send(200, {"ok": True, "result": act(body)})
        except (BdError, ValueError) as e:
            return self.send(400, {"error": str(e)})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="folder opened first (default: cwd); the page can switch")
    parser.add_argument("--port", type=int, default=7766)
    parser.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = parser.parse_args()
    global DEFAULT_REPO
    DEFAULT_REPO = pathlib.Path(args.repo).expanduser().resolve()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"beads dashboard for {DEFAULT_REPO} on {url}  (Ctrl+C to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
