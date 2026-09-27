"""The client's completeness checklist, as seed data.

This is the twenty-item list Ahmed Mohamed Kamel gave in the 3 September
meeting: ten engineering disciplines and ten commercial terms. It is seeded
into `completeness_requirements` rather than hard-coded as an enum because he
will revise it - and because each result row snapshots the label and mandatory
flag it was judged under, an edit changes future checks without rewriting the
history of past ones.

The `description` on each entry does double duty: it is what the reviewer sees
explaining what "present" means for that row, and it is what the model is told
to look for. Keeping one text for both is deliberate - a checker that judges by
a rule nobody can read is not auditable.
"""

from dataclasses import dataclass

from models.enums import RequirementGroup


@dataclass(frozen=True)
class ChecklistEntry:
    code: str
    group: RequirementGroup
    label: str
    description: str
    is_mandatory: bool
    sort_order: int


# --- the ten technical disciplines -----------------------------------------
# Also the ten roots of the item taxonomy: "does this offer cover Electrical?"
# and "which discipline does this line item belong to?" are the same question
# asked from two directions, so they share one vocabulary.
#
# `is_mandatory` is False for all ten on purpose. A UPS quotation is not
# incomplete for having nothing to say about Plumbing - the honest verdict
# there is `not_applicable`, and marking these mandatory would bury the ten
# commercial gaps that actually matter under ten false alarms.
_TECHNICAL = [
    ("TECH_ARCHITECTURE", "Architecture",
     "Architectural scope: finishes, partitions, false ceilings, doors, cladding, "
     "or any item whose description is architectural rather than mechanical or electrical."),
    ("TECH_CIVIL_WORKS", "Civil Works",
     "Civil and structural scope: foundations, concrete bases, steel structures, "
     "excavation, builder's work, plinths."),
    ("TECH_PLUMBING", "Plumbing",
     "Plumbing and sanitary scope: water supply, drainage, piping, pumps, water "
     "heaters, sanitary fixtures."),
    ("TECH_ELECTRICAL", "Electrical",
     "Electrical scope: generators, transformers, switchgear, panels, UPS, ATS, "
     "cabling, cable tray, lighting, earthing."),
    ("TECH_HVAC", "HVAC",
     "Heating, ventilation and air conditioning scope: chillers, VRF/VRV systems, "
     "fan coil units, split units, air handling units, ducting, ventilation fans."),
    ("TECH_AUTOMATION", "Automation",
     "Control and automation scope: BMS, PLC, SCADA, controllers, instrumentation, "
     "integration with a building or plant management system."),
    ("TECH_LIGHT_CURRENT", "Light Current Systems",
     "Extra-low-voltage scope: CCTV, access control, intercom, structured cabling, "
     "public address, data networking, nurse call."),
    ("TECH_FIRE_FIGHTING", "Fire Fighting Systems",
     "Fire protection scope: fire pumps, sprinklers, hose reels, fire alarm and "
     "detection, extinguishers, gas suppression."),
    ("TECH_TRAINING", "Training",
     "Training scope: operator or maintenance training, its duration, location, and "
     "how many people it covers."),
    ("TECH_CERTIFICATION", "Certification",
     "Certificates and compliance evidence: test certificates, factory acceptance "
     "tests, CE/UL/ISO conformity, calibration or type-test certificates, "
     "certificates of origin."),
]

# --- the ten commercial terms (A-J on the client's list) --------------------
_COMMERCIAL = [
    ("COM_DELIVERY_TERM", "Delivery Term (Incoterm)",
     "The Incoterm governing delivery - CIF, DDP, Ex-Works or Ex-Factory are the "
     "ones normally seen, but ANY Incoterms 2020 term (EXW, FCA, CPT, CIP, DAP, "
     "DPU, DDP, FAS, FOB, CFR, CIF) counts as present. Do NOT report a gap merely "
     "because the term used is not one of the four common ones; report a gap only "
     "when the offer never states a delivery term at all."),
    ("COM_DELIVERY_LEAD_TIME", "Delivery Lead Time",
     "How long delivery takes - a number of days or weeks, a delivery date, or a "
     "period counted from a stated trigger such as order confirmation or receipt of "
     "the advance payment. A bare Incoterm is NOT a lead time. Neither is stock "
     "availability: 'Ex-stock', 'Based on the available stock' and 'Subject to prior "
     "sale' say where the goods are, not when they arrive."),
    ("COM_PAYMENT_TERMS", "Payment Terms",
     "How and when the supplier is paid: advance/milestone/on-delivery percentages, "
     "credit period, letter of credit, or a payment schedule."),
    ("COM_VAT_STATUS", "VAT Status",
     "Whether the quoted prices include VAT, exclude it, or are exempt/zero-rated. "
     "A price with no statement about tax at all is a gap - this is one of the most "
     "commonly missed terms."),
    ("COM_CURRENCY", "Offer Currency",
     "The currency of the quoted prices, NAMED - a code (USD, EGP) or a word "
     "(Dollars, Egyptian Pounds). A bare currency symbol such as $ is NOT enough, "
     "because it does not distinguish US, Canadian or Australian dollars."),
    ("COM_WARRANTY", "Warranty Duration",
     "The guarantee period and what starts it - months or years, counted from "
     "delivery, commissioning, or start-up - and anything it excludes."),
    ("COM_VALIDITY", "Offer Validity",
     "How long the quoted prices stand: a number of days, or an explicit expiry "
     "date for the offer."),
    ("COM_INSTALLATION", "Installation",
     "Whether installation, erection or commissioning is inside the quoted scope, "
     "explicitly excluded from it, or priced separately."),
    ("COM_SPARE_PARTS", "Spare Parts",
     "Whether spare parts are included, quoted separately, or excluded - including "
     "a recommended-spares list or a commissioning spares allowance."),
    ("COM_MAINTENANCE", "Maintenance",
     "Whether after-sales maintenance or a service contract is offered, and on what "
     "terms - free during warranty, chargeable, or excluded. Installation or "
     "commissioning labour is NOT maintenance, and neither is a maintenance-free "
     "component or a maintenance bypass switch - those are parts, not a service."),
]

CHECKLIST: tuple[ChecklistEntry, ...] = tuple(
    [
        ChecklistEntry(
            code=code,
            group=RequirementGroup.TECHNICAL,
            label=label,
            description=description,
            is_mandatory=False,
            sort_order=index + 1,
        )
        for index, (code, label, description) in enumerate(_TECHNICAL)
    ]
    + [
        ChecklistEntry(
            code=code,
            group=RequirementGroup.COMMERCIAL,
            label=label,
            description=description,
            is_mandatory=True,
            sort_order=100 + index + 1,
        )
        for index, (code, label, description) in enumerate(_COMMERCIAL)
    ]
)

CHECKLIST_BY_CODE: dict[str, ChecklistEntry] = {entry.code: entry for entry in CHECKLIST}

# The discipline codes, in the order the client listed them. Shared with the
# taxonomy seed so the two can never disagree about what the ten disciplines are.
TECHNICAL_CODES: tuple[str, ...] = tuple(code for code, _, _ in _TECHNICAL)
COMMERCIAL_CODES: tuple[str, ...] = tuple(code for code, _, _ in _COMMERCIAL)
