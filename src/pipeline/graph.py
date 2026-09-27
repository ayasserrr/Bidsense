from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from pipeline.node import (
    make_completeness_node,
    make_extract_node,
    make_parse_node,
    make_persist_node,
    make_sanity_check_node,
    make_summary_node,
    make_taxonomy_node,
    make_verification_node,
)
from pipeline.prescan import CompletenessPrescan
from pipeline.progress import JobProgress
from pipeline.stages import OFFER_PIPELINE_STAGE_ORDER
from pipeline.state import PipelineState


def build_offer_pipeline_graph(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
    *,
    start_stage: str = "parse",
):
    """Compiles the offer pipeline:
    parse -> extract -> sanity_check -> verification -> persist -> taxonomy ->
    completeness -> summary.

    Node order is fixed code, not an agent's own choice; the LLM work inside
    each node runs through the tools in `tools/`. This graph is the only
    orchestrator - the frontend starts a job and watches it, rather than driving
    the stages itself over six sequential HTTP calls.

    Upload is not a node. Files have to be consumed while the HTTP request that
    carried them is alive, so the offer and its documents are created there; the
    graph starts from documents that are already saved.

    `persist` is the line that matters. Everything before it can still lose the
    run. Everything after it - taxonomy, completeness, then summary - runs
    against an offer that is already saved, reports its own failure, and does
    not fail the job: re-running a check should never cost a finished
    extraction.

    Taxonomy runs before completeness because a line item resolved to a
    discipline is the strongest evidence that the offer covers that discipline,
    and completeness reads exactly that. Summary runs last of all: its chase
    list reads completeness's gaps and reports nothing honest before they exist.

    `verification` always runs rather than being skipped by a conditional edge,
    so its persisted `verification_status` is always explicit - `skipped` for a
    clean offer, never left null. The controller already skips the model call
    itself when there is nothing to verify, which costs one database round-trip;
    duplicating that rule as a graph edge would be a second copy of it that can
    drift.

    The one piece of work that does NOT wait its turn is the completeness scan
    (`pipeline/prescan.py`): it reads only parsed pages, so `extract` starts it
    and `completeness` collects it. It is an asyncio.Task rather than a parallel
    branch of this graph on purpose. A branch would join in a superstep, so a
    scan that hung would hold `sanity_check` up behind it - and LangGraph, not
    the runner, would decide what happens to it when a sibling fails. As a task
    the pipeline carries on the moment extraction is done, and cancellation has
    one owner.

    `start_stage` is `pipeline.resume`'s hook: a run resuming from a cached
    extraction payload builds a graph with only "sanity_check" onward as real
    nodes, seeded with that payload in its initial state, rather than a full
    "parse" that re-uploads every file to Parsing Studio and re-runs the most
    expensive stage in the run for work that already succeeded. Every stage
    before `start_stage` is simply never added to the graph - not added and
    skipped, genuinely absent - because a stage that is never reached needs no
    node to reach it.
    """
    if start_stage not in OFFER_PIPELINE_STAGE_ORDER:
        raise ValueError(f"unknown offer pipeline stage {start_stage!r}")

    node_builders: dict[str, Callable] = {
        "parse": lambda: make_parse_node(session_factory, progress),
        "extract": lambda: make_extract_node(session_factory, progress, prescan),
        "sanity_check": lambda: make_sanity_check_node(session_factory, progress),
        "verification": lambda: make_verification_node(session_factory, progress),
        "persist": lambda: make_persist_node(session_factory, progress),
        "taxonomy": lambda: make_taxonomy_node(session_factory, progress),
        "completeness": lambda: make_completeness_node(session_factory, progress, prescan),
        "summary": lambda: make_summary_node(session_factory, progress),
    }

    included = OFFER_PIPELINE_STAGE_ORDER[OFFER_PIPELINE_STAGE_ORDER.index(start_stage) :]

    graph = StateGraph(PipelineState)
    for stage_id in included:
        graph.add_node(stage_id, node_builders[stage_id]())

    graph.add_edge(START, included[0])
    for before, after in zip(included, included[1:]):
        graph.add_edge(before, after)
    graph.add_edge(included[-1], END)

    return graph.compile()


def build_completeness_graph(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
):
    """Just the completeness check, over an offer that is already saved.

    The re-runnable form: a reviewer adds a late technical file, or corrects an
    override, and asks for the check again without touching the offer.

    The `prescan` handed in here is never started - there is no extraction to
    run beside - so the node finds nothing to collect and does both halves of
    the check itself, which is what a re-check has always done.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("completeness", make_completeness_node(session_factory, progress, prescan))
    graph.add_edge(START, "completeness")
    graph.add_edge("completeness", END)
    return graph.compile()


def build_taxonomy_graph(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
):
    """Just the discipline sorting, over an offer that is already saved - run
    again after an admin approves new aliases.

    Takes `prescan` only so that every builder in the runner's dispatch table
    has one signature; there is no completeness stage here to collect it.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("taxonomy", make_taxonomy_node(session_factory, progress))
    graph.add_edge(START, "taxonomy")
    graph.add_edge("taxonomy", END)
    return graph.compile()


def build_summary_graph(
    session_factory: Callable[[], AsyncSession],
    progress: JobProgress,
    prescan: CompletenessPrescan,
):
    """Just the chase-list/email draft, over an offer that is already saved -
    run again after a reviewer corrects a completeness override or attaches
    late evidence. Takes `prescan` only for the same reason `build_taxonomy_
    graph` does: one signature for every builder in the runner's dispatch
    table.
    """
    graph = StateGraph(PipelineState)
    graph.add_node("summary", make_summary_node(session_factory, progress))
    graph.add_edge(START, "summary")
    graph.add_edge("summary", END)
    return graph.compile()
