function formatDuration(ms) {
  if (ms == null) {
    return "—";
  }

  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }

  return `${(ms / 1000).toFixed(2)} s`;
}


function formatNumber(value) {
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


function OverviewCards({ overview }) {
  if (!overview) {
    return null;
  }

  const cards = [
    {
      label: "Total Runs",
      value: formatNumber(
        overview.total_runs
      ),
    },
    {
      label: "Success Rate",
      value: `${Number(
        overview.success_rate ?? 0
      ).toFixed(2)}%`,
    },
    {
      label: "Avg Duration",
      value: formatDuration(
        overview.avg_duration_ms
      ),
    },
    {
      label: "LLM Calls",
      value: formatNumber(
        overview.llm_calls
      ),
    },
    {
      label: "Total Tokens",
      value: formatNumber(
        overview.total_tokens
      ),
    },
    {
      label: "Total Cost",
      value: formatCost(
        overview.cost_usd
      ),
    },
  ];

  return (
    <section className="overview-section">
      <div className="section-heading">
        <h2>Overview</h2>
        <span>Across all runs</span>
      </div>

      <div className="overview-grid">
        {cards.map((card) => (
          <div
            className="overview-card"
            key={card.label}
          >
            <span className="overview-label">
              {card.label}
            </span>

            <strong className="overview-value">
              {card.value}
            </strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export default OverviewCards;