"""filing an offer, its activity log, a real queue, and exchange rates

Five changes, all schema. Nothing in this revision writes application data at
runtime - it is the foundation the revamped screens are built on, and the
endpoints that fill these columns land separately.

1. `offers.rfq_number`, `offers.project_name_entered`, `offers.archived_at`.
   An offer is now FILED by the person uploading it, against an RFQ number and
   a project name they type, instead of being known only by what the document
   happens to say about itself. The typed name is deliberately a second column
   rather than a correction of `project_name_original`: the extracted name is
   what `helpers/offer_versioning.check_same_offer_identity` compares when a
   new version is uploaded, and overwriting it with something a person typed
   would quietly break that check. The two disagreeing is a fact worth
   showing, not an error - it is recorded as an `offer_events` row and never
   allowed to block a run.

2. `offer_events` - the activity log three screens ask for (the dashboard
   timeline, the hover card on the offers list, and the detail screen's own
   log). Until now the closest thing was a scatter of `*_by_user_id` / `*_at`
   pairs on five tables, which can say who last touched a row but never what
   happened to it, in order.

3. `pipeline_jobs.queue_position` / `enqueued_at` / `started_at`, plus a
   `queue_state` row. Jobs stop being unordered `asyncio.Task`s started the
   instant they are created and become a queue that waits, in an order a
   reviewer can change.

4. `exchange_rates` - one current rate per currency, no history, seeded with
   nothing. An empty table means "no conversion available yet", which the
   reading code has to cope with anyway the moment one currency has no rate.

5. Indexes for the offers list the revamp draws: searched by reference,
   project, supplier and RFQ, filtered by uploader and date, ordered by
   `created_at` descending, and paginated. `offers` had no index on
   `created_at` at all.

Revision ID: 0017_revamp_schema
Revises: 0016_checklist_rules
Create Date: 2026-09-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0017_revamp_schema"
down_revision: Union[str, None] = "0016_checklist_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors models.enums.ExchangeRateSource. Spelled out here rather than
# imported because a migration has to keep describing the schema it wrote even
# after the enum it was written against has moved on.
RATE_SOURCES = ("api", "manual")

# `offer_events.kind` deliberately carries NO check constraint - see the
# table's own comment below.

# Free-text search on the offers list. Trigram indexes make a contains-match
# ("%delta%") indexable; a btree cannot. pg_trgm is a contrib extension, so it
# may be absent, or present but uninstallable by a role that is neither a
# superuser nor the database owner - hence the probe, and a prefix-only
# fallback, rather than a hard dependency that would stop this migration
# running on the deployment server.
TRGM_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_offers_offer_ref_trgm", "offers", "offer_ref"),
    ("ix_offers_rfq_number_trgm", "offers", "rfq_number"),
    ("ix_offers_project_name_entered_trgm", "offers", "project_name_entered"),
    ("ix_offers_project_name_original_trgm", "offers", "project_name_original"),
    # The supplier name lives on `suppliers`, and the list joins to it, so the
    # index for "search supplier" has to live there too.
    ("ix_suppliers_supplier_name_trgm", "suppliers", "supplier_name"),
)

# The degraded mode. `lower(col) text_pattern_ops` indexes a prefix match
# ("qt-44%"), which is how a reference number is actually typed, and is the
# most that is possible without trigrams.
PREFIX_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_offers_offer_ref_lower", "offers", "offer_ref"),
    ("ix_offers_rfq_number_lower", "offers", "rfq_number"),
)


def _trigram_search_available(bind) -> bool:
    """Whether `pg_trgm` is installed, or can be installed here and now."""
    if bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")).scalar():
        return True
    if not bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")
    ).scalar():
        return False
    try:
        # Inside a SAVEPOINT: a permission error on CREATE EXTENSION would
        # otherwise poison this migration's transaction and take the other
        # four changes down with it.
        with bind.begin_nested():
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except sa.exc.DBAPIError:
        return False
    return True


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. filing an offer ------------------------------------------------
    op.add_column("offers", sa.Column("rfq_number", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("project_name_entered", sa.Text(), nullable=True))
    op.add_column("offers", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_offers_rfq_number", "offers", ["rfq_number"])
    op.create_index("ix_offers_archived_at", "offers", ["archived_at"])

    # --- 2. the activity log -----------------------------------------------
    op.create_table(
        "offer_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        # CASCADE, like pipeline_jobs.offer_id: discarding an offer takes its
        # history with it rather than leaving events pointing at nothing.
        sa.Column(
            "offer_id",
            sa.BigInteger(),
            sa.ForeignKey("offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL means the system did it - the design's "Bidsense confirmed 2
        # findings". Because this is ON DELETE SET NULL like every other
        # ownership column, deleting an account would otherwise turn that
        # person's entries into system entries, so the name is snapshotted
        # beside it and the log keeps saying what actually happened.
        sa.Column(
            "actor_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_display_name", sa.Text(), nullable=False, server_default=""),
        # No check constraint on purpose. Every other short vocabulary in this
        # schema is constrained, but this one grows every time a new action is
        # worth logging - a migration per event kind would make logging the
        # expensive thing to do, and an unrecognised kind renders as its own
        # detail line rather than corrupting anything. The vocabulary lives in
        # models.enums.OfferEventKind.
        sa.Column("kind", sa.Text(), nullable=False),
        # The sentence a person reads: "corrected 'Warranty period' with an
        # attached email". Written at the time, not rebuilt later out of ids
        # that may since have been deleted or renamed.
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        # The same event's machine facts ({"pages": 42, "files": 3}), so a
        # timeline row can show its counts without re-querying five tables.
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # One offer's log, newest first.
    op.create_index(
        "ix_offer_events_offer_id_created_at",
        "offer_events",
        ["offer_id", sa.text("created_at DESC")],
    )
    # The dashboard's company-wide timeline. It still has to join `offers` for
    # the department scope, which is why no owner columns are copied onto this
    # table: an event is visible exactly when its offer is, and one policy read
    # from one place cannot drift from itself.
    op.create_index("ix_offer_events_created_at", "offer_events", [sa.text("created_at DESC")])

    # --- 3. a real queue ---------------------------------------------------
    # NULL means "not waiting" - running, finished, cancelled, or never queued.
    # Not unique: a reorder rewrites several rows at once, and a unique
    # constraint would force either a deferrable constraint or a shuffle
    # through temporary values for what is a display order. Ties break on
    # enqueued_at, so the order stays total even when two rows briefly share a
    # position.
    op.add_column("pipeline_jobs", sa.Column("queue_position", sa.Integer(), nullable=True))
    op.add_column(
        "pipeline_jobs",
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # When the job left the queue and began reading. Without it, `created_at ->
    # finished_at` silently becomes "wait + read" the moment jobs really do
    # wait, and both the elapsed pill on the queue screen and the average read
    # time on the dashboard would start measuring the backlog instead.
    op.add_column(
        "pipeline_jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE pipeline_jobs SET enqueued_at = created_at")
    # Every job that already exists started the instant it was created - that
    # is what the old runner did. A row still sitting in 'queued' is the one
    # exception: it never started at all, and reap_stale_jobs fails it.
    op.execute("UPDATE pipeline_jobs SET started_at = created_at WHERE status <> 'queued'")
    op.create_index(
        "ix_pipeline_jobs_queue_order",
        "pipeline_jobs",
        ["status", "queue_position", "enqueued_at"],
    )

    op.create_table(
        "queue_state",
        # Exactly one row, forced by the check constraint. A single-row table
        # rather than a module-level flag because pause has to survive a
        # restart - pausing the queue and then deploying must not quietly
        # release the backlog - and has to be seen by every uvicorn worker,
        # not only the one that happened to take the request.
        sa.Column("queue_state_id", sa.SmallInteger(), primary_key=True, autoincrement=False),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        # How many offers read at once. The client asked for one to three; the
        # ceiling is here rather than in config because it is a control a
        # signed-in person turns, and the gateway enforces its own concurrency
        # limit underneath regardless.
        sa.Column("parallel_slots", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("queue_state_id = 1", name="ck_queue_state_singleton"),
        sa.CheckConstraint("parallel_slots BETWEEN 1 AND 3", name="ck_queue_state_parallel_slots"),
        sa.CheckConstraint(
            "is_paused = false OR paused_at IS NOT NULL", name="ck_queue_state_paused_at"
        ),
    )
    # The one row is seeded here, unlike exchange_rates: "no row" and "not
    # paused" would otherwise be indistinguishable, and every reader would have
    # to carry its own copy of the defaults for a table that can only ever hold
    # one row of them.
    op.execute(
        "INSERT INTO queue_state (queue_state_id, is_paused, parallel_slots, updated_at) "
        "VALUES (1, false, 1, now())"
    )

    # --- 4. exchange rates -------------------------------------------------
    op.create_table(
        "exchange_rates",
        # The currency code IS the primary key: one current rate per currency,
        # no history. A per-offer rate history was considered and dropped - a
        # figure converted a month ago and the same figure converted today must
        # not disagree on a screen that puts them side by side.
        sa.Column(
            "currency_code",
            sa.Text(),
            sa.ForeignKey("currencies.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        # What this rate converts INTO, stored rather than assumed. The base
        # currency is configurable, and a rate fetched against EGP is simply
        # wrong once the base becomes USD - recorded here, the reading code can
        # refuse to convert instead of quietly reporting a wrong number. No ON
        # DELETE: removing a currency that rates are quoted against should fail
        # loudly.
        sa.Column(
            "base_currency_code",
            sa.Text(),
            sa.ForeignKey("currencies.code"),
            nullable=False,
        ),
        # Exact, never a float: money converted through a binary float stops
        # adding up, and this application's whole reason for existing is that
        # it re-adds other people's arithmetic. Ten decimal places covers the
        # weak-currency direction (one LBP is a rounding error against a strong
        # base) without pretending to a precision the API publishes.
        sa.Column("rate_to_base", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        # The provider's own "as of", which is not the same fact as when we
        # wrote the row: a refresh that ran a minute ago can still be carrying
        # yesterday's published rate. NULL when a person typed it.
        sa.Column("rate_as_of", sa.DateTime(timezone=True), nullable=True),
        # When this row was last written. The age shown beside every converted
        # figure is measured from here.
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        # Who typed it, for a manual rate. NULL for an API refresh - and also
        # for a manual rate whose author's account was later deleted, which is
        # why there is no constraint tying 'manual' to a non-null user.
        sa.Column(
            "set_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(f"source IN {RATE_SOURCES}", name="ck_exchange_rates_source"),
        sa.CheckConstraint("rate_to_base > 0", name="ck_exchange_rates_rate_positive"),
        sa.CheckConstraint(
            "currency_code <> base_currency_code OR rate_to_base = 1",
            name="ck_exchange_rates_base_is_one",
        ),
    )
    # No secondary indexes: the table holds one row per currency - a couple of
    # dozen - and every read is either the whole table or a primary-key hit.

    # --- 5. the offers list ------------------------------------------------
    # Ordered by created_at DESC and paginated, on every variant of the list.
    op.create_index("ix_offers_created_at", "offers", [sa.text("created_at DESC")])
    # "Uploaded by" plus the same ordering. The single-column index on
    # created_by_user_id stays: it is what the version-chain queries use.
    op.create_index(
        "ix_offers_created_by_user_created_at",
        "offers",
        ["created_by_user_id", sa.text("created_at DESC")],
    )
    # The department half of visibility_filter, plus the same ordering - the
    # shape every non-admin list takes. Deliberately not partial on
    # `persisted_at IS NOT NULL` or `archived_at IS NULL`: a partial index
    # serves only queries that repeat its predicate word for word, and these
    # have to keep working for the dashboard counts and the archived view too.
    op.create_index(
        "ix_offers_department_created_at",
        "offers",
        ["created_by_department", sa.text("created_at DESC")],
    )

    if _trigram_search_available(bind):
        for index_name, table_name, column_name in TRGM_INDEXES:
            # gin_trgm_ops on the raw column, not lower(): pg_trgm folds case
            # itself, so `col ILIKE '%q%'` uses this index exactly as written.
            op.execute(
                f"CREATE INDEX {index_name} ON {table_name} "
                f"USING gin ({column_name} gin_trgm_ops)"
            )
    else:
        for index_name, table_name, column_name in PREFIX_INDEXES:
            op.execute(
                f"CREATE INDEX {index_name} ON {table_name} "
                f"(lower({column_name}) text_pattern_ops)"
            )


def downgrade() -> None:
    # IF EXISTS because which of these two sets was created depends on whether
    # the server had pg_trgm when the upgrade ran.
    for index_name, _table_name, _column_name in TRGM_INDEXES + PREFIX_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    # The extension itself is left installed. Dropping it would take any other
    # trigram index on this database with it, and it may well have been there
    # before this migration ran.

    op.drop_index("ix_offers_department_created_at", table_name="offers")
    op.drop_index("ix_offers_created_by_user_created_at", table_name="offers")
    op.drop_index("ix_offers_created_at", table_name="offers")

    op.drop_table("exchange_rates")

    op.drop_table("queue_state")
    op.drop_index("ix_pipeline_jobs_queue_order", table_name="pipeline_jobs")
    op.drop_column("pipeline_jobs", "started_at")
    op.drop_column("pipeline_jobs", "enqueued_at")
    op.drop_column("pipeline_jobs", "queue_position")

    op.drop_index("ix_offer_events_created_at", table_name="offer_events")
    op.drop_index("ix_offer_events_offer_id_created_at", table_name="offer_events")
    op.drop_table("offer_events")

    op.drop_index("ix_offers_archived_at", table_name="offers")
    op.drop_index("ix_offers_rfq_number", table_name="offers")
    op.drop_column("offers", "archived_at")
    op.drop_column("offers", "project_name_entered")
    op.drop_column("offers", "rfq_number")
