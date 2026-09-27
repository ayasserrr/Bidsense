from enum import Enum


class OfferEventKind(str, Enum):
    """What one line of an offer's activity log records.

    The vocabulary lives here rather than in a database check constraint, which
    is the opposite of what every other short vocabulary in this schema does.
    The reason is that this one grows: a new kind is added every time some
    action turns out to be worth remembering, and needing a migration to log
    something new is how a log stops being written. `offer_events.kind` is
    therefore plain text, and a kind this enum does not know is displayed from
    the row's own `detail` sentence rather than being rejected.

    An event is never derived at read time. "Bidsense parsed 42 pages across 3
    files" is written when it happens, by whoever it happened to, because the
    counts it quotes are gone by the next run.
    """

    # --- the pipeline, written by the runner (actor_user_id is NULL) -------
    OFFER_UPLOADED = "offer_uploaded"
    OFFER_QUEUED = "offer_queued"
    DOCUMENTS_PARSED = "documents_parsed"
    OFFER_EXTRACTED = "offer_extracted"
    FINDINGS_CONFIRMED = "findings_confirmed"
    READ_FINISHED = "read_finished"
    READ_FAILED = "read_failed"
    READ_CANCELLED = "read_cancelled"

    # The typed project name and the one the document states disagree. A
    # finding about the filing, never a reason to stop the run - the extracted
    # name is what decides version identity either way (helpers/
    # offer_versioning.check_same_offer_identity), so this says "look at this",
    # not "this failed".
    PROJECT_NAME_MISMATCH = "project_name_mismatch"

    # --- what a reviewer did ------------------------------------------------
    VERSION_UPLOADED = "version_uploaded"
    COMPLETENESS_RECHECKED = "completeness_rechecked"
    COMPLETENESS_OVERRIDDEN = "completeness_overridden"
    COMPLETENESS_OVERRIDE_CLEARED = "completeness_override_cleared"
    TAXONOMY_RESORTED = "taxonomy_resorted"
    SUMMARY_REGENERATED = "summary_regenerated"
    ITEM_RECATEGORISED = "item_recategorised"
    OFFER_ARCHIVED = "offer_archived"
    OFFER_UNARCHIVED = "offer_unarchived"
