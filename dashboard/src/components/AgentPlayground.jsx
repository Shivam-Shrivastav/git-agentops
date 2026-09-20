import { useEffect, useState } from "react";

import { AGENTS, SUGGESTIONS, GENERIC_SUGGESTIONS } from "../utils/assistant";
import { getSimpleAgents } from "../api";

const ICONS = {
  "trip-planner-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3 10h18M3 10l2-4h14l2 4M5 10v10M19 10v10M8 21h8M12 3v3" />
      <circle cx="12" cy="7" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  ),
  "local-researcher-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.35-4.35" />
      <path d="M11 8v6M8 11h6" />
    </svg>
  ),
  "json-wrangler-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 6h16M4 10h16M4 14h10M4 18h7" />
      <circle cx="19" cy="17" r="2" />
    </svg>
  ),
  "diff-summarizer-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M8 9h8M8 13h5M8 17h3" />
    </svg>
  ),
  "share-page-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="8" cy="12" r="2" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="16" cy="18" r="2" />
      <path d="M10 11l4-3M10 13l4 3" />
    </svg>
  ),
  "trade-signal-agent": (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 20h16M4 16l4-4 4 2 8-8" />
      <path d="M16 6h4v4" />
    </svg>
  ),
};

function AgentIcon({ agentId }) {
  return (
    <span className="agent-tile-icon" aria-hidden="true">
      {ICONS[agentId]}
    </span>
  );
}

function ActionList({ actions }) {
  if (!actions || actions.length === 0) return null;
  return (
    <ul className="agent-tile-actions">
      {actions.map((action) => (
        <li key={action}>{action}</li>
      ))}
    </ul>
  );
}

function AgentPlayground({ selectedAgentId, onSelectAgent, onSendQuestion }) {
  const [agents, setAgents] = useState(
    AGENTS.map((a) => ({
      id: a.id,
      name: a.label,
      description: a.description,
      actions: a.actions ?? [],
    })),
  );
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSimpleAgents()
      .then((data) => {
        if (cancelled) return;
        // Preserve the order in the static catalog, but merge remote metadata
        // so the UI is authoritative and the second tile stays Trade Signal.
        setAgents(
          AGENTS.map((local) => {
            const remote = data.find((r) => r.id === local.id);
            return {
              id: local.id,
              name: local.label,
              description: local.description,
              actions: local.actions ?? [],
            };
          }),
        );
      })
      .catch(() => {
        if (cancelled) return;
        // Keep the static catalog.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = agents.find((a) => a.id === selectedAgentId) ?? agents[0];
  const suggestions = SUGGESTIONS[selected?.id] ?? [];

  return (
    <div className="agent-playground">
      <div className="agent-playground-header">
        <div className="agent-playground-titles">
          <h2>Playground</h2>
          <p>Run a lightweight, privacy-safe agent. Every execution is traced.</p>
        </div>
        {loading && (
          <span className="agent-playground-loading">Loading agents...</span>
        )}
      </div>

      <div className="agent-tiles">
        {agents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            className={`agent-tile ${agent.id === selectedAgentId ? "agent-tile-active" : ""}`}
            onClick={() => onSelectAgent(agent.id)}
          >
            <AgentIcon agentId={agent.id} />
            <span className="agent-tile-name">{agent.name}</span>
            <span className="agent-tile-desc">{agent.description}</span>
            <ActionList actions={agent.actions} />
          </button>
        ))}
      </div>

      {selected && (
        <div className="agent-detail">
          <div className="agent-detail-header">
            <AgentIcon agentId={selected.id} />
            <div>
              <h3>{selected.name}</h3>
              <p>{selected.description}</p>
              <ActionList actions={selected.actions} />
            </div>
          </div>

          <div className="agent-suggested-questions">
            <h4>Suggested tasks</h4>
            <div className="agent-question-chips">
              {suggestions.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="agent-question-chip"
                  onClick={() => onSendQuestion(q)}
                >
                  {q}
                </button>
              ))}
              {GENERIC_SUGGESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="agent-question-chip agent-question-chip-generic"
                  onClick={() => onSendQuestion(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default AgentPlayground;
