# Multi-stage build. In production the app is built and served by vite
# preview behind a reverse proxy; in local dev the same image is rebuilt
# with the default VITE_API_BASE_URL=http://localhost:8000 and the
# dashboard calls the host's ingestion-api directly.
FROM node:20-slim AS build

WORKDIR /app

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# The github-agent HTTP service is at /agent in production (same origin
# behind the reverse proxy). Default /agent works for any proxy-mounted
# deploy; local dev has no agent-service, so the panel is hosted-only.
ARG VITE_AGENT_BASE_URL=/agent
ENV VITE_AGENT_BASE_URL=$VITE_AGENT_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- runtime -----------------------------------------------------------
FROM node:20-slim

WORKDIR /app
COPY --from=build /app /app

EXPOSE 5173

# vite preview serves the built static bundle. --host 0.0.0.0 so the
# reverse proxy / host can reach it; --port 5173 matches the EXPOSE and
# the compose service port.
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]