import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import datasets, failures, knowledge, monitoring, reviews
from app.api.routes import router
from app.core.middleware import safeguards
from app.monitoring.telemetry import configure

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    configure()
    yield


app = FastAPI(
    title="AURA API",
    version="1.0.0",
    description="Local AI reliability and evaluation",
    lifespan=lifespan,
)
app.middleware("http")(safeguards)
for routes in (
    router,
    datasets.router,
    knowledge.router,
    reviews.router,
    failures.router,
    monitoring.router,
):
    app.include_router(routes)
