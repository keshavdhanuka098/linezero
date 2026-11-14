from fastapi import APIRouter

from app.api.routes import counters, intelligence, queues, simulation, twin

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(queues.router)
api_router.include_router(counters.router)
api_router.include_router(simulation.router)
api_router.include_router(intelligence.predictions)
api_router.include_router(intelligence.bottlenecks)
api_router.include_router(intelligence.optimization)
api_router.include_router(intelligence.analytics)
api_router.include_router(intelligence.reports)
api_router.include_router(twin.router)
