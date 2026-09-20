// Routing brain for the chat interface and agent playground.
//
// The dashboard now shows a left sidebar + agent tiles. The chat panel no
// longer has an agent selector; it always uses the agent selected in the
// playground. This file keeps the static agent catalog, starter questions,
// and the simple message router.

// Catalog of lightweight, privacy-safe agents shown as tiles in the playground.
// The chat panel and playground both read from this list.
export const AGENTS = [
  {
    id: "trip-planner-agent",
    label: "Trip Planner",
    description:
      "Reasons over weather forecasts, web search, and budget to build a day-by-day itinerary.",
    placeholder:
      "Plan a 3-day trip to Tokyo with a $1500 budget. I like museums, food, and day trips.",
    actions: ["Open-Meteo weather forecast", "DuckDuckGo activities search"],
  },
  {
    id: "trade-signal-agent",
    label: "Paper Trade Signal",
    description:
      "Fetches market data and news, then reasons to a buy/sell/hold signal with position sizing.",
    placeholder: "Should I buy, sell, or hold BTC right now?",
    actions: ["CoinGecko price", "Alpha Vantage / CryptoCompare price fallback", "DuckDuckGo news search"],
  },
  {
    id: "local-researcher-agent",
    label: "Local Researcher",
    description:
      "Searches the live web with DuckDuckGo, reads pages via r.jina.ai, and writes a cited markdown report.",
    placeholder: "Research local AI observability with r.jina.ai and summarize",
    actions: ["DuckDuckGo web search", "r.jina.ai page reader"],
  },
  {
    id: "json-wrangler-agent",
    label: "JSON Wrangler",
    description:
      "Validates and pretty-prints messy JSON. If the input isn't valid JSON, it extracts structure first.",
    placeholder:
      'Format this JSON: {"name":"AgentOps","features":["traces","spans","alerts"]}',
    actions: ["Native JSON parser", "LLM structure extraction"],
  },
  {
    id: "diff-summarizer-agent",
    label: "Diff Summarizer",
    description:
      "Compares two text blocks with a real unified diff and summarizes the changes in plain English.",
    placeholder:
      "Summarize the difference between these two code blocks:\n\ndef old(x):\n    return x * 2\n\n---\n\ndef new(x):\n    return x * 2 + 1",
    actions: ["Unified diff computation", "LLM summarization"],
  },
  {
    id: "share-page-agent",
    label: "Share This Page",
    description:
      "Fetches a URL, summarizes it, shortens the link, and generates a scannable QR code.",
    placeholder: "Share this page: https://en.wikipedia.org/wiki/AgentOps",
    actions: ["URL fetch / r.jina.ai reader", "is.gd link shortener", "QR code generation"],
  },
];

const GREETING_RE =
  /\b(hi+|hello+|hey+|yo+|hiya|hola|namaste|good (morning|afternoon|evening))\b/;
const THANKS_RE = /\b(thanks|thank you|thankyou|thx|appreciate|cheers)\b/;
const BYE_RE = /\b(bye+|goodbye|see ya|see you|cya|good night)\b/;
const HELP_RE =
  /\b(help|what can you do|who are you|what do you do|your (name|purpose)|what are you)\b/;
const EXIT_RE = /\b(cancel|never ?mind|stop|exit|quit|abort|forget it)\b/;

const SIMPLE_AGENT_INTRO =
  "Pick an agent in the playground, give it a task, and I'll run it and show you the result — with a link to the full AgentOps trace. These agents use only public data and need no extra auth.";

const TOUR_INTRO =
  "I can also tour the dashboard — ask about traces, the decision-quality eval, alerts, token usage/cost, or how this is all hosted.";

function greetingReply() {
  return `Hi. I'm the chat interface to the agents. ${SIMPLE_AGENT_INTRO} ${TOUR_INTRO} What would you like to do?`;
}

function helpReply() {
  const agentIntro =
    "Run lightweight, public-data agents (trip planner, web researcher, JSON wrangler, diff summarizer, share page, paper trade signal) — " +
    SIMPLE_AGENT_INTRO.replace("Pick an agent in the playground, give it a task, and ", "").replace(
      " — with a link to the full AgentOps trace.",
      "",
    );

  return `I do two things:\n1) ${agentIntro}.\n2) ${TOUR_INTRO.charAt(0).toLowerCase()}${TOUR_INTRO.slice(1)}.`;
}

function outOfScopeReply() {
  return `I can't help with that — I'm scoped to two things:\n1) Running tasks for the selected agent using public data.\n2) Explaining this dashboard (traces, the decision-quality eval, alerts, token usage, hosting).\nCould you rephrase, or pick one of those?`;
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
      "Just type a task right here in this chat — the agent selected in the playground will run it. I'll reply with the result and a \"View trace\" link to the full observability trace.",
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
      "This is AgentOps — an observability platform for LLM agents. Instrumented agents emit trace/span events over HTTP to a FastAPI ingestion API (Postgres + Redis), and this dashboard turns them into traces, spans, LLM-decision timelines, token usage, failure analytics, and an LLM-judge decision-quality eval.",
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
      "Agents use a configurable OpenAI-compatible endpoint. The simple agents default to a local Ollama model, while the github-agent targets OpenRouter. The Model breakdown section breaks down calls, tokens, and cost per model so you can compare.",
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
      "The whole stack runs in Docker Compose on a home machine and is exposed publicly through a Cloudflare Tunnel — outbound-only, no public IP or open ports, HTTPS terminates at Cloudflare's edge, and Caddy reverse-proxies /api, /agent, /simple-agent, and the dashboard with HTTP basic auth. The same compose deploys to a VPS unchanged.",
  },
  {
    keys: [
      "simple agents",
      "simple-agent",
      "playground agents",
      "trip planner",
      "researcher agent",
      "json agent",
      "diff agent",
      "share page agent",
      "trade signal agent",
    ],
    reply:
      "The simple agents are lightweight, privacy-safe agents in the Playground: Trip Planner, Local Researcher, JSON Wrangler, Diff Summarizer, Share This Page, and Paper Trade Signal. They use only public data, need no extra auth, and each run is fully traced by AgentOps.",
  },
];

function normalize(text) {
  return text
    .toLowerCase()
    .replace(/[^\w\s/.-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function routeMessage(message, selectedAgent, _history = []) {
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
        "You're welcome. Want to give the agent a task, or take a tour of the dashboard?",
    };
  }
  if (BYE_RE.test(n) && wordCount <= 4) {
    return { type: "scripted", reply: "Goodbye. Come back and send a task anytime." };
  }
  if (HELP_RE.test(n)) {
    return { type: "scripted", reply: helpReply() };
  }

  // Dashboard-tour scripted answers only when no agent is selected.
  // Otherwise the user's message is assumed to be a task for the active agent,
  // even if it contains words like "budget", "cost", or "tokens".
  if (!selectedAgent) {
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
  }

  // Treat any remaining message as a task for the selected agent.
  return { type: "agent", task: text };
}

// True for messages that should abort a pending clarification round instead
// of being fed to the agent as an answer.
export function isExitIntent(message) {
  const n = normalize(message || "");
  const wordCount = n.split(" ").filter(Boolean).length;
  return EXIT_RE.test(n) || (wordCount <= 4 && GREETING_RE.test(n));
}

// Suggested starter tasks grouped by agent. Shown as chips in the agent detail
// panel; clicking one sends it straight to the chat input.
export const SUGGESTIONS = {
  "trip-planner-agent": [
    "Plan a 3-day trip to Tokyo with a $1500 budget. I like museums, food, and day trips.",
    "Long weekend in Paris, budget $800, interested in art and cafes",
    "Week in Bali for two people, $2500 budget, beach and hiking",
  ],
  "local-researcher-agent": [
    "Research LangChain vs LangGraph and give me a cited comparison",
    "Research local AI observability with r.jina.ai and summarize",
    "What are the latest trends in AI coding assistants?",
  ],
  "json-wrangler-agent": [
    'Format this JSON: {"name":"AgentOps","features":["traces","spans","alerts"]}',
    'Validate and pretty-print: [{"id":1,"ok":true},{"id":2,"ok":false}]',
    "Fix this messy JSON: {name: AgentOps, version: 0.1.0}",
  ],
  "diff-summarizer-agent": [
    "Summarize the difference between these two code blocks:\n\ndef old(x):\n    return x * 2\n\n---\n\ndef new(x):\n    return x * 2 + 1",
    "Compare these two paragraphs and summarize what changed.\n\nOLD: The cat sat on the mat.\n\nNEW: The cat slept on the warm mat near the window.",
    "Show me the diff between these two config files:\n\nenabled: true\n\n---\n\nenabled: false\ndebug: true",
  ],
  "share-page-agent": [
    "Share this page: https://en.wikipedia.org/wiki/AgentOps",
    "Summarize https://example.com and give me a short link + QR code",
    "Share this page: https://news.ycombinator.com",
  ],
  "trade-signal-agent": [
    "Should I buy, sell, or hold BTC right now?",
    "Paper trade signal for ETH with moderate risk",
    "Bullish or bearish on NVDA? Explain your reasoning",
  ],
};

// Generic dashboard-tour chips shown alongside agent-specific suggestions.
export const GENERIC_SUGGESTIONS = [
  "What can you do?",
  "What is this dashboard?",
  "How is this hosted?",
];
