from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.routes import chat, combine, datasets, health, projects, query, relationships, rqs


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.queue = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    yield
    await app.state.queue.aclose()


app = FastAPI(title="RQ Lens API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(datasets.router)
app.include_router(relationships.router)
app.include_router(query.router)
app.include_router(combine.router)
app.include_router(chat.router)
app.include_router(rqs.router)
