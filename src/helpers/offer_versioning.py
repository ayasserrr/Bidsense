from models.db_schema import Project, Supplier
from schema.offer import OfferExtractionPayload


def check_same_offer_identity(
    payload: OfferExtractionPayload,
    parent_supplier: Supplier | None,
    parent_project: Project | None,
) -> str | None:
    """Plain string comparison - deliberately not fuzzy or LLM-judged - that
    a newly extracted "new version" payload actually belongs to the same
    offer chain as `parent_supplier`/`parent_project`. This is the safety
    net against attaching an unrelated document as a "new version" of a
    completely different offer by mistake.

    Supplier is always checked when the parent offer has one linked: a real
    offer document almost always states its own supplier, so even a missing
    name on the new upload counts as a mismatch, not a pass. Project and
    client are only checked when the new document actually states one and
    the parent has one on file - many legitimate offers never restate a
    project name or client name (e.g. a revision that just says "per our
    previous quote"), so silence there isn't evidence of anything.

    Returns a human-readable mismatch reason, or `None` if nothing in the
    new payload contradicts the parent.
    """
    if parent_supplier is not None:
        new_supplier_name = payload.supplier.supplier_name_original
        known_names = {
            parent_supplier.supplier_name.lower(),
            *(alias.lower() for alias in parent_supplier.supplier_aliases or []),
        }
        if not new_supplier_name or new_supplier_name.lower() not in known_names:
            return (
                f"The uploaded document's supplier ('{new_supplier_name or 'not stated'}') does not "
                f"match the existing offer's supplier ('{parent_supplier.supplier_name}'). If this is "
                "intentional, upload it as a new offer instead."
            )

    new_project_name = payload.project_name_original
    if parent_project is not None and new_project_name:
        known_names = {
            parent_project.project_name.lower(),
            *(alias.lower() for alias in parent_project.project_aliases or []),
        }
        if new_project_name.lower() not in known_names:
            return (
                f"The uploaded document's project ('{new_project_name}') does not match the existing "
                f"offer's project ('{parent_project.project_name}'). If this is intentional, upload it "
                "as a new offer instead."
            )

    new_client_name = payload.client_name_original
    if parent_project is not None and parent_project.client_name and new_client_name:
        known_names = {
            parent_project.client_name.lower(),
            *(alias.lower() for alias in parent_project.client_aliases or []),
        }
        if new_client_name.lower() not in known_names:
            return (
                f"The uploaded document's client ('{new_client_name}') does not match the existing "
                f"offer's client ('{parent_project.client_name}'). If this is intentional, upload it "
                "as a new offer instead."
            )

    return None
