"""The stage lists a background job can be made of, and what each one is worth.

One definition, used three ways: the runner walks it, the job row stores a
snapshot of it, and the progress bar renders that snapshot. Labels live here
rather than in the frontend so a job of any kind - a full pipeline run or a
single re-check - describes itself, and the UI only has to draw what it is
given.
"""

from dataclasses import dataclass

from models.enums import JobKind


@dataclass(frozen=True)
class StageDefinition:
    id: str
    label: str
    # Share of the overall progress bar. Weights are rough measured durations,
    # not guesses at importance: extraction is most of the wall clock on a real
    # offer, so a bar that gave every stage an equal slice would jump to 50%
    # and then appear frozen for ten minutes.
    weight: int


# Named because two places report on this one stage: the completeness node, and
# the scan that now runs ahead of it alongside extraction (`pipeline/prescan.py`).
COMPLETENESS_STAGE_ID = "completeness"
SUMMARY_STAGE_ID = "summary"

OFFER_PIPELINE_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("upload", "Uploading your files", 4),
    StageDefinition("parse", "Reading your documents", 12),
    StageDefinition("extract", "Extracting the details", 44),
    StageDefinition("sanity_check", "Double-checking the numbers", 8),
    StageDefinition("verification", "Verifying against the source", 8),
    StageDefinition("persist", "Saving the offer", 4),
    # Order here must match pipeline.graph, not just read well: the UI draws
    # this list top to bottom, so a list that disagreed with the execution
    # order would show a later step going active above an earlier one.
    #
    # Completeness stays last even though its scan half starts early. The scan
    # is not a stage of its own: it produces nothing a reviewer can read, and a
    # ninth row that appeared next to extraction and then vanished would be
    # noise. The row goes active early instead, which is the truth.
    StageDefinition("taxonomy", "Sorting items by discipline", 6),
    # 10, not the 14 it measured before summary existed: 4 of that moved to
    # summary below, which does the write-up half of what used to be
    # attributed entirely to this stage. Weights must keep summing to 100 -
    # see test_weights_total_one_hundred.
    StageDefinition(COMPLETENESS_STAGE_ID, "Checking the offer for gaps", 10),
    # Runs last, not alongside taxonomy/completeness: the chase list reads
    # their results (a confirmed finding, a mandatory gap), so it has nothing
    # honest to say until both have had their turn. No LLM call of its own -
    # see pipeline/node/summary.py - so its weight is small on purpose.
    StageDefinition(SUMMARY_STAGE_ID, "Writing the summary", 4),
)

COMPLETENESS_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition(COMPLETENESS_STAGE_ID, "Checking the offer for gaps", 100),
)

TAXONOMY_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition("taxonomy", "Sorting items by discipline", 100),
)

SUMMARY_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition(SUMMARY_STAGE_ID, "Writing the summary", 100),
)

STAGES_BY_KIND: dict[JobKind, tuple[StageDefinition, ...]] = {
    JobKind.OFFER_PIPELINE: OFFER_PIPELINE_STAGES,
    JobKind.COMPLETENESS: COMPLETENESS_STAGES,
    JobKind.TAXONOMY: TAXONOMY_STAGES,
    JobKind.SUMMARY: SUMMARY_STAGES,
}

# Everything from `persist` onward runs against an offer that is already saved.
# A failure in one of these is reported, but it does not fail the job and never
# discards the offer - the reviewer re-runs the check from the offer page.
POST_PERSIST_STAGE_IDS = frozenset({"completeness", "taxonomy", SUMMARY_STAGE_ID})


def stages_for(kind: JobKind) -> tuple[StageDefinition, ...]:
    return STAGES_BY_KIND[kind]


# The offer pipeline's fixed order, as plain ids. Lives here rather than in
# `pipeline.graph` so `pipeline.resume` - imported by the node modules
# themselves, to save their own checkpoints - can use it without importing
# `pipeline.graph`, which imports `pipeline.node`, which would import the node
# modules that are trying to import `pipeline.resume`: a cycle. `graph.py`
# imports it from here instead of re-declaring it, so the two can never
# disagree about what comes after what.
OFFER_PIPELINE_STAGE_ORDER: tuple[str, ...] = tuple(
    stage.id for stage in OFFER_PIPELINE_STAGES if stage.id != "upload"
)
