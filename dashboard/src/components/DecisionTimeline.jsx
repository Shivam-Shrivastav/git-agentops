function formatDuration(durationMs) {
    if (durationMs == null) {
        return "—";
    }

    if (durationMs < 1000) {
        return `${Math.round(durationMs)} ms`;
    }

    return `${(durationMs / 1000).toFixed(2)} s`;
}

function formatConfidence(value) {
    if (value == null) {
        return null;
    }

    return `${Number(value).toFixed(2)}`;
}

function DecisionTimeline({ decisions }) {
    if (!decisions || decisions.length === 0) {
        return (
            <section className="decision-section">
                <div className="section-heading">
                    <h3>Planner Decisions</h3>
                    <span>No planner steps captured</span>
                </div>
                <div className="message">
                    No reasoning steps recorded for this run.
                </div>
            </section>
        );
    }

    return (
        <section className="decision-section">
            <div className="section-heading">
                <h3>Planner Decisions</h3>
                <span>
                    {decisions.length} reasoning step
                    {decisions.length === 1 ? "" : "s"} —
                    candidates offered vs. action chosen
                </span>
            </div>

            <div className="decision-timeline">
                {decisions.map((decision, index) => {
                    const chosen = decision.chosen_action;
                    const rejected = Array.isArray(
                        decision.rejected_actions
                    )
                        ? decision.rejected_actions
                        : [];
                    const candidates = Array.isArray(
                        decision.candidates
                    )
                        ? decision.candidates
                        : [];

                    const isError = decision.status === "error";
                    const budgetHit = decision.budget_exceeded === true;
                    const usage = decision.token_usage || {};

                    return (
                        <div
                            key={decision.span_id}
                            className={`decision-step ${
                                isError ? "decision-step-error" : ""
                            } ${budgetHit ? "decision-step-budget" : ""}`}
                        >
                            <div className="decision-step-header">
                                <span className="decision-step-index">
                                    Step {decision.iteration ?? index + 1}
                                </span>

                                <span className="decision-step-duration">
                                    {formatDuration(
                                        decision.duration_ms
                                    )}
                                </span>

                                {formatConfidence(
                                    decision.confidence
                                ) != null && (
                                    <span className="decision-step-confidence">
                                        confidence{" "}
                                        {formatConfidence(
                                            decision.confidence
                                        )}
                                    </span>
                                )}

                                {usage.total != null && (
                                    <span className="decision-step-tokens">
                                        {Number(usage.total).toLocaleString()}{" "}
                                        tokens
                                    </span>
                                )}

                                {isError && (
                                    <span className="status status-error">
                                        planner error
                                    </span>
                                )}

                                {budgetHit && (
                                    <span className="status status-error">
                                        budget exceeded
                                    </span>
                                )}
                            </div>

                            {decision.thought && (
                                <p className="decision-thought">
                                    {decision.thought}
                                </p>
                            )}

                            <div className="decision-chosen">
                                <span className="decision-chosen-label">
                                    Chose
                                </span>
                                <span className="decision-chosen-value">
                                    {chosen ?? "—"}
                                </span>
                            </div>

                            {decision.final_response && (
                                <p className="decision-final-response">
                                    {decision.final_response}
                                </p>
                            )}

                            {candidates.length > 0 && (
                                <div className="decision-candidates">
                                    <span className="decision-candidates-label">
                                        Candidates
                                    </span>

                                    <div className="candidate-chips">
                                        {candidates.map(
                                            (candidate) => {
                                let chipClass = "candidate-chip";

                                if (candidate === chosen) {
                                    chipClass +=
                                        " candidate-chosen";
                                } else if (
                                    rejected.includes(candidate)
                                ) {
                                    chipClass +=
                                        " candidate-rejected";
                                }

                                return (
                                    <span
                                        key={candidate}
                                        className={chipClass}
                                    >
                                        {candidate}
                                    </span>
                                );
                                            }
                                        )}
                                    </div>
                                </div>
                            )}

                            {decision.error && (
                                <p className="decision-thought">
                                    {decision.error}
                                </p>
                            )}
                        </div>
                    );
                })}
            </div>
        </section>
    );
}

export default DecisionTimeline;