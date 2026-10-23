import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use an in-memory SQLite database for fast, isolated tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

from app.config import settings
settings.database_url = TEST_DB_URL
settings.groq_api_key = None  # Ensure test runs verify deterministic fallbacks

from app.db.database import Base, get_db
from app.main import app

engine_test = create_async_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = async_sessionmaker(bind=engine_test, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine_test.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session():
    async with TestingSessionLocal() as session:
        yield session
