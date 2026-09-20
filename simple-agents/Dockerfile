# Simple agents service image.
#
# Build context is the REPO ROOT so this Dockerfile can COPY both
# agentops-sdk/ and simple-agents/. The simple-agents package is not a
# declared dependency of agentops-sdk, so the image installs both
# explicitly.
#
#   docker compose build simple-agent-service

FROM python:3.12-slim

WORKDIR /app

# Copy both packages and install them, then add the service runtime.
COPY agentops-sdk ./agentops-sdk
COPY simple-agents ./simple-agents

RUN pip install --no-cache-dir \
      ./agentops-sdk \
      ./simple-agents

EXPOSE 8002

# FastAPI app: simple_agents.service.app:app
CMD ["uvicorn", "simple_agents.service.app:app", \
     "--host", "0.0.0.0", "--port", "8002"]
