# Agent service image — wraps the github-agent as an HTTP service.
#
# Build context is the REPO ROOT (so this Dockerfile can COPY both
# agentops-sdk/ and github-agent/). agentops is not a declared dep of
# github-agent (it resolves via the local editable venv in dev), so the
# image installs both packages explicitly, plus the service runtime.
#
#   docker compose -f docker-compose.prod.yml build agent-service

FROM python:3.12-slim

WORKDIR /app

# Copy both packages and install them, then add the HTTP runtime.
# agentops-sdk first: github-agent imports `agentops` at runtime.
COPY agentops-sdk ./agentops-sdk
COPY github-agent ./github-agent

RUN pip install --no-cache-dir \
      ./agentops-sdk \
      ./github-agent \
      "fastapi>=0.115" \
      "uvicorn[standard]>=0.32"

EXPOSE 8001

# FastAPI app: github_agent.service.app:app
CMD ["uvicorn", "github_agent.service.app:app", \
     "--host", "0.0.0.0", "--port", "8001"]