import { useMemo } from "react";

const BUCKETS = ["15m", "hour", "day"];

const COLOR_INPUT = "#6366f1";
const COLOR_OUTPUT = "#06b6d4";

function formatTokens(value) {
    if (value == null) {
        return "0";
    }
    return Number(value).toLocaleString();
}

function formatCost(value) {
    if (value == null) {
        return "$0.0000";
    }
    return `$${Number(value).toFixed(4)}`;
}

function formatBucketLabel(iso, bucket) {
    if (!iso) {
        return "";
    }
    const d = new Date(iso);
    if (bucket === "day") {
        return d.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
        });
    }
    return d.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function buildPath(points) {
    if (points.length === 0) {
        return "";
    }
    return points
        .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
        .join(" ");
}

function buildArea(points, baseY) {
    if (points.length === 0) {
        return "";
    }
    const head = points
        .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x} ${p.y}`)
        .join(" ");
    const last = points[points.length - 1];
    const first = points[0];
    return `${head} L ${last.x} ${baseY} L ${first.x} ${baseY} Z`;
}

function CostTrend({ trend, bucket, onBucketChange }) {
    const series = trend?.series ?? [];
    const totals = trend?.totals ?? {};

    const avgTokensPerRun =
        totals.runs > 0
            ? Math.round(totals.total_tokens / totals.runs)
            : 0;

    // Chart geometry. We render with a fixed viewBox and let CSS
    // scale it to the container width.
    const W = 720;
    const H = 260;
    const padLeft = 52;
    const padRight = 16;
    const padTop = 16;
    const padBottom = 36;
    const plotW = W - padLeft - padRight;
    const plotH = H - padTop - padBottom;

    const { inputLine, outputLine, inputArea, yTicks, xLabels, hasData } =
        useMemo(() => {
            if (series.length === 0) {
                return {
                    inputLine: "",
                    outputLine: "",
                    inputArea: "",
                    yTicks: [],
                    xLabels: [],
                    hasData: false,
                };
            }

            const maxTokens = Math.max(
                1,
                ...series.map((p) => p.total_tokens)
            );

            const n = series.length;
            const xFor = (i) =>
                n === 1
                    ? padLeft + plotW / 2
                    : padLeft + (i / (n - 1)) * plotW;
            const yFor = (v) =>
                padTop + plotH - (v / maxTokens) * plotH;

            const inputPts = series.map((p, i) => ({
                x: xFor(i),
                y: yFor(p.input_tokens),
            }));
            const outputPts = series.map((p, i) => ({
                x: xFor(i),
                y: yFor(p.output_tokens),
            }));

            // 4 y-axis gridlines.
            const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
                y: padTop + plotH - f * plotH,
                value: Math.round(f * maxTokens),
            }));

            // x labels: show ~5 evenly spaced buckets.
            const labelCount = Math.min(5, n);
            const xLabels = [];
            for (let i = 0; i < labelCount; i++) {
                const idx =
                    labelCount === 1
                        ? 0
                        : Math.round(
                              (i / (labelCount - 1)) * (n - 1)
                          );
                xLabels.push({
                    x: xFor(idx),
                    label: formatBucketLabel(
                        series[idx].bucket,
                        bucket
                    ),
                });
            }

            return {
                inputLine: buildPath(inputPts),
                outputLine: buildPath(outputPts),
                inputArea: buildArea(
                    inputPts,
                    padTop + plotH
                ),
                yTicks,
                xLabels,
                hasData: true,
            };
        }, [series, bucket]);

    return (
        <section className="cost-trend-section">
            <div className="section-heading">
                <h3>Cost &amp; Token Trend</h3>
                <div className="bucket-selector">
                    {BUCKETS.map((b) => (
                        <button
                            key={b}
                            type="button"
                            className={`bucket-button ${
                                bucket === b ? "active" : ""
                            }`}
                            onClick={() => onBucketChange(b)}
                        >
                            {b}
                        </button>
                    ))}
                </div>
            </div>

            <div className="cost-trend-summary">
                <div className="usage-card">
                    <span className="summary-label">Total Cost</span>
                    <strong>{formatCost(totals.cost_usd)}</strong>
                </div>
                <div className="usage-card">
                    <span className="summary-label">Total Tokens</span>
                    <strong>
                        {formatTokens(totals.total_tokens)}
                    </strong>
                </div>
                <div className="usage-card">
                    <span className="summary-label">Runs</span>
                    <strong>{totals.runs ?? 0}</strong>
                </div>
                <div className="usage-card">
                    <span className="summary-label">
                        Avg Tokens / Run
                    </span>
                    <strong>{formatTokens(avgTokensPerRun)}</strong>
                </div>
            </div>

            <div className="cost-trend-chart-wrapper">
                {hasData ? (
                    <svg
                        className="cost-trend-chart"
                        viewBox={`0 0 ${W} ${H}`}
                        preserveAspectRatio="none"
                        role="img"
                        aria-label="Token usage over time"
                    >
                        {/* y gridlines + labels */}
                        {yTicks.map((t, i) => (
                            <g key={i}>
                                <line
                                    x1={padLeft}
                                    x2={W - padRight}
                                    y1={t.y}
                                    y2={t.y}
                                    className="chart-grid"
                                />
                                <text
                                    x={padLeft - 8}
                                    y={t.y + 4}
                                    className="chart-axis-label"
                                    textAnchor="end"
                                >
                                    {formatTokens(t.value)}
                                </text>
                            </g>
                        ))}

                        {/* input tokens area + line */}
                        <path
                            d={inputArea}
                            className="chart-area chart-area-input"
                        />
                        <path
                            d={inputLine}
                            className="chart-line chart-line-input"
                        />

                        {/* output tokens line */}
                        <path
                            d={outputLine}
                            className="chart-line chart-line-output"
                        />

                        {/* x labels */}
                        {xLabels.map((l, i) => (
                            <text
                                key={i}
                                x={l.x}
                                y={H - 12}
                                className="chart-axis-label"
                                textAnchor="middle"
                            >
                                {l.label}
                            </text>
                        ))}
                    </svg>
                ) : (
                    <div className="message">
                        No usage data yet for this window.
                    </div>
                )}
            </div>

            {hasData && (
                <div className="chart-legend">
                    <span className="legend-item">
                        <span
                            className="legend-swatch"
                            style={{ background: COLOR_INPUT }}
                        />
                        Input tokens
                    </span>
                    <span className="legend-item">
                        <span
                            className="legend-swatch"
                            style={{ background: COLOR_OUTPUT }}
                        />
                        Output tokens
                    </span>
                </div>
            )}
        </section>
    );
}

export default CostTrend;