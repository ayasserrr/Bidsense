"""The starting taxonomy: ten disciplines and the equipment under them.

The root codes are the SAME codes the completeness checklist uses for its ten
technical requirements. That is the whole point of seeding them together: an
item resolved to TECH_HVAC is direct evidence that the offer covers HVAC, so
the discipline half of the checklist answers itself from the bill of quantities
rather than from a second opinion.

The child level is ours, not the client's - he gave one example ("HVAC >
Chiller / VRF / VRV / Fan Coil") and left the rest. It is seeded rather than
guessed at per-offer so that two offers using different words for the same
thing land in the same bucket, and it is data in a table so a reviewer can
extend it without a deployment.

Aliases are the forms actually printed on Egyptian and Gulf offers, including
the abbreviations ("FCU", "MDB", "DG set") that a description will use without
ever spelling the thing out.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SeedNode:
    code: str
    label: str
    aliases: tuple[str, ...] = ()
    children: tuple["SeedNode", ...] = field(default_factory=tuple)


def _node(code: str, label: str, aliases: tuple[str, ...], children=()) -> SeedNode:
    return SeedNode(code=code, label=label, aliases=aliases, children=tuple(children))


TAXONOMY_SEED: tuple[SeedNode, ...] = (
    _node(
        "TECH_HVAC", "HVAC",
        ("hvac", "air conditioning", "mechanical ventilation", "climate control"),
        (
            _node("TECH_HVAC__CHILLER", "Chiller",
                  ("chiller", "water chiller", "air cooled chiller", "water cooled chiller",
                   "screw chiller", "scroll chiller", "absorption chiller")),
            _node("TECH_HVAC__VRF", "VRF / VRV",
                  ("vrf", "vrv", "variable refrigerant flow", "variable refrigerant volume",
                   "vrf system", "vrv system")),
            _node("TECH_HVAC__FCU", "Fan Coil Unit",
                  ("fcu", "fan coil", "fan coil unit", "ducted fan coil", "cassette unit")),
            _node("TECH_HVAC__SPLIT", "Split Unit",
                  ("split", "split unit", "mini split", "wall mounted unit", "window unit",
                   "concealed split")),
            _node("TECH_HVAC__AHU", "Air Handling Unit",
                  ("ahu", "air handling unit", "fahu", "fresh air handling unit", "makeup air unit")),
            _node("TECH_HVAC__PACKAGE", "Package / Rooftop Unit",
                  ("package unit", "packaged unit", "rooftop unit", "rtu", "self contained unit")),
            _node("TECH_HVAC__VENTILATION", "Ventilation & Ducting",
                  ("duct", "ducting", "ductwork", "exhaust fan", "ventilation fan", "extract fan",
                   "grille", "diffuser", "damper", "air curtain")),
            # Refrigerant pipework is HVAC, not Plumbing. The copper run between
            # an outdoor and an indoor unit is part of the air-conditioning
            # system; sending it to Plumbing would report a discipline as
            # covered on an offer that quotes no water, drainage or sanitary
            # work at all.
            _node("TECH_HVAC__REFRIGERANT", "Refrigerant Piping",
                  ("refrigerant pipe", "refrigerant piping", "refrigerant line",
                   "refrigerant copper pipe", "copper refrigerant pipe", "insulated copper pipe",
                   "refrigerant charge")),
            _node("TECH_HVAC__COOLING_TOWER", "Cooling Tower",
                  ("cooling tower", "condenser water", "closed circuit cooler")),
        ),
    ),
    _node(
        "TECH_ELECTRICAL", "Electrical",
        ("electrical", "power supply", "electrical works"),
        (
            _node("TECH_ELECTRICAL__GENERATOR", "Generator",
                  ("generator", "genset", "gen set", "diesel generator", "dg set", "standby generator")),
            # A generator's fuel train and exhaust are quoted as separate lines
            # on every genset offer and belong to the generator, not to Plumbing
            # (a day tank is fuel oil, not water) and not to HVAC (an engine
            # exhaust is not ventilation).
            _node("TECH_ELECTRICAL__GEN_AUX", "Generator Auxiliaries",
                  ("daily tank", "day tank", "daily fuel tank", "bulk tank", "bulk fuel tank",
                   "fuel tank", "diesel tank", "fuel system", "fuel piping", "exhaust silencer",
                   "residential silencer")),
            _node("TECH_ELECTRICAL__TRANSFORMER", "Transformer",
                  ("transformer", "dry type transformer", "oil immersed transformer", "package substation")),
            _node("TECH_ELECTRICAL__SWITCHGEAR", "Switchgear & Panels",
                  ("switchgear", "mv panel", "lv panel", "distribution board", "mdb", "smdb",
                   "panel board", "mccb panel", "ring main unit", "rmu", "motor control centre",
                   "mcc", "feeder pillar")),
            _node("TECH_ELECTRICAL__UPS", "UPS",
                  ("ups", "uninterruptible power supply", "static ups", "online ups", "inverter",
                   "battery bank", "battery cabinet")),
            _node("TECH_ELECTRICAL__ATS", "ATS / Transfer Switch",
                  ("ats", "automatic transfer switch", "changeover switch", "change over panel")),
            _node("TECH_ELECTRICAL__CABLING", "Cable & Containment",
                  ("cable", "power cable", "cable tray", "cable ladder", "busbar", "bus duct",
                   "busduct", "trunking", "conduit", "cable gland")),
            _node("TECH_ELECTRICAL__LIGHTING", "Lighting",
                  ("lighting", "luminaire", "light fitting", "led fixture", "flood light",
                   "emergency light", "street light")),
            _node("TECH_ELECTRICAL__EARTHING", "Earthing & Lightning Protection",
                  ("earthing", "grounding", "earth pit", "lightning protection", "surge arrester",
                   "spd", "lightning rod")),
            _node("TECH_ELECTRICAL__PFC", "Power Factor Correction",
                  ("capacitor bank", "pfc panel", "power factor correction", "harmonic filter")),
        ),
    ),
    _node(
        "TECH_FIRE_FIGHTING", "Fire Fighting Systems",
        ("fire fighting", "firefighting", "fire protection", "fire system"),
        (
            _node("TECH_FIRE__PUMP", "Fire Pumps",
                  ("fire pump", "jockey pump", "diesel fire pump", "electric fire pump",
                   "fire pump set")),
            _node("TECH_FIRE__SPRINKLER", "Sprinkler System",
                  ("sprinkler", "sprinkler head", "deluge", "wet riser", "dry riser",
                   "alarm valve", "flow switch")),
            _node("TECH_FIRE__ALARM", "Fire Alarm & Detection",
                  ("fire alarm", "fire detection", "smoke detector", "heat detector",
                   "addressable panel", "manual call point", "sounder", "beam detector")),
            _node("TECH_FIRE__EXTINGUISHER", "Extinguishers",
                  ("extinguisher", "fire extinguisher", "co2 extinguisher", "dry powder extinguisher",
                   "fire blanket")),
            _node("TECH_FIRE__SUPPRESSION", "Gas Suppression",
                  ("fm200", "fm 200", "novec", "gas suppression", "clean agent", "co2 flooding",
                   "aerosol suppression")),
            _node("TECH_FIRE__HYDRANT", "Hydrants & Hose Reels",
                  ("hose reel", "landing valve", "fire hydrant", "hydrant", "fire cabinet",
                   "siamese connection")),
        ),
    ),
    _node(
        "TECH_LIGHT_CURRENT", "Light Current Systems",
        ("light current", "extra low voltage", "elv", "low current"),
        (
            _node("TECH_ELV__CCTV", "CCTV",
                  ("cctv", "surveillance camera", "ip camera", "nvr", "dvr", "ptz camera",
                   "video surveillance")),
            _node("TECH_ELV__ACCESS", "Access Control",
                  ("access control", "card reader", "turnstile", "door controller", "biometric reader",
                   "time attendance")),
            _node("TECH_ELV__CABLING", "Structured Cabling",
                  ("structured cabling", "data cabling", "patch panel", "cat6", "cat 6", "cat5e",
                   "fiber optic", "fibre optic", "rack", "faceplate")),
            _node("TECH_ELV__PA", "Public Address",
                  ("public address", "pa system", "speaker", "voice evacuation", "horn speaker",
                   "amplifier")),
            _node("TECH_ELV__INTERCOM", "Intercom",
                  ("intercom", "video door phone", "door phone", "nurse call")),
            _node("TECH_ELV__NETWORK", "Data Network",
                  ("network switch", "router", "firewall", "access point", "wifi", "wireless ap",
                   "poe switch")),
        ),
    ),
    _node(
        "TECH_PLUMBING", "Plumbing",
        ("plumbing", "sanitary", "water supply", "drainage"),
        (
            _node("TECH_PLUMBING__PUMP", "Pumps",
                  ("water pump", "booster pump", "submersible pump", "sump pump", "drainage pump",
                   "booster set", "pressure set")),
            # "copper pipe" is deliberately NOT an alias here. Copper is the
            # material of both a plumbing water line and an HVAC refrigerant
            # line, so the bare phrase names no discipline on its own - and as a
            # Plumbing alias it silently turned VRV refrigerant piping into
            # Plumbing coverage. Left unmatched, the line goes to the model with
            # its full description, which is the right place to decide it:
            # a wrong discipline is worse than an unresolved one.
            _node("TECH_PLUMBING__PIPING", "Piping & Fittings",
                  ("ppr", "pvc pipe", "upvc", "hdpe", "gi pipe", "water pipe", "fitting",
                   "valve", "gate valve", "check valve")),
            _node("TECH_PLUMBING__HEATER", "Water Heaters",
                  ("water heater", "calorifier", "boiler", "solar water heater", "geyser")),
            _node("TECH_PLUMBING__SANITARY", "Sanitary Ware",
                  ("wc", "water closet", "wash basin", "sanitary ware", "faucet", "mixer",
                   "urinal", "shower")),
            _node("TECH_PLUMBING__TREATMENT", "Water Treatment",
                  ("water treatment", "ro unit", "reverse osmosis", "softener", "filtration",
                   "chlorination", "sewage treatment", "stp")),
        ),
    ),
    _node(
        "TECH_AUTOMATION", "Automation",
        ("automation", "control system", "controls"),
        (
            _node("TECH_AUTOMATION__BMS", "BMS",
                  ("bms", "building management system", "building automation", "bas",
                   "integration with bms")),
            _node("TECH_AUTOMATION__PLC", "PLC / SCADA",
                  ("plc", "scada", "hmi", "dcs", "programmable logic controller", "rtu panel")),
            _node("TECH_AUTOMATION__FIELD", "Controllers & Instrumentation",
                  ("controller", "thermostat", "sensor", "actuator", "transmitter", "flow meter",
                   "pressure gauge", "vfd", "variable frequency drive", "soft starter")),
        ),
    ),
    _node(
        "TECH_CIVIL_WORKS", "Civil Works",
        # "builders work" is deliberately NOT here - it belongs to the more
        # specific child below, and an alias may only point at one node.
        ("civil works", "civil work", "structural works", "site works"),
        (
            _node("TECH_CIVIL__FOUNDATION", "Foundations & Concrete",
                  ("foundation", "concrete", "plinth", "concrete base", "excavation", "backfilling",
                   "screed", "raft")),
            _node("TECH_CIVIL__STEEL", "Steel Structure",
                  ("steel structure", "structural steel", "platform", "support frame", "skid",
                   "canopy", "shed")),
            _node("TECH_CIVIL__BUILDERS", "Builder's Work",
                  ("builders work", "core drilling", "wall opening", "chasing", "making good",
                   "grouting")),
        ),
    ),
    _node(
        "TECH_ARCHITECTURE", "Architecture",
        ("architecture", "architectural", "architectural works", "finishing works"),
        (
            _node("TECH_ARCH__FINISHES", "Finishes",
                  ("finishes", "painting", "flooring", "tiles", "cladding", "epoxy floor",
                   "wall covering")),
            _node("TECH_ARCH__PARTITIONS", "Partitions & Ceilings",
                  ("partition", "false ceiling", "gypsum", "drywall", "suspended ceiling",
                   "raised floor")),
            _node("TECH_ARCH__OPENINGS", "Doors & Windows",
                  ("door", "fire door", "window", "louver", "shutter", "glazing", "curtain wall",
                   "roller shutter")),
        ),
    ),
    _node(
        "TECH_TRAINING", "Training",
        ("training", "operator training", "maintenance training", "on site training",
         "training course"),
        (),
    ),
    _node(
        "TECH_CERTIFICATION", "Certification",
        ("certification", "certificate", "certificates", "compliance"),
        (
            _node("TECH_CERT__TEST", "Test Certificates",
                  ("test certificate", "fat", "sat", "factory acceptance test",
                   "site acceptance test", "routine test", "type test")),
            _node("TECH_CERT__COMPLIANCE", "Compliance Certificates",
                  ("ce certificate", "ul listed", "iso certificate", "certificate of conformity",
                   "coc", "certificate of origin", "declaration of conformity")),
            _node("TECH_CERT__CALIBRATION", "Calibration Certificates",
                  ("calibration certificate", "calibration", "traceable calibration")),
        ),
    ),
)
