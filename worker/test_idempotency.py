from uuid import uuid4
from datetime import datetime, timezone

from worker import process_event


event_id = str(uuid4())
trace_id = str(uuid4())
span_id = str(uuid4())


event = {
    "event_id": event_id,
    "trace_id": trace_id,
    "span_id": span_id,
    "parent_span_id": None,
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "event_type": "agent.start",
    "name": "idempotency-test",
    "status": "success",
    "duration_ms": None,
    "payload": {
        "test": True,
    },
}


first = process_event(event)

print(
    "First processing:",
    first,
)


second = process_event(event)

print(
    "Second processing:",
    second,
)