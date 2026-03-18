"""FastAPI application factory with lifespan."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from claw_msg.server.database import connect_db, init_db
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
    try:
        yield
    finally:
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
