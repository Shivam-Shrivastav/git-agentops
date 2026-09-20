import { useEffect, useState } from "react";

import "./App.css";

import {
  getTraces,
  getTraceTree,
  getTraceUsage,
  getOverview,
  getModelBreakdown,
  getFailureAnalytics,
  getTraceError,
  getTraceDecisions,
  getTraceDecisionQuality,
  getDecisionAnalytics,
  getCostTrend,
} from "./api";

import RunsList from "./components/RunsList";
import TraceDetail from "./components/TraceDetail";
import OverviewCards from "./components/OverviewCards";
import ModelBreakdown from "./components/ModelBreakdown";
import FailureAnalytics from "./components/FailureAnalytics";
import DecisionAnalytics from "./components/DecisionAnalytics";
import CostTrend from "./components/CostTrend";
import Alerts from "./components/Alerts";
import AgentPlayground from "./components/AgentPlayground";
import ChatAssistant from "./components/ChatAssistant";

import { AGENTS } from "./utils/assistant";

const SECTIONS = [
  { id: "playground", label: "Playground" },
  { id: "traces", label: "Traces" },
  { id: "overview", label: "Overview" },
  { id: "alerts", label: "Alerts" },
];

function App() {
  const [traces, setTraces] = useState([]);
  const [selectedTraceId, setSelectedTraceId] = useState(null);
  const [traceTree, setTraceTree] = useState(null);
  const [traceUsage, setTraceUsage] = useState(null);
  const [overview, setOverview] = useState(null);
  const [models, setModels] = useState([]);
  const [failures, setFailures] = useState(null);
  const [traceError, setTraceError] = useState(null);
  const [traceDecisions, setTraceDecisions] = useState(null);
  const [traceQuality, setTraceQuality] = useState(null);
  const [decisionAnalytics, setDecisionAnalytics] = useState(null);
  const [costTrend, setCostTrend] = useState(null);
  const [costTrendBucket, setCostTrendBucket] = useState("15m");
  const [alertFiringCount, setAlertFiringCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [section, setSection] = useState("playground");
  const [selectedAgentId, setSelectedAgentId] = useState(AGENTS[0].id);
  const [suggestedTask, setSuggestedTask] = useState(null);

  useEffect(() => {
    loadDashboard();
  }, []);

  async function loadDashboard() {
    setLoading(true);
    setError(null);

    try {
      const [
        tracesData,
        overviewData,
        modelsData,
        failuresData,
        decisionsData,
        costTrendData,
      ] = await Promise.all([
        getTraces(),
        getOverview(),
        getModelBreakdown(),
        getFailureAnalytics(),
        getDecisionAnalytics(),
        getCostTrend(costTrendBucket),
      ]);

      setTraces(tracesData);
      setOverview(overviewData);
      setModels(modelsData);
      setFailures(failuresData);
      setDecisionAnalytics(decisionsData);
      setCostTrend(costTrendData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectTrace(traceId) {
    setSelectedTraceId(traceId);
    setTraceTree(null);
    setTraceUsage(null);
    setTraceDecisions(null);
    setTraceQuality(null);
    setSection("traces");
    setLoading(true);
    setError(null);

    try {
      const [tree, usage, traceErrorData, decisionsData, qualityData] =
        await Promise.all([
          getTraceTree(traceId),
          getTraceUsage(traceId),
          getTraceError(traceId),
          getTraceDecisions(traceId),
          getTraceDecisionQuality(traceId),
        ]);

      setTraceTree(tree);
      setTraceUsage(usage);
      setTraceError(traceErrorData);
      setTraceDecisions(decisionsData);
      setTraceQuality(qualityData);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function handleBack() {
    setSelectedTraceId(null);
    setTraceTree(null);
    setTraceUsage(null);
    setTraceDecisions(null);
    setTraceQuality(null);
    setError(null);
  }

  async function handleCostTrendBucket(nextBucket) {
    if (nextBucket === costTrendBucket) {
      return;
    }
    setCostTrendBucket(nextBucket);
    try {
      const data = await getCostTrend(nextBucket);
      setCostTrend(data);
    } catch (err) {
      setError(err.message);
    }
  }

  function handleSendQuestion(question) {
    setSuggestedTask(question);
  }

  function handleSelectAgent(agentId) {
    setSelectedAgentId(agentId);
  }

  function renderMainContent() {
    if (section === "playground") {
      return (
        <AgentPlayground
          selectedAgentId={selectedAgentId}
          onSelectAgent={handleSelectAgent}
          onSendQuestion={handleSendQuestion}
        />
      );
    }

    if (section === "traces") {
      if (selectedTraceId) {
        return (
          <>
            {loading && <div className="message">Loading trace...</div>}
            {error && (
              <>
                <button
                  type="button"
                  className="back-button"
                  onClick={handleBack}
                >
                  ← Back to runs
                </button>
                <div className="message error">Failed to load trace: {error}</div>
              </>
            )}
            {!loading && !error && traceTree && (
              <TraceDetail
                data={traceTree}
                usage={traceUsage}
                error={traceError}
                decisions={traceDecisions}
                quality={traceQuality}
                onBack={handleBack}
              />
            )}
          </>
        );
      }

      return (
        <>
          <div className="page-heading">
            <div>
              <h2>Recent Runs</h2>
              <p>Recent agent executions captured by AgentOps.</p>
            </div>
            <button
              type="button"
              className="refresh-button"
              onClick={loadDashboard}
            >
              Refresh
            </button>
          </div>

          {loading && <div className="message">Loading traces...</div>}
          {error && (
            <div className="message error">Failed to load traces: {error}</div>
          )}
          {!loading && !error && traces.length === 0 && (
            <div className="message">No agent runs found.</div>
          )}
          {!loading && !error && traces.length > 0 && (
            <RunsList traces={traces} onSelectTrace={handleSelectTrace} />
          )}
        </>
      );
    }

    if (section === "overview") {
      return (
        <>
          <div className="page-heading">
            <div>
              <h2>Overview</h2>
              <p>Aggregated metrics and analytics across all traces.</p>
            </div>
            <button
              type="button"
              className="refresh-button"
              onClick={loadDashboard}
            >
              Refresh
            </button>
          </div>

          {loading && <div className="message">Loading analytics...</div>}
          {error && (
            <div className="message error">Failed to load analytics: {error}</div>
          )}
          {!loading && !error && (
            <>
              <OverviewCards overview={overview} />
              <ModelBreakdown models={models} />
              <FailureAnalytics failures={failures} />
              <DecisionAnalytics decisions={decisionAnalytics} />
              <CostTrend
                trend={costTrend}
                bucket={costTrendBucket}
                onBucketChange={handleCostTrendBucket}
              />
              <Alerts onFiringChange={setAlertFiringCount} />
            </>
          )}
        </>
      );
    }

    if (section === "alerts") {
      return (
        <>
          <div className="page-heading">
            <div>
              <h2>Alerts</h2>
              <p>Configure thresholds and view firing alerts.</p>
            </div>
          </div>
          <Alerts onFiringChange={setAlertFiringCount} />
        </>
      );
    }

    return null;
  }

  return (
    <div className="app">
      <aside className="app-sidebar">
        <div className="app-sidebar-brand">
          <h1>AgentOps</h1>
          <p>Agent observability</p>
        </div>

        <nav className="app-sidebar-nav">
          {SECTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`app-sidebar-link ${section === s.id ? "app-sidebar-link-active" : ""}`}
              onClick={() => {
                if (s.id === "traces") {
                  handleBack();
                }
                setSection(s.id);
              }}
            >
              <span className="app-sidebar-dot" aria-hidden="true" />
              <span>{s.label}</span>
              {s.id === "alerts" && alertFiringCount > 0 && (
                <span className="app-sidebar-badge">{alertFiringCount}</span>
              )}
            </button>
          ))}
        </nav>

        <div className="app-sidebar-footer">
          <p>Open the chat panel to run the selected agent.</p>
        </div>
      </aside>

      <main className="app-main">{renderMainContent()}</main>

      <ChatAssistant
        onSelectTrace={handleSelectTrace}
        selectedAgentId={selectedAgentId}
        suggestedTask={suggestedTask}
      />
    </div>
  );
}

export default App;
