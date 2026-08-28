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


function RunsList({ traces, onSelectTrace }) {
  return (
    <div className="runs">
      <div className="run-row run-header">
        <span>Agent</span>
        <span>Status</span>
        <span>Duration</span>
        <span>Started</span>
      </div>

      {traces.map((trace) => (
        <button
          type="button"
          className="run-row run-button"
          key={trace.trace_id}
          onClick={() => onSelectTrace(trace.trace_id)}
        >
          <div className="agent">
            <strong>{trace.name}</strong>

            <span className="trace-id">
              {trace.trace_id}
            </span>
          </div>

          <div>
            <span
              className={`status status-${trace.status}`}
            >
              {trace.status}
            </span>
          </div>

          <span>
            {formatDuration(trace.duration_ms)}
          </span>

          <span className="date">
            {formatDate(trace.started_at)}
          </span>
        </button>
      ))}
    </div>
  );
}


export default RunsList;