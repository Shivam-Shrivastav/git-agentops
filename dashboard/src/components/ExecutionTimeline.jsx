export default function ExecutionTimeline({ rows, selectedSpan,
    onSelect, }) {
    if (!rows || rows.length === 0) {
        return null;
    }

    const totalDuration = Math.max(
        ...rows.map(
            (r) => r.start_ms + r.duration_ms
        )
    );

    const totalSeconds =
        Math.ceil(totalDuration / 1000);

    return (
        <section className="timeline-section">
            <div className="section-header">
                <h2>Execution Timeline</h2>
                <span>{rows.length} spans</span>
            </div>

            <div className="timeline-axis-row">

                <div></div>

                <div></div>

                <div className="timeline-axis">
                    <span>0 ms</span>

                    <span>
                        {Math.round(totalSeconds / 3)} s
                    </span>

                    <span>
                        {Math.round(totalSeconds * 2 / 3)} s
                    </span>

                    <span>{totalSeconds} s</span>
                </div>

            </div>

            <div className="timeline-table">
                <div className="timeline-header">
                    <div>Name</div>
                    <div>Type</div>
                    <div>Timeline</div>
                </div>

                {rows.map((row) => (
                    <div
                        key={row.span_id}
                        className="timeline-row"
                    >
                        <div
                            style={{
                                paddingLeft: `${row.level * 20}px`,
                            }}
                        >
                            {row.name}
                        </div>

                        <div>{row.span_type}</div>

                        <div className="timeline-bar-container">
                            <div

                                className={`timeline-bar ${row.span_type} ${selectedSpan === row.span_id
                                        ? "selected"
                                        : ""
                                    }`}
                                onClick={() => onSelect?.(row.span_id)}
                                style={{
                                    left: `${(row.start_ms / totalDuration) * 100
                                        }%`,

                                    width: `${Math.max(
                                        (row.duration_ms / totalDuration) * 100,
                                        0.5
                                    )
                                        }%`,
                                }}
                            />
                        </div>
                    </div>
                ))}
            </div>
        </section>
    );
}