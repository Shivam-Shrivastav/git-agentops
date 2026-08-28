function formatNumber(value) {
  return Number(value ?? 0).toLocaleString();
}

function formatPercent(value) {
  return `${Number(value ?? 0).toFixed(2)}%`;
}

function formatSpanType(value) {
  if (!value) {
    return "Unknown";
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function FailureAnalytics({ failures }) {
  if (!failures) {
    return null;
  }

  return (
    <section className="failure-section">
      <div className="section-heading">
        <h2>Failure Analytics</h2>

        <span>
          Run failures and internal recovery
        </span>
      </div>

      <h3 className="failure-subheading">
        Run Health
      </h3>

      <div className="failure-grid">
        <div className="failure-card">
          <span className="failure-label">
            FAILED RUNS
          </span>

          <strong className="failure-value">
            {formatNumber(failures.failed_runs)}
          </strong>
        </div>

        <div className="failure-card">
          <span className="failure-label">
            FAILURE RATE
          </span>

          <strong className="failure-value">
            {formatPercent(
              failures.failure_rate
            )}
          </strong>
        </div>

        <div className="failure-card">
          <span className="failure-label">
            RECOVERED RUNS
          </span>

          <strong className="failure-value">
            {formatNumber(
              failures.recovered_runs
            )}
          </strong>
        </div>
      </div>

      <h3 className="failure-subheading">
        Internal Errors
      </h3>

      <div className="failure-grid">
        <div className="failure-card">
          <span className="failure-label">
            AFFECTED RUNS
          </span>

          <strong className="failure-value">
            {formatNumber(
              failures.traces_with_span_failures
            )}
          </strong>
        </div>

        <div className="failure-card">
          <span className="failure-label">
            FAILED OPERATIONS
          </span>

          <strong className="failure-value">
            {formatNumber(
              failures.failed_spans
            )}
          </strong>
        </div>
      </div>

      {failures.by_span_type?.length > 0 && (
        <>
          <h3 className="failure-subheading">
            Failure Sources
          </h3>

          <div className="failure-sources">
            {failures.by_span_type.map(
              (item) => (
                <div
                  className="failure-source-row"
                  key={item.span_type}
                >
                  <div className="failure-source-name">
                    <span
                      className={
                        `span-badge ${item.span_type}`
                      }
                    >
                      {formatSpanType(
                        item.span_type
                      )}
                    </span>
                  </div>

                  <strong>
                    {formatNumber(
                      item.failures
                    )}
                  </strong>
                </div>
              )
            )}
          </div>
        </>
      )}
    </section>
  );
}

export default FailureAnalytics;