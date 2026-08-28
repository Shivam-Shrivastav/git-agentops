function formatNumber(value) {
  if (value == null) {
    return "0";
  }

  return Number(value).toLocaleString();
}


function formatDuration(ms) {
  if (ms == null) {
    return "—";
  }

  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }

  return `${(ms / 1000).toFixed(2)} s`;
}


function formatCost(value) {
  if (value == null) {
    return "$0.0000";
  }

  return `$${Number(value).toFixed(4)}`;
}


function ModelBreakdown({ models }) {
  if (!models?.length) {
    return null;
  }

  return (
    <section className="model-section">
      <div className="section-heading">
        <h2>Model Breakdown</h2>
        <span>LLM usage by actual model</span>
      </div>

      <div className="model-table-wrapper">
        <table className="model-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Provider</th>
              <th>Calls</th>
              <th>Input</th>
              <th>Output</th>
              <th>Total Tokens</th>
              <th>Avg Latency</th>
              <th>Cost</th>
            </tr>
          </thead>

          <tbody>
            {models.map((model) => (
              <tr
                key={`${model.provider}-${model.model}`}
              >
                <td className="model-name">
                  {model.model}
                </td>

                <td>{model.provider}</td>

                <td>
                  {formatNumber(model.calls)}
                </td>

                <td>
                  {formatNumber(
                    model.input_tokens
                  )}
                </td>

                <td>
                  {formatNumber(
                    model.output_tokens
                  )}
                </td>

                <td>
                  {formatNumber(
                    model.total_tokens
                  )}
                </td>

                <td>
                  {formatDuration(
                    model.avg_duration_ms
                  )}
                </td>

                <td>
                  {formatCost(
                    model.cost_usd
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default ModelBreakdown;