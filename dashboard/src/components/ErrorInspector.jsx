function ErrorInspector({ error }) {
  if (!error) {
    return null;
  }

  const isSuccess = error.status === "success";

  return (
    <section className="error-section">
      <div className="section-heading">
        <h2>Error Inspector</h2>

        <span>
          Failure diagnostics
        </span>
      </div>

      {isSuccess ? (
        <div className="success-card">
          <strong>✓ Trace completed successfully</strong>

          <p>
            No error information was recorded for this trace.
          </p>
        </div>
      ) : (
        <div className="error-card">
          <div className="error-row">
            <span>Failure Stage</span>

            <strong>
              {error.failure_stage}
            </strong>
          </div>

          <div className="error-row">
            <span>Error Type</span>

            <strong>
              {error.error_type}
            </strong>
          </div>

          <div className="error-row">
            <span>Message</span>

            <code className="error-message">
              {error.error_message}
            </code>
          </div>
        </div>
      )}
    </section>
  );
}

export default ErrorInspector;