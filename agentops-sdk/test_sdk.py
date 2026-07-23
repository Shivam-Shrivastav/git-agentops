from agentops import AgentOps

ops = AgentOps()

with ops.trace(
    "github-agent",
    payload={"task": "List issues"},
):

    with ops.span(
        "planner",
        payload={"model": "gpt-4"},
    ):
        print("Planning")

    with ops.span(
        "github_api",
        payload={
            "tool": "list_issues",
            "repo": "openai/openai-python",
        },
    ):
        print("Calling GitHub")