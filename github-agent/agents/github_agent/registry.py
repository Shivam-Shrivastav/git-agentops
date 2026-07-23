from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_]+", text.lower()) if len(token) > 1}


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    name: str
    description: str
    required: dict[str, type]
    optional: dict[str, type] = field(default_factory=dict)
    keywords: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()

    def argument_shape(self) -> dict[str, str]:
        shape: dict[str, str] = {}
        for key, value in self.required.items():
            shape[key] = value.__name__
        for key, value in self.optional.items():
            shape[key] = f"{value.__name__} optional"
        return shape

    def searchable_text(self) -> str:
        parts = [
            self.name,
            self.description,
            " ".join(self.keywords),
            " ".join(self.examples),
            " ".join(self.required.keys()),
            " ".join(self.optional.keys()),
        ]
        return " ".join(parts)


ACTION_REGISTRY: dict[str, ActionDefinition] = {
    "get_user": ActionDefinition(
        name="get_user",
        description="Get the authenticated GitHub user profile.",
        required={},
        keywords=("whoami", "profile", "user", "account", "me"),
        examples=("who am i on github", "show my github user"),
    ),
    "list_user_repos": ActionDefinition(
        name="list_user_repos",
        description="List repositories accessible to the authenticated user.",
        required={},
        optional={"visibility": str, "affiliation": str, "per_page": int, "page": int, "sort": str},
        keywords=("repos", "repositories", "my repos", "owned repos", "accessible repos", "top repos", "list repos"),
        examples=("list my repos", "show my repositories", "top 5 repos of mine"),
    ),
    "create_user_repo": ActionDefinition(
        name="create_user_repo",
        description="Create a repository under the authenticated user's account.",
        required={"name": str},
        optional={"description": str, "private": bool, "auto_init": bool},
        keywords=("create repo", "new repo", "make repository", "personal repository"),
        examples=("create a private repo named sandbox",),
    ),
    "create_org_repo": ActionDefinition(
        name="create_org_repo",
        description="Create a repository inside a GitHub organization.",
        required={"org": str, "name": str},
        optional={"description": str, "private": bool, "auto_init": bool},
        keywords=("organization repo", "org repo", "create repo in org"),
        examples=("create repo demo in org acme",),
    ),
    "create_fork": ActionDefinition(
        name="create_fork",
        description="Fork a repository into the authenticated user's account or a specified organization.",
        required={"owner": str, "repo": str},
        optional={"organization": str, "name": str, "default_branch_only": bool},
        keywords=("fork", "fork repo", "fork repository", "create fork", "copy repo to my account"),
        examples=("fork octocat hello-world", "fork owner/repo into my account", "fork owner/repo into org acme"),
    ),
    "get_repo": ActionDefinition(
        name="get_repo",
        description="Get repository metadata for owner/repo.",
        required={"owner": str, "repo": str},
        keywords=("repo exists", "repository details", "check repo", "repository metadata", "owner repo"),
        examples=("does octocat hello-world exist", "inspect repo owner/repo"),
    ),
    "get_contents": ActionDefinition(
        name="get_contents",
        description="Get a file or directory listing from a repository path.",
        required={"owner": str, "repo": str, "path": str},
        optional={"ref": str},
        keywords=("files", "contents", "read file", "directory", "root files", "list files"),
        examples=("what files are in that repo", "read README.md from owner/repo"),
    ),
    "put_contents": ActionDefinition(
        name="put_contents",
        description="Create or update a single file in a repository.",
        required={"owner": str, "repo": str, "path": str, "content": str, "message": str},
        optional={"branch": str, "sha": str},
        keywords=("update file", "create file", "edit file", "write file", "commit file"),
        examples=("update README.md in owner/repo",),
    ),
    "list_branches": ActionDefinition(
        name="list_branches",
        description="List branches in a repository.",
        required={"owner": str, "repo": str},
        keywords=("branches", "list branches", "default branch"),
        examples=("show branches in owner/repo",),
    ),
    "get_branch": ActionDefinition(
        name="get_branch",
        description="Get metadata for a branch in a repository.",
        required={"owner": str, "repo": str, "branch": str},
        keywords=("branch details", "branch sha", "branch commit", "inspect branch"),
        examples=("show main branch details in owner/repo",),
    ),
    "list_issues": ActionDefinition(
        name="list_issues",
        description="List issues in a repository.",
        required={"owner": str, "repo": str},
        optional={
            "state": str,
            "labels": str,
            "assignee": str,
            "creator": str,
            "mentioned": str,
            "since": str,
            "per_page": int,
            "page": int,
        },
        keywords=("issues", "list issues", "open issues", "closed issues", "bugs", "tickets"),
        examples=("list open issues in owner/repo", "show issues labeled bug in owner/repo"),
    ),
    "create_issue": ActionDefinition(
        name="create_issue",
        description="Create an issue in a repository.",
        required={"owner": str, "repo": str, "title": str},
        optional={"body": str, "labels": list, "assignees": list, "milestone": int},
        keywords=("create issue", "open issue", "file issue", "new ticket", "bug report"),
        examples=("create an issue titled fix login bug in owner/repo",),
    ),
    "update_issue": ActionDefinition(
        name="update_issue",
        description="Update an issue title, body, state, labels, assignees, or milestone.",
        required={"owner": str, "repo": str, "issue_number": int},
        optional={
            "title": str,
            "body": str,
            "state": str,
            "state_reason": str,
            "labels": list,
            "assignees": list,
            "milestone": int,
        },
        keywords=("update issue", "edit issue", "close issue", "reopen issue", "change issue"),
        examples=("close issue 12 in owner/repo", "update issue 4 title in owner/repo"),
    ),
    "set_issue_state": ActionDefinition(
        name="set_issue_state",
        description="Open or close an issue by setting its state.",
        required={"owner": str, "repo": str, "issue_number": int, "state": str},
        optional={"state_reason": str},
        keywords=("close issue", "reopen issue", "open issue", "set issue state", "resolve issue"),
        examples=("close issue 12 in owner/repo", "reopen issue 12 in owner/repo"),
    ),
    "add_issue_labels": ActionDefinition(
        name="add_issue_labels",
        description="Add labels to an issue.",
        required={"owner": str, "repo": str, "issue_number": int, "labels": list},
        keywords=("add labels", "label issue", "tag issue", "issue labels"),
        examples=("add labels bug and priority-high to issue 12 in owner/repo",),
    ),
    "add_issue_assignees": ActionDefinition(
        name="add_issue_assignees",
        description="Add assignees to an issue.",
        required={"owner": str, "repo": str, "issue_number": int, "assignees": list},
        keywords=("assign issue", "add assignees", "issue assignee", "take issue"),
        examples=("assign issue 12 in owner/repo to octocat",),
    ),
    "create_issue_comment": ActionDefinition(
        name="create_issue_comment",
        description="Post a comment on a GitHub issue.",
        required={"owner": str, "repo": str, "issue_number": int, "body": str},
        keywords=("issue comment", "comment on issue", "reply issue"),
        examples=("comment on issue 12 in owner/repo",),
    ),
    "list_pull_requests": ActionDefinition(
        name="list_pull_requests",
        description="List pull requests in a repository.",
        required={"owner": str, "repo": str},
        optional={"state": str, "head": str, "base": str, "sort": str, "direction": str, "per_page": int, "page": int},
        keywords=("pull requests", "prs", "list prs", "open prs", "closed prs"),
        examples=("list open PRs in owner/repo", "show pull requests targeting main"),
    ),
    "get_pull_request": ActionDefinition(
        name="get_pull_request",
        description="Get pull request metadata for owner/repo and pull number.",
        required={"owner": str, "repo": str, "pull_number": int},
        keywords=("pull request", "pr details", "review pr", "inspect pr"),
        examples=("show PR 42 in owner/repo",),
    ),
    "get_pull_request_diff": ActionDefinition(
        name="get_pull_request_diff",
        description="Get a pull request as a unified diff.",
        required={"owner": str, "repo": str, "pull_number": int},
        keywords=("pr diff", "pull request diff", "unified diff", "show diff"),
        examples=("get the diff for PR 42 in owner/repo",),
    ),
    "get_pull_request_patch": ActionDefinition(
        name="get_pull_request_patch",
        description="Get a pull request as a patch.",
        required={"owner": str, "repo": str, "pull_number": int},
        keywords=("pr patch", "pull request patch", "show patch"),
        examples=("get the patch for PR 42 in owner/repo",),
    ),
    "list_pull_request_files": ActionDefinition(
        name="list_pull_request_files",
        description="List changed files in a pull request.",
        required={"owner": str, "repo": str, "pull_number": int},
        keywords=("pr files", "changed files", "diff files", "files in pull request"),
        examples=("what files changed in PR 42",),
    ),
    "update_pull_request": ActionDefinition(
        name="update_pull_request",
        description="Update pull request title, body, base branch, state, or maintainer modification setting.",
        required={"owner": str, "repo": str, "pull_number": int},
        optional={"title": str, "body": str, "base": str, "state": str, "maintainer_can_modify": bool},
        keywords=("update pr", "edit pr", "change pr title", "change pr body", "change base branch", "close pr"),
        examples=("update PR 42 title in owner/repo", "change PR 42 base branch to develop"),
    ),
    "create_pull_request": ActionDefinition(
        name="create_pull_request",
        description="Create a pull request between two branches.",
        required={"owner": str, "repo": str, "title": str, "head": str, "base": str},
        optional={"body": str, "draft": bool},
        keywords=("open pr", "create pull request", "raise pr"),
        examples=("create a pull request from feature/docs to main",),
    ),
    "merge_pull_request": ActionDefinition(
        name="merge_pull_request",
        description="Merge a pull request.",
        required={"owner": str, "repo": str, "pull_number": int},
        optional={"commit_title": str, "commit_message": str, "sha": str, "merge_method": str},
        keywords=("merge pr", "merge pull request", "squash merge", "rebase merge"),
        examples=("merge PR 42 in owner/repo using squash",),
    ),
    "request_pull_request_reviewers": ActionDefinition(
        name="request_pull_request_reviewers",
        description="Request user or team reviewers on a pull request.",
        required={"owner": str, "repo": str, "pull_number": int},
        optional={"reviewers": list, "team_reviewers": list},
        keywords=("request reviewers", "add reviewers", "pr reviewers", "team reviewers"),
        examples=("request octocat to review PR 42 in owner/repo",),
    ),
    "create_pull_request_review": ActionDefinition(
        name="create_pull_request_review",
        description="Submit a review on a pull request.",
        required={"owner": str, "repo": str, "pull_number": int, "body": str},
        optional={"event": str},
        keywords=("review pr", "approve pr", "request changes", "comment on pull request"),
        examples=("approve PR 10 in owner/repo",),
    ),
    "create_pull_request_review_comment": ActionDefinition(
        name="create_pull_request_review_comment",
        description="Create an inline review comment on a pull request diff line.",
        required={"owner": str, "repo": str, "pull_number": int, "body": str, "commit_id": str, "path": str, "line": int},
        optional={"side": str, "start_line": int, "start_side": str},
        keywords=("inline comment", "review comment", "comment on diff", "pr line comment", "pull request line"),
        examples=("add an inline comment to line 20 of app.py on PR 42",),
    ),
    "reply_to_pull_request_review_comment": ActionDefinition(
        name="reply_to_pull_request_review_comment",
        description="Reply to an existing pull request review comment.",
        required={"owner": str, "repo": str, "pull_number": int, "comment_id": int, "body": str},
        keywords=("reply review comment", "reply inline comment", "respond to pr comment"),
        examples=("reply to PR review comment 123 in owner/repo",),
    ),
    "get_check_runs": ActionDefinition(
        name="get_check_runs",
        description="Get CI or check runs for a commit or branch reference.",
        required={"owner": str, "repo": str, "ref": str},
        keywords=("ci", "checks", "status", "tests", "check runs", "commit status"),
        examples=("check ci for commit abc123 in owner/repo",),
    ),
    "list_actions_runs": ActionDefinition(
        name="list_actions_runs",
        description="List GitHub Actions workflow runs for a repository.",
        required={"owner": str, "repo": str},
        optional={"branch": str, "per_page": int},
        keywords=("actions", "workflow runs", "ci runs", "github actions"),
        examples=("show workflow runs in owner/repo",),
    ),
    "search_code": ActionDefinition(
        name="search_code",
        description="Search code across repositories accessible to the token.",
        required={"query": str},
        optional={"per_page": int},
        keywords=("search code", "find symbol", "find file", "grep github"),
        examples=("search code for fastapi router",),
    ),
    "search_repositories": ActionDefinition(
        name="search_repositories",
        description="Search GitHub repositories.",
        required={"query": str},
        optional={"sort": str, "order": str, "per_page": int, "page": int},
        keywords=("search repos", "search repositories", "find repository", "discover repos"),
        examples=("search repositories for langgraph github agent",),
    ),
    "search_issues": ActionDefinition(
        name="search_issues",
        description="Search GitHub issues and pull requests.",
        required={"query": str},
        optional={"sort": str, "order": str, "per_page": int, "page": int},
        keywords=("search issues", "search prs", "search pull requests", "find issue", "find pr"),
        examples=("search issues for repo:owner/repo label:bug", "search PRs with is:pr is:open"),
    ),
    "search_commits": ActionDefinition(
        name="search_commits",
        description="Search GitHub commits.",
        required={"query": str},
        optional={"sort": str, "order": str, "per_page": int, "page": int},
        keywords=("search commits", "find commit", "commit search", "sha search"),
        examples=("search commits for fix login repo:owner/repo",),
    ),
    "search_users": ActionDefinition(
        name="search_users",
        description="Search GitHub users or organizations. Use qualifiers like type:user or type:org when needed.",
        required={"query": str},
        optional={"sort": str, "order": str, "per_page": int, "page": int},
        keywords=("search users", "search orgs", "search organizations", "find user", "find org"),
        examples=("search users for octocat", "search organizations matching openai type:org"),
    ),
    "get_git_ref": ActionDefinition(
        name="get_git_ref",
        description="Get a Git reference such as heads/main.",
        required={"owner": str, "repo": str, "ref": str},
        keywords=("git ref", "branch ref", "ref sha", "heads main"),
        examples=("get git ref heads/main in owner/repo",),
    ),
    "create_git_ref": ActionDefinition(
        name="create_git_ref",
        description="Create a Git reference.",
        required={"owner": str, "repo": str, "ref": str, "sha": str},
        keywords=("create git ref", "create branch ref", "new ref"),
        examples=("create refs/heads/feature-docs from sha abc123 in owner/repo",),
    ),
    "update_git_ref": ActionDefinition(
        name="update_git_ref",
        description="Update a Git reference to point at a new SHA.",
        required={"owner": str, "repo": str, "ref": str, "sha": str},
        optional={"force": bool},
        keywords=("update git ref", "move branch", "update branch sha", "patch ref"),
        examples=("move heads/feature-docs to commit abc123 in owner/repo",),
    ),
    "create_branch": ActionDefinition(
        name="create_branch",
        description="Create a branch from another branch or SHA.",
        required={"owner": str, "repo": str, "branch": str},
        optional={"from_branch": str, "from_sha": str},
        keywords=("create branch", "new branch", "branch from main", "feature branch"),
        examples=("create branch feature/docs from main in owner/repo",),
    ),
    "create_git_blob": ActionDefinition(
        name="create_git_blob",
        description="Create a Git blob for file content.",
        required={"owner": str, "repo": str, "content": str},
        optional={"encoding": str},
        keywords=("create blob", "git blob", "file blob"),
        examples=("create a git blob in owner/repo",),
    ),
    "create_git_tree": ActionDefinition(
        name="create_git_tree",
        description="Create a Git tree from file entries.",
        required={"owner": str, "repo": str, "tree": list},
        optional={"base_tree": str},
        keywords=("create tree", "git tree", "multi file tree"),
        examples=("create a git tree with multiple file entries in owner/repo",),
    ),
    "create_git_commit": ActionDefinition(
        name="create_git_commit",
        description="Create a Git commit from a tree and parent commits.",
        required={"owner": str, "repo": str, "message": str, "tree": str, "parents": list},
        keywords=("create commit", "git commit", "commit tree"),
        examples=("create a git commit in owner/repo",),
    ),
    "create_multi_file_commit": ActionDefinition(
        name="create_multi_file_commit",
        description="Create or update multiple files in one commit on a branch, optionally creating the branch first.",
        required={"owner": str, "repo": str, "branch": str, "message": str, "files": list},
        optional={"base_branch": str, "create_branch": bool},
        keywords=("multi file commit", "commit multiple files", "branch commit", "edit multiple files", "create branch and commit"),
        examples=("create a branch feature/docs and commit README.md and memory.md updates",),
    ),
    "get_rate_limit": ActionDefinition(
        name="get_rate_limit",
        description="Get current GitHub API rate limit usage.",
        required={},
        keywords=("rate limit", "quota", "api limit"),
        examples=("what is my current github rate limit",),
    ),
}


class ActionRetriever:
    def __init__(self, registry: dict[str, ActionDefinition]) -> None:
        self.registry = registry
        self._action_tokens = {name: _tokenize(action.searchable_text()) for name, action in registry.items()}

    def retrieve(self, task: str, top_k: int = 6) -> list[ActionDefinition]:
        query_tokens = _tokenize(task)
        scored: list[tuple[int, str]] = []
        for name, action in self.registry.items():
            action_tokens = self._action_tokens[name]
            overlap = len(query_tokens & action_tokens)
            score = overlap
            lowered_task = task.lower()
            if name in lowered_task:
                score += 4
            if any(example.lower() in lowered_task for example in action.examples):
                score += 3
            if any(keyword.lower() in lowered_task for keyword in action.keywords):
                score += 2
            scored.append((score, name))

        ranked = [self.registry[name] for score, name in sorted(scored, key=lambda item: (-item[0], item[1])) if score > 0]
        if ranked:
            return ranked[:top_k]

        fallback_names = [
            "get_repo",
            "get_contents",
            "list_user_repos",
            "search_code",
            "get_rate_limit",
        ]
        return [self.registry[name] for name in fallback_names[:top_k] if name in self.registry]


def get_action_definition(action_name: str) -> ActionDefinition | None:
    return ACTION_REGISTRY.get(action_name)


def format_candidates_for_prompt(candidates: list[ActionDefinition]) -> str:
    lines: list[str] = []
    for action in candidates:
        lines.append(f"- {action.name}: {action.description}")
        lines.append(f"  required: {action.required or {}}")
        lines.append(f"  optional: {action.optional or {}}")
        if action.examples:
            lines.append(f"  examples: {list(action.examples[:2])}")
    return "\n".join(lines)
