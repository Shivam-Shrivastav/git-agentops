from agentops import AgentOps


ops = AgentOps()

try:
    with ops.trace("success-test"):
        pass
except RuntimeError:
    pass