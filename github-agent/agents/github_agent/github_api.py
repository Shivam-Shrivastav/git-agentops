from __future__ import annotations

import base64
from typing import Any

import requests


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns an error response."""


class GitHubClient:
    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "local-github-agent",
            }
        )
        # Last response metadata, exposed for tool-span observability.
        self.last_status: int | None = None
        self.last_size_bytes: int | None = None

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method=method, url=f"{self.base_url}{path}", timeout=60, **kwargs)
        self.last_status = response.status_code
        self.last_size_bytes = len(response.content or b"")
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            raise GitHubAPIError(f"{method} {path} failed with {response.status_code}: {payload}")

        if response.status_code == 204:
            return {"ok": True}
        if not response.content:
            return {"ok": True}
        return response.json()

    def _request_text(self, method: str, path: str, **kwargs: Any) -> str:
        response = self.session.request(method=method, url=f"{self.base_url}{path}", timeout=60, **kwargs)
        self.last_status = response.status_code
        self.last_size_bytes = len(response.content or b"")
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            raise GitHubAPIError(f"{method} {path} failed with {response.status_code}: {payload}")
        return response.text

    def _clean_params(self, values: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in values.items() if value is not None and value != ""}

    def _clean_body(self, values: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in values.items() if value is not None}

    def get_user(self) -> Any:
        return self._request("GET", "/user")

    def list_user_repos(
        self,
        visibility: str | None = None,
        affiliation: str | None = None,
        per_page: int | None = None,
        page: int | None = None,
        sort: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {}
        if visibility:
            params["visibility"] = visibility
        if affiliation:
            params["affiliation"] = affiliation
        if per_page is not None:
            params["per_page"] = per_page
        if page is not None:
            params["page"] = page
        if sort:
            params["sort"] = sort
        return self._request("GET", "/user/repos", params=params)

    def create_user_repo(
        self,
        name: str,
        description: str = "",
        private: bool = True,
        auto_init: bool = True,
    ) -> Any:
        return self._request(
            "POST",
            "/user/repos",
            json={
                "name": name,
                "description": description,
                "private": private,
                "auto_init": auto_init,
            },
        )

    def create_org_repo(
        self,
        org: str,
        name: str,
        description: str = "",
        private: bool = True,
        auto_init: bool = True,
    ) -> Any:
        return self._request(
            "POST",
            f"/orgs/{org}/repos",
            json={
                "name": name,
                "description": description,
                "private": private,
                "auto_init": auto_init,
            },
        )

    def create_fork(
        self,
        owner: str,
        repo: str,
        organization: str | None = None,
        name: str | None = None,
        default_branch_only: bool | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "organization": organization,
                "name": name,
                "default_branch_only": default_branch_only,
            }
        )
        return self._request("POST", f"/repos/{owner}/{repo}/forks", json=body_payload)

    def get_repo(self, owner: str, repo: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}")

    def get_contents(self, owner: str, repo: str, path: str, ref: str | None = None) -> Any:
        params = {"ref": ref} if ref else None
        payload = self._request("GET", f"/repos/{owner}/{repo}/contents/{path}", params=params)
        if isinstance(payload, dict) and payload.get("type") == "file" and payload.get("encoding") == "base64":
            content = payload.get("content", "")
            payload["decoded_content"] = base64.b64decode(content).decode("utf-8", errors="replace")
        return payload

    def put_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str | None = None,
        sha: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        }
        if branch:
            body["branch"] = branch
        if sha:
            body["sha"] = sha
        return self._request("PUT", f"/repos/{owner}/{repo}/contents/{path}", json=body)

    def list_branches(self, owner: str, repo: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/branches")

    def get_branch(self, owner: str, repo: str, branch: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/branches/{branch}")

    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str | None = None,
        labels: str | None = None,
        assignee: str | None = None,
        creator: str | None = None,
        mentioned: str | None = None,
        since: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params(
            {
                "state": state,
                "labels": labels,
                "assignee": assignee,
                "creator": creator,
                "mentioned": mentioned,
                "since": since,
                "per_page": per_page,
                "page": page,
            }
        )
        return self._request("GET", f"/repos/{owner}/{repo}/issues", params=params)

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "title": title,
                "body": body,
                "labels": labels,
                "assignees": assignees,
                "milestone": milestone,
            }
        )
        return self._request("POST", f"/repos/{owner}/{repo}/issues", json=body_payload)

    def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        state_reason: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "title": title,
                "body": body,
                "state": state,
                "state_reason": state_reason,
                "labels": labels,
                "assignees": assignees,
                "milestone": milestone,
            }
        )
        return self._request("PATCH", f"/repos/{owner}/{repo}/issues/{issue_number}", json=body_payload)

    def set_issue_state(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        state: str,
        state_reason: str | None = None,
    ) -> Any:
        return self.update_issue(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            state=state,
            state_reason=state_reason,
        )

    def add_issue_labels(self, owner: str, repo: str, issue_number: int, labels: list[str]) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )

    def add_issue_assignees(self, owner: str, repo: str, issue_number: int, assignees: list[str]) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/assignees",
            json={"assignees": assignees},
        )

    def create_issue_comment(self, owner: str, repo: str, issue_number: int, body: str) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )

    def list_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str | None = None,
        head: str | None = None,
        base: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params(
            {
                "state": state,
                "head": head,
                "base": base,
                "sort": sort,
                "direction": direction,
                "per_page": per_page,
                "page": page,
            }
        )
        return self._request("GET", f"/repos/{owner}/{repo}/pulls", params=params)

    def get_pull_request(self, owner: str, repo: str, pull_number: int) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}")

    def get_pull_request_diff(self, owner: str, repo: str, pull_number: int) -> Any:
        content = self._request_text(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return {"media_type": "diff", "content": content}

    def get_pull_request_patch(self, owner: str, repo: str, pull_number: int) -> Any:
        content = self._request_text(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            headers={"Accept": "application/vnd.github.v3.patch"},
        )
        return {"media_type": "patch", "content": content}

    def list_pull_request_files(self, owner: str, repo: str, pull_number: int) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{pull_number}/files")

    def update_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        title: str | None = None,
        body: str | None = None,
        base: str | None = None,
        state: str | None = None,
        maintainer_can_modify: bool | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "title": title,
                "body": body,
                "base": base,
                "state": state,
                "maintainer_can_modify": maintainer_can_modify,
            }
        )
        return self._request("PATCH", f"/repos/{owner}/{repo}/pulls/{pull_number}", json=body_payload)

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )

    def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        commit_title: str | None = None,
        commit_message: str | None = None,
        sha: str | None = None,
        merge_method: str | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "commit_title": commit_title,
                "commit_message": commit_message,
                "sha": sha,
                "merge_method": merge_method,
            }
        )
        return self._request("PUT", f"/repos/{owner}/{repo}/pulls/{pull_number}/merge", json=body_payload)

    def request_pull_request_reviewers(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "reviewers": reviewers,
                "team_reviewers": team_reviewers,
            }
        )
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/requested_reviewers",
            json=body_payload,
        )

    def create_pull_request_review(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
        event: str = "COMMENT",
    ) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            json={
                "body": body,
                "event": event,
            },
        )

    def create_pull_request_review_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
        start_line: int | None = None,
        start_side: str | None = None,
    ) -> Any:
        body_payload = self._clean_body(
            {
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
                "start_line": start_line,
                "start_side": start_side,
            }
        )
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/comments",
            json=body_payload,
        )

    def reply_to_pull_request_review_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        comment_id: int,
        body: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pull_number}/comments/{comment_id}/replies",
            json={"body": body},
        )

    def get_check_runs(self, owner: str, repo: str, ref: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/commits/{ref}/check-runs")

    def list_actions_runs(self, owner: str, repo: str, branch: str | None = None, per_page: int = 10) -> Any:
        params: dict[str, Any] = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        return self._request("GET", f"/repos/{owner}/{repo}/actions/runs", params=params)

    def search_code(self, query: str, per_page: int = 10) -> Any:
        return self._request("GET", "/search/code", params={"q": query, "per_page": per_page})

    def search_repositories(
        self,
        query: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params({"q": query, "sort": sort, "order": order, "per_page": per_page, "page": page})
        return self._request("GET", "/search/repositories", params=params)

    def search_issues(
        self,
        query: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params({"q": query, "sort": sort, "order": order, "per_page": per_page, "page": page})
        return self._request("GET", "/search/issues", params=params)

    def search_commits(
        self,
        query: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params({"q": query, "sort": sort, "order": order, "per_page": per_page, "page": page})
        return self._request("GET", "/search/commits", params=params)

    def search_users(
        self,
        query: str,
        sort: str | None = None,
        order: str | None = None,
        per_page: int = 10,
        page: int | None = None,
    ) -> Any:
        params = self._clean_params({"q": query, "sort": sort, "order": order, "per_page": per_page, "page": page})
        return self._request("GET", "/search/users", params=params)

    def get_git_ref(self, owner: str, repo: str, ref: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/git/ref/{ref}")

    def create_git_ref(self, owner: str, repo: str, ref: str, sha: str) -> Any:
        return self._request("POST", f"/repos/{owner}/{repo}/git/refs", json={"ref": ref, "sha": sha})

    def update_git_ref(self, owner: str, repo: str, ref: str, sha: str, force: bool = False) -> Any:
        return self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/git/refs/{ref}",
            json={"sha": sha, "force": force},
        )

    def create_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
        from_branch: str | None = None,
        from_sha: str | None = None,
    ) -> Any:
        if not from_sha:
            source_branch = from_branch
            if not source_branch:
                repository = self.get_repo(owner, repo)
                source_branch = repository["default_branch"]
            source_ref = self.get_git_ref(owner, repo, f"heads/{source_branch}")
            from_sha = source_ref["object"]["sha"]
        return self.create_git_ref(owner, repo, f"refs/heads/{branch}", from_sha)

    def get_git_commit(self, owner: str, repo: str, commit_sha: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/git/commits/{commit_sha}")

    def create_git_blob(self, owner: str, repo: str, content: str, encoding: str = "utf-8") -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/blobs",
            json={"content": content, "encoding": encoding},
        )

    def create_git_tree(
        self,
        owner: str,
        repo: str,
        tree: list[dict[str, Any]],
        base_tree: str | None = None,
    ) -> Any:
        body_payload = {"tree": tree}
        if base_tree:
            body_payload["base_tree"] = base_tree
        return self._request("POST", f"/repos/{owner}/{repo}/git/trees", json=body_payload)

    def create_git_commit(
        self,
        owner: str,
        repo: str,
        message: str,
        tree: str,
        parents: list[str],
    ) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/commits",
            json={"message": message, "tree": tree, "parents": parents},
        )

    def create_multi_file_commit(
        self,
        owner: str,
        repo: str,
        branch: str,
        message: str,
        files: list[dict[str, Any]],
        base_branch: str | None = None,
        create_branch: bool = True,
    ) -> Any:
        if base_branch:
            source_branch = base_branch
        elif create_branch:
            repository = self.get_repo(owner, repo)
            source_branch = repository["default_branch"]
        else:
            source_branch = branch
        source_ref = self.get_git_ref(owner, repo, f"heads/{source_branch}")
        parent_sha = source_ref["object"]["sha"]

        target_ref = f"heads/{branch}"
        if create_branch and branch != source_branch:
            self.create_git_ref(owner, repo, f"refs/{target_ref}", parent_sha)
        elif branch != source_branch:
            target_branch_ref = self.get_git_ref(owner, repo, target_ref)
            parent_sha = target_branch_ref["object"]["sha"]

        parent_commit = self.get_git_commit(owner, repo, parent_sha)
        base_tree = parent_commit["tree"]["sha"]

        tree_entries: list[dict[str, Any]] = []
        for file_change in files:
            path = file_change["path"]
            content = file_change.get("content")
            mode = file_change.get("mode", "100644")
            file_type = file_change.get("type", "blob")
            if content is None:
                tree_entries.append({"path": path, "mode": mode, "type": file_type, "sha": None})
                continue
            blob = self.create_git_blob(owner, repo, str(content), file_change.get("encoding", "utf-8"))
            tree_entries.append({"path": path, "mode": mode, "type": file_type, "sha": blob["sha"]})

        new_tree = self.create_git_tree(owner, repo, tree_entries, base_tree=base_tree)
        new_commit = self.create_git_commit(owner, repo, message, new_tree["sha"], [parent_sha])
        updated_ref = self.update_git_ref(owner, repo, target_ref, new_commit["sha"])
        return {
            "branch": branch,
            "base_branch": source_branch,
            "commit": new_commit,
            "ref": updated_ref,
            "files_changed": len(files),
        }

    def get_rate_limit(self) -> Any:
        return self._request("GET", "/rate_limit")
