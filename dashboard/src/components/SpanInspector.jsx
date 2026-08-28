function formatDuration(durationMs) {
    if (durationMs == null) {
        return "—";
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
        return "—";
    }

    return Number(value).toLocaleString();
}


function formatCost(value) {
    if (value == null) {
        return "—";
    }

    return `$${Number(value).toFixed(4)}`;
}

function SpanInspector({ span, onClose }) {
    if (!span) {
        return (
            <aside className="span-inspector inspector-empty">
                <div>
                    <h3>Span Inspector</h3>
                    <p>
                        Select an operation from the execution tree to
                        inspect it.
                    </p>
                </div>
            </aside>
        );
    }

    return (
        <aside className="span-inspector">

            <div className="inspector-header">
                <div>
                    <div className="inspector-title-row">
                        <h3>{span.name}</h3>

                        <span
                            className={`status status-${span.status}`}
                        >
                            {span.status}
                        </span>
                    </div>

                    <span
                        className={`span-type type-${span.span_type}`}
                    >
                        {span.span_type}
                    </span>
                </div>

                <button
                    type="button"
                    className="inspector-close"
                    onClick={onClose}
                    aria-label="Close span inspector"
                >
                    ×
                </button>
            </div>


            <div className="inspector-section">
                <h4>Timing</h4>

                <div className="inspector-grid">
                    <div>
                        <span className="inspector-label">
                            Duration
                        </span>

                        <strong>
                            {formatDuration(span.duration_ms)}
                        </strong>
                    </div>

                    <div>
                        <span className="inspector-label">
                            Started
                        </span>

                        <strong>
                            {formatDate(span.started_at)}
                        </strong>
                    </div>

                    <div>
                        <span className="inspector-label">
                            Ended
                        </span>

                        <strong>
                            {formatDate(span.ended_at)}
                        </strong>
                    </div>
                </div>
            </div>

            {span.span_type === "llm" && (
                <div className="inspector-section">
                    <h4>LLM Usage</h4>

                    <div className="inspector-grid">
                        <div>
                            <span className="inspector-label">
                                Provider
                            </span>

                            <strong>
                                {span.payload?.provider ?? "—"}
                            </strong>
                        </div>

                        <div>
                            <span className="inspector-label">
                                Model
                            </span>

                            <strong>
                                {span.payload?.model ?? span.name ?? "—"}
                            </strong>
                        </div>

                        <div>
                            <span className="inspector-label">
                                Actual Model
                            </span>

                            <strong>
                                {span.payload?.actual_model ?? "—"}
                            </strong>
                        </div>
                    </div>


                    <div className="inspector-grid llm-token-grid">
                        <div>
                            <span className="inspector-label">
                                Input Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    span.payload?.input_tokens
                                )}
                            </strong>
                        </div>

                        <div>
                            <span className="inspector-label">
                                Output Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    span.payload?.output_tokens
                                )}
                            </strong>
                        </div>

                        <div>
                            <span className="inspector-label">
                                Total Tokens
                            </span>

                            <strong>
                                {formatTokens(
                                    span.payload?.total_tokens
                                )}
                            </strong>
                        </div>

                        <div>
                            <span className="inspector-label">
                                Cost
                            </span>

                            <strong>
                                {formatCost(
                                    span.payload?.cost_usd
                                )}
                            </strong>
                        </div>
                    </div>
                </div>
            )}


            {span.span_type === "planner" && (
                <div className="inspector-section inspector-decision">
                    <h4>Planner Decision</h4>

                    {span.payload?.thought && (
                        <p className="decision-thought">
                            {span.payload.thought}
                        </p>
                    )}

                    <div className="decision-chosen">
                        <span className="decision-chosen-label">
                            Chose
                        </span>
                        <span className="decision-chosen-value">
                            {span.payload?.chosen_action ?? "—"}
                        </span>
                    </div>

                    {Array.isArray(
                        span.payload?.candidates
                    ) &&
                        span.payload.candidates.length > 0 && (
                            <div className="decision-candidates">
                                <span className="decision-candidates-label">
                                    Candidates
                                </span>

                                <div className="candidate-chips">
                                    {span.payload.candidates.map(
                                        (candidate) => {
                                            let chipClass =
                                                "candidate-chip";

                                            if (
                                                candidate ===
                                                span.payload
                                                    ?.chosen_action
                                            ) {
                                                chipClass +=
                                                    " candidate-chosen";
                                            } else if (
                                                Array.isArray(
                                                    span.payload
                                                        ?.rejected_actions
                                                ) &&
                                                span.payload.rejected_actions.includes(
                                                    candidate
                                                )
                                            ) {
                                                chipClass +=
                                                    " candidate-rejected";
                                            }

                                            return (
                                                <span
                                                    key={candidate}
                                                    className={
                                                        chipClass
                                                    }
                                                >
                                                    {candidate}
                                                </span>
                                            );
                                        }
                                    )}
                                </div>
                            </div>
                        )}

                    <div className="inspector-grid">
                        {span.payload?.confidence != null && (
                            <div>
                                <span className="inspector-label">
                                    Confidence
                                </span>
                                <strong>
                                    {formatTokens(
                                        span.payload.confidence
                                    )}
                                </strong>
                            </div>
                        )}

                        {span.payload?.iteration != null && (
                            <div>
                                <span className="inspector-label">
                                    Iteration
                                </span>
                                <strong>
                                    {span.payload.iteration}
                                </strong>
                            </div>
                        )}
                    </div>

                    {span.payload?.error && (
                        <p className="decision-thought">
                            {span.payload.error}
                        </p>
                    )}
                </div>
            )}


            <div className="inspector-section">
                <h4>Identifiers</h4>

                <div className="identifier">
                    <span className="inspector-label">
                        Span ID
                    </span>

                    <code>{span.span_id}</code>
                </div>

                <div className="identifier">
                    <span className="inspector-label">
                        Parent Span ID
                    </span>

                    <code>
                        {span.parent_span_id ?? "—"}
                    </code>
                </div>

                <div className="identifier">
                    <span className="inspector-label">
                        Trace ID
                    </span>

                    <code>{span.trace_id}</code>
                </div>
            </div>


            <div className="inspector-section">
                <h4>Payload</h4>

                {span.payload &&
                    Object.keys(span.payload).length > 0 ? (
                    <pre className="payload">
                        {JSON.stringify(span.payload, null, 2)}
                    </pre>
                ) : (
                    <div className="empty-payload">
                        No payload captured.
                    </div>
                )}
            </div>

           

        </aside>
    );
}


export default SpanInspector;