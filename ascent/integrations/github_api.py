from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class GitHubAPIError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"GitHub API {status} on {url}: {body}")
        self.status = status
        self.body = body
        self.url = url


class GitHubClient:
    def __init__(self, token: str, repo: str, api_url: str | None = None):
        self.token = token
        self.repo = repo
        self.api_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")

    def create_check_run(
        self,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        title: str,
        summary: str,
        text: str,
        annotations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": {
                "title": title,
                "summary": summary,
                "text": text,
            },
        }
        if annotations:
            payload["output"]["annotations"] = annotations
        return self._request("POST", f"/repos/{self.repo}/check-runs", payload)

    def upsert_pr_comment(self, *, pr_number: int, marker: str, body: str) -> dict[str, Any]:
        existing = self._find_existing_comment(pr_number, marker)
        if existing is not None:
            return self._request(
                "PATCH",
                f"/repos/{self.repo}/issues/comments/{existing['id']}",
                {"body": body},
            )
        return self._request(
            "POST",
            f"/repos/{self.repo}/issues/{pr_number}/comments",
            {"body": body},
        )

    def _find_existing_comment(self, pr_number: int, marker: str) -> dict[str, Any] | None:
        path = f"/repos/{self.repo}/issues/{pr_number}/comments?per_page=100"
        comments = self._request("GET", path, None)
        if not isinstance(comments, list):
            return None
        for comment in comments:
            if isinstance(comment, dict) and marker in (comment.get("body") or ""):
                return comment
        return None

    def _request(self, method: str, path: str, body: Any) -> Any:
        url = f"{self.api_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "ascent/0.2",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise GitHubAPIError(err.code, err_body, url) from None
        if not raw:
            return {}
        return json.loads(raw)
