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
import ErrorInspector from "./components/ErrorInspector";
import DecisionAnalytics from "./components/DecisionAnalytics";
import CostTrend from "./components/CostTrend";
import Alerts from "./components/Alerts";
import DecisionQuality from "./components/DecisionQuality";
import ChatAssistant from "./components/ChatAssistant";



function App() {
  const [traces, setTraces] = useState([]);

  const [selectedTraceId, setSelectedTraceId] =
    useState(null);

  const [traceTree, setTraceTree] =
    useState(null);

  const [traceUsage, setTraceUsage] =
    useState(null);

  const [overview, setOverview] = useState(null);

  const [models, setModels] = useState([]);

  const [failures, setFailures] = useState(null);

  const [traceError, setTraceError] = useState(null);

  const [traceDecisions, setTraceDecisions] =
    useState(null);

  const [traceQuality, setTraceQuality] = useState(null);

  const [decisionAnalytics, setDecisionAnalytics] =
    useState(null);

  const [costTrend, setCostTrend] = useState(null);
  const [costTrendBucket, setCostTrendBucket] =
    useState("15m");

  const [alertFiringCount, setAlertFiringCount] = useState(0);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState(null);


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


  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>AgentOps</h1>
          <p>Agent observability</p>
        </div>
        {alertFiringCount > 0 && !selectedTraceId && (
          <div className="header-alert-badge">
            {alertFiringCount} alert{alertFiringCount === 1 ? "" : "s"} firing
          </div>
        )}
      </header>

      <main className="content">


        {!selectedTraceId && (
          <>
            <div className="page-heading">
              <div>
                <h2>Recent Runs</h2>

                <p>
                  Recent agent executions captured by
                  AgentOps.
                </p>
              </div>

              <button
                type="button"
                className="refresh-button"
                onClick={loadDashboard}
              >
                Refresh
              </button>
            </div>

            <OverviewCards overview={overview} />

            <ModelBreakdown
              models={models}
            />
            <FailureAnalytics failures={failures} />
            <DecisionAnalytics decisions={decisionAnalytics} />
            <CostTrend
              trend={costTrend}
              bucket={costTrendBucket}
              onBucketChange={handleCostTrendBucket}
            />
            <Alerts onFiringChange={setAlertFiringCount} />
            {/* <ErrorInspector error={traceError} /> */}


            {loading && (
              <div className="message">
                Loading traces...
              </div>
            )}

            {error && (
              <div className="message error">
                Failed to load traces: {error}
              </div>
            )}

            {!loading &&
              !error &&
              traces.length === 0 && (
                <div className="message">
                  No agent runs found.
                </div>
              )}

            {!loading &&
              !error &&
              traces.length > 0 && (


                <RunsList
                  traces={traces}
                  onSelectTrace={handleSelectTrace}
                />
              )}
          </>
        )}


        {selectedTraceId && (
          <>
            {loading && (
              <div className="message">
                Loading trace...
              </div>
            )}

            {error && (
              <>
                <button
                  type="button"
                  className="back-button"
                  onClick={handleBack}
                >
                  ← Back to runs
                </button>

                <div className="message error">
                  Failed to load trace: {error}
                </div>
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
        )}

      </main>

      <ChatAssistant onSelectTrace={handleSelectTrace} />
    </div>
  );
}


export default App;