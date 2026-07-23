# GitHub Agent



Local Python framework for a GitHub agent using:

- OpenRouter free-tier models
- LangGraph for agent orchestration
- GitHub REST APIs for repo actions

## What it can do

This starter framework includes wrappers for these useful GitHub APIs:

- User/repos: `GET /user`, `GET /user/repos`, `POST /user/repos`, `POST /orgs/{org}/repos`, `POST /repos/{owner}/{repo}/forks`, `GET /repos/{owner}/{repo}`
- Contents/branches: `GET /contents/{path}`, `PUT /contents/{path}`, `GET /branches`, `GET /branches/{branch}`
- Issues: list, create, update, close/reopen, comment, add labels, add assignees
- Pull requests: list, inspect, update title/body/base/state, list files, get diff/patch, create, merge, request reviewers, submit reviews, add inline comments, reply to review comments
- Checks/actions: get check runs for a commit/ref, list workflow runs
- Search: code, repositories, issues/PRs, commits, users/orgs
- Git data: get/create/update refs, create blobs, create trees, create commits
- Utilities: `GET /rate_limit`

It also includes composite helpers:

- `create_branch`: create a branch from another branch or SHA.
- `create_multi_file_commit`: create/update multiple files in one commit on a branch, optionally creating that branch first.

## Project layout

```text
github_agent/
  cli.py
  config.py
  github_api.py
  graph.py
```

## Requirements

- Python 3.11+
- OpenRouter API key
- GitHub personal access token

## Setup

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. Copy the env file:

```bash
cp .env.example .env
```

3. Fill in `GITHUB_TOKEN` in `.env`.

4. Create an OpenRouter API key at [OpenRouter Keys](https://openrouter.ai/keys).

```bash
open https://openrouter.ai/keys
```

5. Put these values in `.env`:

```env
GITHUB_TOKEN=your_github_token
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=openrouter/free
OPENROUTER_HTTP_REFERER=http://localhost
OPENROUTER_APP_NAME=github-agent-local
```

`openrouter/free` uses OpenRouter's official free-model router. You can later switch to a specific free model if you want.

## Usage

Run a task:

```bash
github-agent "List my repos and tell me which ones look like Python services."
```

Print the full graph result:

```bash
github-agent "Inspect owner/repo and read README" --json
```

## Ollama cleanup

If you want to delete downloaded local Ollama models and free disk space:

```bash
ollama list
ollama rm qwen3-coder
```

Official docs:
- [Ollama delete API](https://docs.ollama.com/api/delete)
- [ollama rm CLI reference](https://www.mintlify.com/ollama/ollama/cli/rm)

## Example tasks

```text
Get my current GitHub rate limit.
List my repositories.
Read README.md from owner/repo.
Create a private repository named agent-sandbox.
Fork octocat/Hello-World into my account.
Fork owner/repo into org acme with name repo-copy and only the default branch.
List open issues in owner/repo.
Create an issue in owner/repo and assign it to octocat.
Close issue 12 in owner/repo.
Inspect PR 42 in owner/repo and summarize changed files.
Check CI status for commit abc123 in owner/repo.
Merge PR 42 in owner/repo using squash.
Request octocat as a reviewer on PR 42.
Search repositories for langgraph github agent.
Create branch feature/docs from main and commit updates to README.md and memory.md.
```

## How the graph works

The LangGraph workflow is intentionally simple and explicit:

1. `plan` retrieves a small candidate action set from the API registry.
2. `plan` asks the model for the next JSON action using only that shortlist.
3. `act` validates arguments and executes exactly one GitHub API wrapper call.
4. The graph loops until the model returns `FINAL` or the max step count is reached.

This keeps the agent debuggable now, while making it much easier to scale to larger API collections later.

## Scalable action selection

The agent no longer relies on one giant prompt that lists every action.

Instead it uses:

- an action registry in [github_agent/registry.py](/Users/shivamshrivastava/Documents/PROJ_PI/github-agent/github_agent/registry.py)
- lightweight lexical retrieval to shortlist relevant actions
- planner prompts that only include the retrieved candidates

This is the pattern you want as the number of APIs grows.

## Missing input handling

If a request is ambiguous or missing required fields, the agent can now stop and ask for the smallest missing set instead of guessing.

Example:

```bash
github-agent "Review pull request 42"
```

Expected style of response:

```text
Which repository should I inspect for pull request 42? Missing inputs: owner, repo.
```

In the CLI, this is now interactive. The agent will pause, ask for the missing details, and continue after you answer in the terminal.

## Follow-up memory

The CLI now keeps a tiny local memory file at `.github_agent_memory.json` in the project directory.

It remembers the last successfully referenced repository so follow-up prompts like:

```bash
github-agent "does repo foo exist?"
github-agent "what files are in that repo?"
```

can reuse the previous `owner/repo` context.

## Notes

- This version uses JSON-planned actions instead of native tool-calling to keep model behavior predictable.
- Action arguments are validated before GitHub calls are made.
- `PUT /contents` is good for simple single-file changes.
- `create_multi_file_commit` uses lower-level Git refs/blobs/trees/commits for grouped changes.
- If you want richer GitHub automation later, the next useful additions are:
  - workflow reruns and log download
  - branch protection management
  - release creation and changelog generation
