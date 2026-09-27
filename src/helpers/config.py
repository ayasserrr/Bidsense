from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo root (this file is src/helpers/config.py), resolved from the file's
# own location rather than the working directory. `.env` lives there next to
# main.py, and this way it is found identically whether the process was started
# by uvicorn from the root, by alembic, or by a script run from src/ - a
# CWD-relative ".env" would silently fall back to environment-only settings and
# fail startup with a confusing "field required" error instead.
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):

    APP_NAME: str
    APP_VERSION: str
    # The application's own log level. Without configuring this the root logger
    # sits at WARNING and every INFO line this app writes is silently dropped -
    # including the per-call `llm_call ... duration_seconds=` lines, which are
    # the first thing anyone looks at when a run is slow. uvicorn configures
    # only its own loggers, not this one.
    LOG_LEVEL: str

    # --- LLM gateway -------------------------------------------------------
    # Every model call goes to the corporate LiteLLM gateway. There is no
    # external AI provider and no fallback to one - qwen and gemma, both
    # already-configured local models served by that same gateway, fall back
    # to each other instead (see LLM_FALLBACK_ENABLED).
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_PRIMARY_MODEL: str
    LLM_HELPER_MODEL: str
    LLM_APPLICATION_NAME: str
    LLM_TIMEOUT_SECONDS: float
    LLM_CONNECT_TIMEOUT_SECONDS: float
    LLM_TEMPERATURE: float
    LLM_VERIFY_TLS: bool
    # Reasoning is configured per model because the two models differ: qwen
    # takes `enable_thinking` plus a `reasoning_effort`, gemma cannot think.
    # The reasoning trace SHARES the output cap with the JSON answer, so a
    # thinking model needs a larger cap - too small and it spends the budget
    # reasoning and the answer comes back cut off or empty. The helper's cap
    # stays smaller because its context is: vLLM refuses a request whose input
    # plus max_tokens exceeds the model's window.
    LLM_PRIMARY_ENABLE_THINKING: bool
    # "low" | "medium" | "high"; empty sends no reasoning_effort at all.
    LLM_PRIMARY_REASONING_EFFORT: str
    LLM_PRIMARY_MAX_OUTPUT_TOKENS: int
    LLM_HELPER_ENABLE_THINKING: bool
    LLM_HELPER_MAX_OUTPUT_TOKENS: int
    # How many times a single gateway call is attempted before giving up, and the
    # base backoff between attempts (exponential off this, capped at 30s, plus
    # jitter). Separate from EXTRACTION_MAX_REPAIR_ATTEMPTS below, which retries
    # schema-validation failures, not transport failures.
    # ge=1: at 0 or below, `_call_with_retries`'s attempt loop would never run
    # and every gateway call would fail with a misleading "None" error instead
    # of a real one, or a real attempt.
    LLM_CALL_MAX_ATTEMPTS: int = Field(ge=1)
    LLM_CALL_BACKOFF_SECONDS: float
    # When a call exhausts LLM_CALL_MAX_ATTEMPTS against the model it was routed
    # to, retry the whole call once against the OTHER local model before giving
    # up. Never used for a truncated or schema-invalid response - only for
    # transport failures, where a different model is actually a fresh chance.
    LLM_FALLBACK_ENABLED: bool
    # How many requests this process may have in flight at the gateway at once,
    # across every stage and every concurrent run. Extraction splits a long
    # offer into page chunks and the completeness checker into facets; both fan
    # out up to this ceiling instead of running one call at a time, which is
    # what makes a multi-chunk offer finish in roughly the time of its slowest
    # chunk rather than the sum of all of them. Raising it past what the
    # gateway will actually serve concurrently converts speed into queueing and
    # timeouts, so it is configuration, not a constant.
    LLM_MAX_CONCURRENT_REQUESTS: int

    # --- Authentication (corporate Active Directory) -----------------------
    # LDAP_ENABLED=false is an emergency switch: non-admin logins then get a
    # 503. It never re-enables local passwords for ordinary users.
    LDAP_ENABLED: bool
    LDAP_API_URL: str
    # A timeout is reported as "directory unreachable", not as a wrong
    # password, so too tight a value turns a slow AD into a login outage.
    LDAP_TIMEOUT_SECONDS: float
    # The service authenticates without a key today; sent only when set.
    LDAP_API_KEY: str = ""
    LDAP_VERIFY_TLS: bool
    # The directory only accepts a UPN: a bare "firstname.lastname" is
    # rejected with 400 "Malformed username". People sign in to their
    # workstation with the bare name, so it is completed with this suffix when
    # the typed value has no "@".
    LDAP_UPN_SUFFIX: str

    JWT_SECRET: str
    JWT_ALGORITHM: str
    # Must comfortably exceed one full pipeline run: a token expiring mid-run
    # would 401 the persist call and lose the work.
    JWT_EXPIRE_MINUTES: int
    # Browsers silently discard a Secure cookie over plain http, which looks
    # like "login worked then every request is 401". Off for LAN dev, on
    # behind real HTTPS.
    SESSION_COOKIE_SECURE: bool

    # The only local-password account, so an AD outage cannot lock operations
    # out of the app entirely.
    BOOTSTRAP_ADMIN_USERNAME: str
    BOOTSTRAP_ADMIN_PASSWORD: str = ""

    FILE_ALLOWED_TYPES: list[str]
    # A separate allowlist for the files a reviewer attaches to justify an
    # override. Emails are the client's primary evidence and are not accepted
    # as offer documents - a decision about what an offer is, not a parsing
    # limit (Parsing Studio can read them) - so the two lists are deliberately
    # not the same setting.
    EVIDENCE_ALLOWED_TYPES: list[str]
    FILE_MAX_SIZE: int
    FILE_DEFAULT_CHUNK_SIZE: int

    DATABASE_URL: str

    CORS_ALLOWED_ORIGINS: list[str]

    # --- Document parsing (corporate Parsing Studio service) ---------------
    # Comma-separated; tried in order, and the next one is used only when a
    # server cannot be connected to at all. There is no local parser and no
    # fallback to one.
    PARSING_STUDIO_URLS: str
    # "native-text@stable" for documents with a real text layer (OCR still
    # runs on the pages that need it); "arabic-scanned@stable" is OCR-first.
    PARSING_STUDIO_RECIPE: str
    # Queue time plus parse time for ONE file. Scanned pages go through OCR
    # and docling on the service, which allows itself minutes per page.
    PARSING_STUDIO_TIMEOUT_SECONDS: float
    # Files of one offer sent at once. The service runs a fixed number of
    # parses for everyone and queues the rest, so this is a courtesy ceiling,
    # not a speed dial.
    PARSING_STUDIO_MAX_CONCURRENT_FILES: int
    LANGUAGE_DETECTION_SAMPLE_CHARS: int

    # --- the job queue -----------------------------------------------------
    # How many offers this process will read at the same time. The hard ceiling
    # of the installation, not the control a reviewer turns: that one is
    # `queue_state.parallel_slots` in the database, and the dispatcher runs the
    # SMALLER of the two. Both exist because they answer different questions -
    # this one is "what will this server stand", which only an operator knows,
    # and the row is "how many do we want going at once today", which changes
    # without a deploy.
    #
    # 1 is the honest default and what the queue screen describes ("one offer
    # reads at a time - the rest wait in order"). Raising it multiplies
    # everything underneath: each concurrent run fans out up to
    # LLM_MAX_CONCURRENT_REQUESTS at the gateway and up to
    # PARSING_STUDIO_MAX_CONCURRENT_FILES at a service another team owns, so 3
    # runs can mean 3x both. The 1-3 bound is the same one the database check
    # constraint puts on parallel_slots (models/db_schema/queue_state.py);
    # outside it the server refuses to start rather than silently clamping.
    #
    # It carries a default, which almost nothing here does, for the same reason
    # COMPLETENESS_SCAN_DURING_EXTRACTION does: it changes behaviour rather
    # than naming a resource this deployment has to supply, and every existing
    # `.env` predates it and must keep starting the server. 1 is also the
    # behaviour those deployments already had in every way that matters.
    QUEUE_MAX_CONCURRENT_JOBS: int = Field(default=1, ge=1, le=3)

    EXTRACTION_MAX_REPAIR_ATTEMPTS: int
    EXTRACTION_MAX_PAGES_PER_CHUNK: int
    EXTRACTION_CHUNK_PAGE_OVERLAP: int
    EXTRACTION_TOTAL_TIMEOUT_SECONDS: float

    # The completeness check's scan half reads only parsed pages, so it does not
    # have to wait for extraction: with this on it runs alongside it and the
    # completeness stage is left with the reconciliation, which is the only part
    # that needs the saved offer. Off puts the whole check back behind taxonomy,
    # one request at a time - the switch to flip if that second concurrent
    # request is ever measured costing extraction more than the scan saves.
    # One of the two settings with a default, deliberately: it changes
    # behaviour rather than naming a resource, and a deployment's existing .env
    # must keep starting without an edit. QUEUE_MAX_CONCURRENT_JOBS above is
    # the other, for the same reason.
    COMPLETENESS_SCAN_DURING_EXTRACTION: bool = True

    # --- Money -------------------------------------------------------------
    # The currency every total on the dashboard and the compare screen is
    # converted INTO. The original amount and its own currency are returned
    # beside every converted figure regardless, so changing this changes what
    # the second number means, never whether the first one is shown.
    # These four carry defaults, unlike almost everything above: they were
    # added after deployments already had a .env, and an existing one has to
    # keep starting without an edit. None of them names a secret.
    BASE_CURRENCY: str = "EGP"
    # `{base}` is substituted with BASE_CURRENCY. The default provider needs no
    # key and publishes daily. It is only ever called by an explicit refresh -
    # never on the path of a page that has to render.
    EXCHANGE_RATES_API_URL: str = "https://open.er-api.com/v6/latest/{base}"
    # The firewalled-server switch. Off, a refresh does not attempt the call at
    # all and says so; the rates already on file keep working and a person can
    # still type one in by hand.
    EXCHANGE_RATES_FETCH_ENABLED: bool = True
    # One refresh attempt. Short on purpose: a provider that is slow is a
    # provider that is down as far as this feature is concerned, and the rates
    # already on file are never at risk either way.
    EXCHANGE_RATES_TIMEOUT_SECONDS: float = 15.0

    model_config = SettingsConfigDict(env_file=ENV_FILE)


@lru_cache
def get_settings() -> Settings:
    return Settings()
