import { useEffect, useRef, useState } from "react";

import { getSimpleAgentRun, startSimpleAgentRun } from "../api";
import { isExitIntent, routeMessage, AGENTS } from "../utils/assistant";
import Markdown from "./Markdown";

const STORAGE_KEY = "agentops-chat-history";
const WIDTH_KEY = "agentops-chat-width";
const SCRIPTED_DELAY = 350; // ms — scripted replies feel instantaneous-ish
const POLL_INTERVAL = 2000; // ms — poll the agent run

const PANEL_MIN = 300; // px — floor for the resizable side panel
const PANEL_MAX = 560; // px — ceiling

function clampWidth(w) {
  return Math.max(PANEL_MIN, Math.min(PANEL_MAX, Math.round(w)));
}

function initialWidth() {
  try {
    const saved = Number(localStorage.getItem(WIDTH_KEY));
    if (saved) {
      return clampWidth(saved);
    }
  } catch {
    // localStorage disabled — fall through to default.
  }
  // Default: ~22% of the viewport, clamped to the min/max band.
  return clampWidth(
    typeof window !== "undefined" ? window.innerWidth * 0.22 : 360,
  );
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function formatAgentResponse(resp) {
  if (resp == null) {
    return "(no response)";
  }
  if (typeof resp === "string") {
    return resp;
  }
  if (typeof resp === "object" && resp.summary) {
    return resp.summary;
  }
  return JSON.stringify(resp, null, 2);
}

function ChatAssistant({
  onSelectTrace,
  selectedAgentId,
  suggestedTask,
}) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState(loadHistory);
  const [input, setInput] = useState("");
  const [typing, setTyping] = useState(false);
  const [typingCaption, setTypingCaption] = useState("");

  // Side-panel width, persisted per-browser (the "slider" resizes this).
  const [width, setWidth] = useState(initialWidth);
  const [dragging, setDragging] = useState(false);

  // Agent-run conversation state (multi-turn with clarifications).
  const [currentTask, setCurrentTask] = useState(null);
  const [clarifications, setClarifications] = useState([]);
  const [awaitingClarification, setAwaitingClarification] = useState(false);

  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const pollRef = useRef(null);
  const activeRunRef = useRef(null);
  const timersRef = useRef([]);
  const lastSuggestedRef = useRef(null);

  // Persist history across reloads (per-browser).
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
    } catch {
      // Storage full / disabled — non-fatal.
    }
  }, [messages]);

  // Auto-scroll to the latest message.
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, typing, open]);

  // When the playground sends a suggested task, put it in the input and open
  // the chat so the user can review/edit before sending.
  useEffect(() => {
    if (!suggestedTask || suggestedTask === lastSuggestedRef.current) {
      return;
    }
    lastSuggestedRef.current = suggestedTask;
    setInput(suggestedTask);
    setOpen(true);
    // Focus the textarea after the panel opens.
    setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 50);
  }, [suggestedTask]);

  // Clean up timers/polling on unmount.
  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
      timersRef.current.forEach((t) => clearTimeout(t));
    };
  }, []);

  // While the resize handle is being dragged, track the pointer across the
  // whole window (the cursor leaves the narrow handle almost immediately)
  // and update the panel width = viewport-right - cursor-x.
  useEffect(() => {
    if (!dragging) {
      return undefined;
    }
    const onMove = (e) => {
      const next = clampWidth(window.innerWidth - e.clientX);
      setWidth(next);
      try {
        localStorage.setItem(WIDTH_KEY, String(next));
      } catch {
        // localStorage disabled — width still applies for the session.
      }
    };
    const onUp = () => setDragging(false);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging]);

  function pushUser(text) {
    setMessages((prev) => [
      ...prev,
      { role: "user", text, ts: Date.now() },
    ]);
  }

  function pushAssistant(text, traceId = null, traceback = null) {
    setMessages((prev) => [
      ...prev,
      { role: "assistant", text, ts: Date.now(), traceId, traceback },
    ]);
  }

  function clearRunState() {
    setCurrentTask(null);
    setClarifications([]);
    setAwaitingClarification(false);
  }

  // Start (or continue, with clarifications) an agent run and poll it.
  function runAgentTask(task, clarificationsList, agentId = selectedAgentId) {
    // Supersede any in-flight poll.
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    activeRunRef.current = null;

    setTyping(true);
    setTypingCaption("Running the agent…");

    const startRun = () => startSimpleAgentRun(agentId, task, clarificationsList);
    const getRun = getSimpleAgentRun;

    let runId;
    startRun()
      .then((started) => {
        runId = started.run_id;
        activeRunRef.current = runId;

        const poll = async () => {
          if (runId !== activeRunRef.current) {
            return; // superseded or cancelled
          }
          try {
            const data = await getRun(runId);
            if (runId !== activeRunRef.current) {
              return;
            }
            if (data.status === "running") {
              return; // keep polling
            }

            // Terminal — stop polling.
            clearInterval(pollRef.current);
            pollRef.current = null;
            activeRunRef.current = null;
            setTyping(false);
            setTypingCaption("");

            if (data.status === "done") {
              pushAssistant(formatAgentResponse(data.final_response), data.trace_id);
              clearRunState();
            } else if (data.status === "needs_input") {
              setCurrentTask(task);
              setClarifications(clarificationsList);
              setAwaitingClarification(true);
              pushAssistant(
                data.question ||
                  (typeof data.final_response === "string"
                    ? data.final_response
                    : "I need more information to continue."),
              );
            } else if (data.status === "error") {
              pushAssistant(
                "The agent run failed: " + (data.error || "unknown error"),
                null,
                data.traceback || null,
              );
              clearRunState();
            } else {
              pushAssistant("Unexpected run status: " + data.status);
              clearRunState();
            }
          } catch (err) {
            if (runId !== activeRunRef.current) {
              return;
            }
            clearInterval(pollRef.current);
            pollRef.current = null;
            activeRunRef.current = null;
            setTyping(false);
            setTypingCaption("");
            pushAssistant("Polling the agent failed: " + err.message);
            clearRunState();
          }
        };

        pollRef.current = setInterval(poll, POLL_INTERVAL);
        poll(); // immediate first check
      })
      .catch((err) => {
        setTyping(false);
        setTypingCaption("");
        pushAssistant("Couldn't start the agent: " + err.message);
        clearRunState();
      });
  }

  function send(rawText) {
    const text = (rawText || "").trim();
    if (!text || typing) {
      return;
    }

    pushUser(text);
    setInput("");

    // Continuation of a needs_input round: treat the reply as a
    // clarification (unless it's an exit/greeting, which aborts the round).
    if (awaitingClarification) {
      if (isExitIntent(text)) {
        setTyping(true);
        setTypingCaption("");
        const t = setTimeout(() => {
          setTyping(false);
          pushAssistant(
            "Okay, cancelled. What would you like to do? You can give me a new task or ask about the dashboard.",
          );
        }, SCRIPTED_DELAY);
        timersRef.current.push(t);
        clearRunState();
        return;
      }
      const nextClars = [...clarifications, text];
      setClarifications(nextClars);
      runAgentTask(currentTask, nextClars);
      return;
    }

    const route = routeMessage(text, selectedAgentId, messages);
    if (!route) {
      return;
    }

    if (route.type === "agent") {
      runAgentTask(route.task, [], selectedAgentId);
      return;
    }

    // scripted or out_of_scope — short delay, then reply.
    setTyping(true);
    setTypingCaption("");
    const t = setTimeout(() => {
      setTyping(false);
      pushAssistant(route.reply);
    }, SCRIPTED_DELAY);
    timersRef.current.push(t);
  }

  function handleSubmit(event) {
    event.preventDefault();
    send(input);
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(input);
    }
  }

  function handleClear() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    activeRunRef.current = null;
    timersRef.current.forEach((t) => clearTimeout(t));
    timersRef.current = [];
    setMessages([]);
    setTyping(false);
    setTypingCaption("");
    clearRunState();
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Ignore.
    }
  }

  const selectedAgent = AGENTS.find((a) => a.id === selectedAgentId) ?? AGENTS[0];

  return (
    <div className="chat-assistant">
      {open && (
        <div
          className={`chat-panel${dragging ? " chat-panel-dragging" : ""}`}
          style={{ width: `${width}px` }}
        >
          {/* Resize slider — drag the left edge to widen/narrow the panel. */}
          <div
            className={`chat-resizer${dragging ? " chat-resizer-active" : ""}`}
            onMouseDown={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            title="Drag to resize"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize chat panel"
          />

          <div className="chat-header">
            <div className="chat-header-titles">
              <span className="chat-title">Agent playground</span>
              <span className="chat-subtitle">
                Chat · {selectedAgent?.label ?? "Agent"}
              </span>
            </div>
            <div className="chat-header-actions">
              {messages.length > 0 && (
                <button
                  type="button"
                  className="chat-clear"
                  onClick={handleClear}
                  title="Clear conversation"
                >
                  Clear
                </button>
              )}
              <button
                type="button"
                className="chat-close"
                onClick={() => setOpen(false)}
                title="Close"
                aria-label="Close assistant"
              >
                ×
              </button>
            </div>
          </div>

          <div className="chat-messages" ref={scrollRef}>
            {messages.length === 0 && (
              <div className="chat-empty">
                <p>
                  Hi! 👋 Send me a task for the <strong>{selectedAgent?.label}</strong> agent
                  and I'll run it and show you the result — with a link to the
                  full AgentOps trace.
                </p>
              </div>
            )}

            {messages.map((m, i) => (
              <div
                key={i}
                className={`chat-bubble chat-bubble-${m.role}`}
              >
                {m.role === "assistant" ? (
                  <Markdown text={m.text} />
                ) : (
                  m.text
                )}
                {m.traceId && (
                  <button
                    type="button"
                    className="chat-view-trace"
                    onClick={() => onSelectTrace && onSelectTrace(m.traceId)}
                  >
                    View trace →
                  </button>
                )}
                {m.traceback && (
                  <details className="chat-traceback">
                    <summary>Show traceback</summary>
                    <pre>{m.traceback}</pre>
                  </details>
                )}
              </div>
            ))}

            {typing && (
              <div className="chat-typing-wrap">
                <div className="chat-bubble chat-bubble-assistant chat-typing">
                  <span />
                  <span />
                  <span />
                </div>
                {typingCaption && (
                  <span className="chat-typing-caption">
                    {typingCaption}
                  </span>
                )}
              </div>
            )}
          </div>

          <form className="chat-input-row" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
              className="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                awaitingClarification
                  ? "Answer the agent's question…"
                  : `Give the ${selectedAgent?.label ?? "agent"} a task…`
              }
              rows={1}
              aria-label="Message"
            />
            <button
              type="submit"
              className="chat-send"
              disabled={!input.trim() || typing}
              aria-label="Send"
            >
              ➤
            </button>
          </form>
        </div>
      )}

      {!open && (
        <div className="chat-open-wrap">
          <button
            type="button"
            className="chat-open-pill"
            onClick={() => setOpen(true)}
            aria-label="Open assistant"
            title="Chat with the agent"
          >
            <span className="chat-open-dot" aria-hidden="true" />
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10z" />
            </svg>
            <span className="chat-open-label">Chat</span>
          </button>
          <p className="chat-open-hint">
            Select an agent above, then send a task here.
          </p>
        </div>
      )}
    </div>
  );
}

export default ChatAssistant;
