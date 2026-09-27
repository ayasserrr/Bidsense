"""Bidsense API entry point.

Lives at the repo root, next to `.env` and `alembic.ini`, so the whole backend
is operated from a single working directory:

    alembic upgrade head
    uvicorn main:app --host 0.0.0.0 --port 8004

The application package itself is `src/`, whose modules import one another by
top-level name (`from helpers import ...`). Putting `src` on `sys.path` here -
before any of those imports run - is what lets this file sit at the root
without rewriting every import in the codebase, and mirrors what
`alembic.ini`'s `prepend_sys_path = src` already does for migrations.
"""

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import logging  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from db import engine  # noqa: E402
from helpers import get_settings, gov_context  # noqa: E402
from routes.auth import auth_router  # noqa: E402
from routes.base import base_router  # noqa: E402
from routes.compare import compare_router  # noqa: E402
from routes.completeness import completeness_router  # noqa: E402
from routes.dashboard import dashboard_router  # noqa: E402
from routes.events import events_router  # noqa: E402
from routes.extract import extract_router  # noqa: E402
from routes.jobs import jobs_router, queue_router  # noqa: E402
from routes.offers import offers_router  # noqa: E402
from routes.parse import parse_router  # noqa: E402
from routes.persist import persist_router  # noqa: E402
from routes.rates import rates_router  # noqa: E402
from routes.sanity_check import sanity_check_router  # noqa: E402
from routes.summary import summary_router  # noqa: E402
from routes.taxonomy import taxonomy_router  # noqa: E402
from routes.upload import upload_router  # noqa: E402
from routes.verification import verification_router  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Names this app in the gateway's spend logs. Must be set before any LLM
    # call; it is stable by contract, because changing it would split this
    # app's usage history across two names on the governance dashboard.
    gov_context.configure(application=settings.LLM_APPLICATION_NAME)
    await _startup_tasks()
    # The queue's dispatcher, started only after stale jobs have been settled -
    # otherwise it would count a run left `running` by the previous process
    # against the slots and never start anything.
    from pipeline import runner

    runner.start_dispatcher()
    yield
    # Stop the dispatcher and any job still running before the loop closes.
    # Without this asyncpg connections are torn down mid-query and the shutdown
    # logs fill with tracebacks that look like a fault and are not.
    await runner.shutdown()
    await engine.dispose()


async def _startup_tasks() -> None:
    """Seed the local admin, the checklist and the taxonomy, and clear out any
    job left running by a previous process.

    Every step is non-fatal and each is caught on its own. Migrations are a
    separate operator step (`alembic upgrade head`), so on a fresh database
    these run before the tables exist - failing startup there would make a
    missing migration look like a broken application. One failing step must not
    skip the others, which is why they are not in a single try block.

    Reaping is not optional housekeeping: nothing resumes a run that was
    already in flight, and a row left `running` would be polled forever by a
    progress bar that can never move. A job that was only WAITING keeps its
    place in the queue - see `JobController.reap_stale_jobs`.
    """
    from controllers import AuthController, CompletenessController, JobController, TaxonomyController
    from db import async_session_factory

    async def run(label: str, work) -> None:
        try:
            async with async_session_factory() as db:
                result = await work(db)
            # seed_taxonomy returns a (nodes, aliases) tuple, and a plain
            # truthiness test calls (0, 0) a change - logging "taxonomy ->
            # (0, 0)" on every restart of an already-seeded deployment.
            changed = any(result) if isinstance(result, tuple) else bool(result)
            if changed:
                logger.info("startup: %s -> %s", label, result)
        except Exception as exc:
            logger.warning(
                "startup: %s skipped (%s) - run `alembic upgrade head` if its table does not "
                "exist yet",
                label,
                exc,
            )

    await run("bootstrap admin", lambda db: AuthController(db).bootstrap_admin())
    await run("completeness checklist", lambda db: CompletenessController(db).seed_requirements())
    await run("taxonomy", lambda db: TaxonomyController(db).seed_taxonomy())
    await run("stale jobs", lambda db: JobController(db).reap_stale_jobs())


settings = get_settings()

# uvicorn installs handlers for its own loggers only, leaving the root logger
# at WARNING - so without this every logger.info() in the application is
# dropped, including the per-model-call timing lines. Configured here, once,
# before the app exists.
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    # Required for the session cookie to survive a cross-origin deployment.
    # In development the Vite /api proxy makes the app same-origin and this
    # middleware is never consulted. NOTE: with credentials enabled the CORS
    # spec forbids a "*" origin - keep CORS_ALLOWED_ORIGINS explicit.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(base_router)
app.include_router(upload_router)
app.include_router(parse_router)
app.include_router(extract_router)
app.include_router(sanity_check_router)
app.include_router(verification_router)
app.include_router(persist_router)
app.include_router(offers_router)
app.include_router(jobs_router)
app.include_router(queue_router)
app.include_router(completeness_router)
app.include_router(taxonomy_router)
app.include_router(summary_router)
app.include_router(events_router)
app.include_router(dashboard_router)
app.include_router(compare_router)
app.include_router(rates_router)
