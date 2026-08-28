// Routing brain for the chat interface to the github-agent.
//
// Each user message is classified into one of:
//   { type: "scripted",    reply }  — greetings/help/thanks/bye/dashboard tour
//   { type: "agent",       task }   — a GitHub task -> trigger the agent
//   { type: "out_of_scope",reply }  — politely deflect + state capabilities
//
// Deterministic (no LLM) so it's instant, free, and won't 500 mid-demo. The
// agent itself is only invoked for real tasks. Swap `routeMessage` for an
// LLM router later without touching the UI.

const GREETING_RE =
  /\b(hi+|hello+|hey+|yo+|hiya|hola|namaste|good (morning|afternoon|evening))\b/;
const THANKS_RE = /\b(thanks|thank you|thankyou|thx|appreciate|cheers)\b/;
const BYE_RE = /\b(bye+|goodbye|see ya|see you|cya|good night)\b/;
const HELP_RE =
  /\b(help|what can you do|who are you|what do you do|your (name|purpose)|what are you)\b/;
const EXIT_RE = /\b(cancel|never ?mind|stop|exit|quit|abort|forget it)\b/;

// A message is an agent task if it names a repo path (owner/repo) OR pairs an
// action verb with a GitHub noun. This keeps general chatter / knowledge
// questions from burning a (slow, flaky) agent run.
const REPO_PATH_RE = /[\w.-]+\/[\w.-]+/;
const ACTION_RE =
  /\b(list|find|search|summarize|show|get|fetch|create|open|close|comment|read|write|look ?up|tell me)\b/;
const AGENT_WORDS = [
  "issue",
  "repo",
  "pull request",
  "pullrequest",
  "release",
  "branch",
  "commit",
  "milestone",
  "repository",
];

const AGENT_INTRO =
  "Send me a GitHub task — e.g. \"list open issues in Shivam-Shrivastav/Data-Structures\" or \"summarize the latest release of owner/repo\" — and I'll run the github-agent and show you its answer, with a link to the full trace.";

const TOUR_INTRO =
  "I can also tour the dashboard — ask about traces, the decision-quality (LLM-judge) eval, alerts, token usage/cost, or how this is all hosted.";

function greetingReply() {
  return "Hi! 👋 I'm the chat interface to the github-agent. " +
    AGENT_INTRO +
    " " +
    TOUR_INTRO +
    " What would you like to do?";
}

function helpReply() {
  return "I do two things:\n1) Run GitHub tasks via the github-agent — " +
    AGENT_INTRO.replace("Send me a GitHub task — e.g. ", "").replace(
      " — and I'll run the github-agent and show you its answer, with a link to the full trace.",
      "",
    ) +
    ".\n2) " +
    TOUR_INTRO.charAt(0).toLowerCase() +
    TOUR_INTRO.slice(1);
}

function outOfScopeReply() {
  return "I can't help with that — I'm scoped to two things:\n1) Running GitHub tasks via the agent (e.g. \"list open issues in owner/repo\", \"summarize the latest release of owner/repo\").\n2) Explaining this dashboard (traces, the decision-quality eval, alerts, token usage, hosting).\nCould you rephrase, or pick one of those?";
}

// Dashboard-tour intents — scripted answers about THIS project.
const DASHBOARD_INTENTS = [
  {
    keys: [
      "trigger",
      "start a run",
      "run the agent",
      "how do i run",
      "how to run",
      "run agent",
      "new run",
      "give it a task",
      "give the agent",
      "how do i trigger",
    ],
    reply:
      "Just type a GitHub task right here in this chat — e.g. \"list open issues in Shivam-Shrivastav/Data-Structures\" — and I'll run the github-agent and reply with its result, plus a \"View trace\" link to the full observability trace. If it needs more info, I'll ask you a follow-up.",
  },
  {
    keys: [
      "what is this",
      "what is agentops",
      "what does this",
      "about this project",
      "what's this",
      "overview",
      "what is this dashboard",
      "what am i looking at",
    ],
    reply:
      "This is AgentOps — an observability platform for LLM agents. A LangGraph GitHub-agent emits trace/span events over HTTP to a FastAPI ingestion API (Postgres + Redis), and this dashboard turns them into traces, spans, LLM-decision timelines, token usage, failure analytics, and an LLM-judge decision-quality eval.",
  },
  {
    keys: ["trace", "span", "observability", "timeline", "execution", "tree"],
    reply:
      "A trace is one full agent run; spans are the steps inside it (planner turns, LLM calls, tool calls). Click any run in the list — or the \"View trace\" link in our chat — to open its trace: span tree, execution timeline, per-span payloads, and token usage.",
  },
  {
    keys: ["decision", "reasoning", "why did", "chosen", "candidate", "why"],
    reply:
      "Every planning step is a 'decision': the agent lists candidate actions, picks one, and records its reasoning. The decision timeline shows each step's thought, chosen action, rejected candidates, confidence, and tokens — so you can see WHY the agent did what it did.",
  },
  {
    keys: ["quality", "eval", "judge", "score", "decision-quality", "graded", "rating"],
    reply:
      "The decision-quality eval is an LLM-judge: a separate LLM scores each run's decisions on a 1–5 scale with noted strengths and weaknesses. It grades how good the agent's reasoning was, not just whether the run succeeded.",
  },
  {
    keys: ["alert", "alert rule", "firing", "threshold", "notify"],
    reply:
      "Alerts set thresholds on metrics (e.g. failure rate, cost) and surface when they fire. The Alerts section lists rules you can edit, toggle, and delete; firing alerts show up top and in the header badge.",
  },
  {
    keys: ["cost", "token", "usage", "budget", "how much", "spend", "tokens"],
    reply:
      "Token usage and cost are tracked per run and aggregated. The Model breakdown shows per-model tokens/cost, and the Cost trend chart plots input/output tokens over a switchable time bucket (15m / hour / day).",
  },
  {
    keys: ["model", "openrouter", "which model", "llm model", "free model"],
    reply:
      "The agent uses OpenRouter's free model by default (configurable via OPENROUTER_MODEL). The Model breakdown section breaks down calls, tokens, and cost per model so you can compare.",
  },
  {
    keys: ["failure", "error", "fail", "crash", "failed", "bug"],
    reply:
      "The Failure analytics section summarizes error counts and which spans/components are the top failure sources, so you can see where the agent tends to break.",
  },
  {
    keys: [
      "host",
      "hosted",
      "deploy",
      "deployment",
      "cloudflare",
      "tunnel",
      "server",
      "vps",
      "url",
      "online",
      "public",
    ],
    reply:
      "The whole stack runs in Docker Compose on a home machine and is exposed publicly through a Cloudflare Tunnel — outbound-only, no public IP or open ports, HTTPS terminates at Cloudflare's edge, and Caddy reverse-proxies /api, /agent, and the dashboard with HTTP basic auth. The same compose deploys to a VPS unchanged.",
  },
  {
    keys: [
      "github",
      "what does the agent do",
      "github-agent",
      "what can the agent do",
      "agent do",
    ],
    reply:
      "The github-agent is a LangGraph agent that works with GitHub — e.g. \"list open issues in owner/repo\". It's wrapped as an HTTP service (POST /agent/run) and instrumented with the AgentOps SDK so every run is captured as a trace. Just type a task in this chat and I'll run it.",
  },
];

function normalize(text) {
  return text
    .toLowerCase()
    .replace(/[^\w\s/.-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isAgentTask(n) {
  if (REPO_PATH_RE.test(n)) {
    return true;
  }
  return ACTION_RE.test(n) && AGENT_WORDS.some((w) => n.includes(w));
}


export function routeMessage(message, _history = []) {
  const text = (message || "").trim();
  if (!text) {
    return null;
  }

  const n = normalize(text);
  const wordCount = n.split(" ").filter(Boolean).length;

  if (wordCount <= 4 && GREETING_RE.test(n)) {
    return { type: "scripted", reply: greetingReply() };
  }
  if (THANKS_RE.test(n)) {
    return {
      type: "scripted",
      reply:
        "You're welcome! Want to give the agent a task, or take a tour of the dashboard?",
    };
  }
  if (BYE_RE.test(n) && wordCount <= 4) {
    return { type: "scripted", reply: "Goodbye! Come back and send a task anytime. 👋" };
  }
  if (HELP_RE.test(n)) {
    return { type: "scripted", reply: helpReply() };
  }

  // Agent task takes precedence over a dashboard-tour match when the message
  // is an actionable GitHub request (e.g. "list open issues in owner/repo").
  if (isAgentTask(n)) {
    return { type: "agent", task: text };
  }

  // Dashboard-tour scripted answers.
  let best = null;
  let bestScore = 0;
  for (const intent of DASHBOARD_INTENTS) {
    let score = 0;
    for (const key of intent.keys) {
      if (n.includes(key)) {
        score += 1;
      }
    }
    if (score > bestScore) {
      bestScore = score;
      best = intent;
    }
  }
  if (best) {
    return { type: "scripted", reply: best.reply };
  }

  return { type: "out_of_scope", reply: outOfScopeReply() };
}


// True for messages that should abort a pending clarification round instead
// of being fed to the agent as an answer.
export function isExitIntent(message) {
  const n = normalize(message || "");
  const wordCount = n.split(" ").filter(Boolean).length;
  return EXIT_RE.test(n) || (wordCount <= 4 && GREETING_RE.test(n));
}


// Starter prompts shown as chips when the conversation is empty.
export const SUGGESTIONS = [
  "List open issues in Shivam-Shrivastav/Data-Structures",
  "What can you do?",
  "What is the decision-quality eval?",
  "How is this hosted?",
];