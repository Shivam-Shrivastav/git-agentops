function scoreClass(score) {
    const n = Number(score);
    if (Number.isNaN(n)) {
        return "score-unknown";
    }
    if (n <= 2) {
        return "score-low";
    }
    if (n === 3) {
        return "score-mid";
    }
    return "score-high";
}

function Stars({ score }) {
    const n = Number(score);
    if (Number.isNaN(n)) {
        return null;
    }
    return (
        <span className="score-stars" aria-label={`score ${n} of 5`}>
            {[1, 2, 3, 4, 5].map((i) => (
                <span
                    key={i}
                    className={i <= n ? "star filled" : "star"}
                >
                    ★
                </span>
            ))}
        </span>
    );
}

function DecisionQuality({ quality }) {
    if (!quality || !quality.evaluated) {
        return (
            <section className="decision-quality-section">
                <div className="section-heading">
                    <h3>Decision Quality</h3>
                    <span>LLM-judge evaluation</span>
                </div>
                <div className="message">
                    No decision-quality evaluation recorded for this
                    run. Enable{" "}
                    <code>AGENT_DECISION_JUDGE=1</code> on the agent
                    to score its decisions.
                </div>
            </section>
        );
    }

    const score = quality.score;
    const strengths = Array.isArray(quality.strengths)
        ? quality.strengths
        : [];
    const weaknesses = Array.isArray(quality.weaknesses)
        ? quality.weaknesses
        : [];

    return (
        <section className="decision-quality-section">
            <div className="section-heading">
                <h3>Decision Quality</h3>
                <span>LLM-judge evaluation</span>
            </div>

            <div className="decision-quality-card">
                <div className="dq-score-block">
                    <div
                        className={`dq-score-badge ${scoreClass(
                            score
                        )}`}
                    >
                        {score != null ? score : "—"}
                        <span className="dq-score-of">/5</span>
                    </div>
                    <Stars score={score} />
                    {quality.model && (
                        <div className="dq-meta">
                            judged by{" "}
                            <code>{quality.model}</code>
                        </div>
                    )}
                </div>

                {quality.summary && (
                    <p className="dq-summary">
                        {quality.summary}
                    </p>
                )}

                <div className="dq-columns">
                    {strengths.length > 0 && (
                        <div className="dq-column dq-strengths">
                            <h4>Strengths</h4>
                            <ul>
                                {strengths.map((s, i) => (
                                    <li key={i}>{s}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {weaknesses.length > 0 && (
                        <div className="dq-column dq-weaknesses">
                            <h4>Weaknesses</h4>
                            <ul>
                                {weaknesses.map((w, i) => (
                                    <li key={i}>{w}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            </div>
        </section>
    );
}

export default DecisionQuality;