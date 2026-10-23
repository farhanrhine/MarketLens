import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_alerts import router as alerts_router
from app.api.routes_competitors import router as competitors_router
from app.api.routes_demo import router as demo_router
from app.api.routes_scans import router as scans_router
from app.config import settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    await init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    description="Competitor Monitoring Alert Tool with 3-tier crawler, content delta engine, pricing tracking, and Groq AI enrichment.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(competitors_router)
app.include_router(scans_router)
app.include_router(demo_router)
app.include_router(alerts_router)

# Mount Static UI directory
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)


from fastapi.responses import FileResponse


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    fav_path = os.path.join(static_dir, "favicon.svg")
    return FileResponse(fav_path, media_type="image/svg+xml")


app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def start():
    """CLI entrypoint for running via uv run or uvicorn."""
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)


if __name__ == "__main__":
    start()
