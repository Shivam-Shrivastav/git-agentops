import { useState } from "react";

import SpanNode from "./SpanNode";
import SpanInspector from "./SpanInspector";
import ErrorInspector from "./ErrorInspector";
import ExecutionTimeline from "./ExecutionTimeline";
import DecisionTimeline from "./DecisionTimeline";
import DecisionQuality from "./DecisionQuality";
import { flattenTimeline } from "../utils/timeline";


function formatDuration(durationMs) {
    if (durationMs == null) {
        return "Running";
    }

    if (durationMs < 1000) {
        return `${Math.round(durationMs)} ms`;
    }

    return `${(durationMs / 1000).toFixed(2)} s`;
}


function formatDate(timestamp) {
    if (!timestamp) {
        return "—";
    }

    return new Date(timestamp).toLocaleString();
}

function formatTokens(value) {
    if (value == null) {
        return "0";
    }

    return value.toLocaleString();
}


function formatCost(value) {
    if (value == null) {
        return "$0.0000";
    }

    return `$${Number(value).toFixed(4)}`;
}


function TraceDetail({ data,
    usage,
    error,
    decisions,
    quality,
    onBack, }) {
    const { trace, children } = data;

    const [selectedSpan, setSelectedSpan] =
        useState(null);


    function handleSpanSelect(spanId) {
        if (!data) {
            return;
        }

        function findSpan(spans) {
            for (const span of spans) {
                if (span.span_id === spanId) {
                    return span;
                }

                const child = findSpan(span.children ?? []);

                if (child) {
                    return child;
                }
            }

            return null;
        }

        const span = findSpan(data.children);

        setSelectedSpan(span);
    }

    const timelineRows = data
        ? flattenTimeline(data)
        : [];


    return (
        <div>

            <button
                type="button"
                className="back-button"
                onClick={onBack}
            >
                ← Back to runs
            </button>


            <div className="trace-heading">

                <div>

                    <div className="trace-title-row">

                        <h2>{trace.name}</h2>

                        <span
                            className={`status status-${trace.status}`}
                        >
                            {trace.status}
                        </span>

                    </div>

                    <div className="trace-id detail-trace-id">
                        {trace.trace_id}
                    </div>

                    {trace.user_query && (
                        <div className="trace-user-query">
                            <span className="trace-user-query-label">
                                User ask
                            </span>
                            <span className="trace-user-query-text">
                                {trace.user_query}
                            </span>
                        </div>
                    )}

                </div>

            </div>


            <div className="trace-summary">

                <div className="summary-item">
                    <span className="summary-label">
                        Duration
                    </span>

                    <strong>
                        {formatDuration(trace.duration_ms)}
                    </strong>
                </div>


                <div className="summary-item">
                    <span className="summary-label">
                        Started
                    </span>

                    <strong>
                        {formatDate(trace.started_at)}
                    </strong>
                </div>


                <div className="summary-item">
                    <span className="summary-label">
                        Ended
                    </span>

                    <strong>
                        {formatDate(trace.ended_at)}
                    </strong>
                </div>

            </div>

            {usage && (
                <section className="usage-section">

                    <div className="section-heading">
                        <h3>LLM Usage</h3>

                        <span>
                            Aggregated across this trace
                        </span>
                    </div>


                    <div className="usage-grid">

                        <div className="usage-card">
                            <span className="summary-label">
                                LLM Calls
                            </span>

                            <strong>
                                {usage.llm_calls}
                            </strong>
                        </div>


                        <div className="usage-card">
                            <span className="summary-label">
                                Total Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    usage.total_tokens
                                )}
                            </strong>
                        </div>


                        <div className="usage-card">
                            <span className="summary-label">
                                Input Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    usage.input_tokens
                                )}
                            </strong>
                        </div>


                        <div className="usage-card">
                            <span className="summary-label">
                                Output Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    usage.output_tokens
                                )}
                            </strong>
                        </div>


                        <div className="usage-card">
                            <span className="summary-label">
                                LLM Time
                            </span>

                            <strong>
                                {formatDuration(
                                    usage.llm_duration_ms
                                )}
                            </strong>
                        </div>


                        <div className="usage-card">
                            <span className="summary-label">
                                Cost
                            </span>

                            <strong>
                                {formatCost(
                                    usage.cost_usd
                                )}
                            </strong>
                        </div>

                    </div>

                </section>
            )}

            <DecisionTimeline decisions={decisions} />

            {quality && (
                <DecisionQuality quality={quality} />
            )}

            <ErrorInspector error={error} />

            <ExecutionTimeline
                rows={timelineRows}
                selectedSpanId={selectedSpan?.span_id}
                onSelect={handleSpanSelect}
            />


            <section className="execution-section">

                <div className="section-heading">

                    <h3>Execution</h3>

                    <span>
                        {children.length} top-level operations
                    </span>

                </div>


                {children.length === 0 ? (

                    <div className="message">
                        No spans captured for this run.
                    </div>

                ) : (

                    <div
                        className={`trace-workspace ${selectedSpan
                            ? "inspector-open"
                            : ""
                            }`}
                    >

                        <div className="execution-tree">

                            {children.map((span) => (
                                <SpanNode
                                    key={span.span_id}
                                    span={span}
                                    selectedSpanId={
                                        selectedSpan?.span_id
                                    }
                                    onSelectSpan={setSelectedSpan}
                                />
                            ))}

                        </div>


                        {selectedSpan && (

                            <SpanInspector
                                span={selectedSpan}
                                onClose={() =>
                                    setSelectedSpan(null)
                                }
                            />

                        )}

                    </div>

                )}

            </section>

        </div>
    );
}


export default TraceDetail;