function formatDuration(durationMs) {
  if (durationMs == null) {
    return "—";
  }

  if (durationMs < 1000) {
    return `${Math.round(durationMs)} ms`;
  }

  return `${(durationMs / 1000).toFixed(2)} s`;
}


function SpanNode({
  span,
  depth = 0,
  selectedSpanId,
  onSelectSpan,
}) {
  const children = span.children ?? [];

  const selected =
    selectedSpanId === span.span_id;

  return (
    <div className="span-tree">

      <button
        type="button"
        className={`span-row span-button ${
          selected ? "span-selected" : ""
        }`}
        style={{
          paddingLeft: `${18 + depth * 28}px`,
        }}
        onClick={() => onSelectSpan(span)}
      >

        <div className="span-main">

          {depth > 0 && (
            <span className="tree-connector">
              └
            </span>
          )}

          <span
            className={`span-type type-${span.span_type}`}
          >
            {span.span_type}
          </span>

          <span className="span-name">
            {span.name}
          </span>

        </div>


        <div className="span-info">

          <span
            className={`status status-${span.status}`}
          >
            {span.status}
          </span>

          <span className="span-duration">
            {formatDuration(span.duration_ms)}
          </span>

        </div>

      </button>


      {children.map((child) => (
        <SpanNode
          key={child.span_id}
          span={child}
          depth={depth + 1}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
        />
      ))}

    </div>
  );
}


export default SpanNode;