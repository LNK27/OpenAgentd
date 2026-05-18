from pathlib import Path

import pytest
import pytest_asyncio
from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.agent.providers.zai.zai import ZAIProvider

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# Me keep engine ref so cleanup fixture can access it
_test_engine = None


# ---------------------------------------------------------------------------
# Test fixture config files — .tests/ is gitignored, so the fixture below is
# materialised on-demand the first time the test session runs. TitleGeneration
# still loads its prompt from a file; SummarizationHook now uses in-code
# constants. pytest.ini pins the four XDG dirs to .tests/{data,config,state,cache}.
# ---------------------------------------------------------------------------

_TITLE_GENERATION_FIXTURE = """\
---
# Test-only title generation config.
enabled: true
wait_timeout_seconds: 0.0
---

You are a title generator. Output a short conversation title and nothing else.
This prompt is used by the test suite only.
"""


@pytest.fixture(scope="session", autouse=True)
def _materialise_openagentd_config(tmp_path_factory):
    """Ensure ``{CONFIG_DIR}/title_generation.md`` exists.

    CI and local runs both point the four XDG dirs at ``.tests/*`` (see
    ``pytest.ini``). The directory is gitignored by design, so the config
    file must be generated before any agent-building code runs.
    """
    from app.core.config import settings

    # settings already resolved — CONFIG_DIR = .tests/config.
    config_dir = Path(settings.OPENAGENTD_CONFIG_DIR)
    config_dir.mkdir(parents=True, exist_ok=True)

    title = config_dir / "title_generation.md"
    if not title.exists():
        title.write_text(_TITLE_GENERATION_FIXTURE)

    yield


def set_openagentd_dirs(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """Point all four XDG dirs at subdirectories of ``root``.

    Shared by tests that need isolated XDG roots.
    Creates ``{root}/{data,config,state,cache}`` lazily by setting env vars;
    the directories themselves are created by whatever code writes into them.
    """
    monkeypatch.setenv("OPENAGENTD_DATA_DIR", str(root / "data"))
    monkeypatch.setenv("OPENAGENTD_CONFIG_DIR", str(root / "config"))
    monkeypatch.setenv("OPENAGENTD_STATE_DIR", str(root / "state"))
    monkeypatch.setenv("OPENAGENTD_CACHE_DIR", str(root / "cache"))


@pytest.fixture
def api_key():
    return "test_key"


@pytest.fixture
def zai_provider(api_key):
    return ZAIProvider(api_key=api_key, model="m")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """Create schema once per session in-memory and redirect app.core.db to it."""
    global _test_engine
    import app.core.db as _db_module

    engine = create_async_engine(
        _TEST_DB_URL,
        connect_args={"check_same_thread": False},
    )
    _test_engine = engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    # Redirect the shared app engine / session factory to the in-memory DB
    _orig_engine = _db_module.engine
    _orig_factory = _db_module.async_session_factory
    _db_module.engine = engine
    _db_module.async_session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    yield

    _db_module.engine = _orig_engine
    _db_module.async_session_factory = _orig_factory
    await engine.dispose()
    _test_engine = None


@pytest_asyncio.fixture(autouse=True)
async def clean_db(setup_db):
    """Me wipe all rows between tests — keep schema, clear data."""
    yield
    if _test_engine is None:
        return
    async with _test_engine.begin() as conn:
        # Me order matters: messages first (FK child), then sessions (FK parent)
        for table in reversed(SQLModel.metadata.sorted_tables):
            try:
                await conn.execute(text(f"DELETE FROM {table.name}"))
            except Exception:
                # Table might not exist in test database
                pass
