"""FastAPI application factory with lifespan."""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claw_msg.server.config import OFFLINE_QUEUE_CLEANUP_INTERVAL_SECONDS
from claw_msg.server.database import connect_db, init_db
from claw_msg.server.offline_queue import run_cleanup_loop
from claw_msg.server.routes_agents import router as agents_router
from claw_msg.server.routes_messages import router as messages_router
from claw_msg.server.routes_rooms import router as rooms_router
from claw_msg.server.routes_contacts import router as contacts_router
from claw_msg.server.routes_ws import router as ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await connect_db()
    await init_db(db)
    app.state.db = db
    cleanup_task = asyncio.create_task(
        run_cleanup_loop(db, OFFLINE_QUEUE_CLEANUP_INTERVAL_SECONDS)
    )
    app.state.offline_queue_cleanup_task = cleanup_task
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        await db.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="claw-msg",
        description="Agent-to-agent messaging layer",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(agents_router)
    app.include_router(messages_router)
    app.include_router(rooms_router)
    app.include_router(contacts_router)
    app.include_router(ws_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
