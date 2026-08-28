from fastapi import FastAPI
from typing import List

from .queue import enqueue_event, enqueue_events
from .schemas import EventIn
from app.routes.traces import router as traces_router
from fastapi.middleware.cors import CORSMiddleware
from app.routes.analytics import router as analytics_router
from app.routes.spans import router as spans_router
from app.routes.alerts import router as alerts_router


app = FastAPI(
    title="AgentOps Ingestion API",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(traces_router)
app.include_router(analytics_router)
app.include_router(spans_router)
app.include_router(alerts_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
    }


@app.post("/events")
def ingest_event(event: EventIn) -> dict[str, str]:
    enqueue_event(
        event.model_dump(mode="json")
    )

    return {
        "status": "accepted",
    }


@app.post("/events/batch")
def ingest_events_batch(events: List[EventIn]) -> dict[str, object]:
    """
    Accept a batch of events and enqueue them in a single Redis
    pipeline. Used by the SDK's batched HTTPEmitter.
    """
    count = enqueue_events(
        [event.model_dump(mode="json") for event in events]
    )

    return {
        "status": "accepted",
        "count": count,
    }