function DecisionAnalytics({ decisions }) {
    if (!decisions || decisions.total_decisions === 0) {
        return null;
    }

    const { distribution, rejection, total_decisions } = decisions;

    const maxCount = Math.max(
        1,
        ...distribution.map((d) => d.count)
    );

    // Only show actions that were actually rejected at least once.
    const topRejected = rejection
        .filter((r) => r.rejected > 0)
        .slice(0, 5);

    return (
        <section className="decision-analytics-section">
            <div className="section-heading">
                <h3>Decision Distribution</h3>
                <span>
                    {total_decisions} planner decision
                    {total_decisions === 1 ? "" : "s"}
                </span>
            </div>

            <div className="decision-distribution">
                {distribution.map((d) => (
                    <div
                        key={d.action}
                        className="decision-distribution-row"
                    >
                        <span className="decision-distribution-name">
                            {d.action}
                        </span>

                        <div className="decision-distribution-bar-track">
                            <div
                                className="decision-distribution-bar"
                                style={{
                                    width: `${(d.count / maxCount) * 100}%`,
                                }}
                            />
                        </div>

                        <span className="decision-distribution-count">
                            {d.count}
                            <span className="decision-distribution-pct">
                                {" "}
                                ({d.pct}%)
                            </span>
                        </span>
                    </div>
                ))}
            </div>

            {topRejected.length > 0 && (
                <div className="decision-sources">
                    <span className="decision-candidates-label">
                        Most often offered but rejected
                    </span>

                    {topRejected.map((r) => (
                        <div
                            key={r.action}
                            className="decision-rejection-stats"
                        >
                            <span className="decision-distribution-name">
                                {r.action}
                            </span>
                            {" — rejected "}
                            {r.rejected}
                            {" of "}
                            {r.offered} time
                            {r.offered === 1 ? "" : "s"}
                            {r.chosen > 0
                                ? ` (chosen ${r.chosen})`
                                : " (never chosen)"}
                        </div>
                    ))}
                </div>
            )}
        </section>
    );
}

export default DecisionAnalytics;