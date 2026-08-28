export function flattenTimeline(data) {
    if (!data) {
        return [];
    }

    const rows = [];

    const traceStart = new Date(
        data.trace.started_at
    ).getTime();

    function visit(span, level = 0) {
        const spanStart = new Date(
            span.started_at
        ).getTime();

        rows.push({
            span_id: span.span_id,
            name: span.name,
            span_type: span.span_type,
            status: span.status,

            level,

            start_ms: spanStart - traceStart,

            duration_ms: span.duration_ms ?? 0,
        });

        for (const child of span.children ?? []) {
            visit(child, level + 1);
        }
    }

    for (const root of data.children) {
        visit(root);
    }

    return rows;
}