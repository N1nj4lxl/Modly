# =========================
# Section 1 — Imports → Themes
# =========================

# Stdlib
import os
import re
import io
import csv
import json
import time
import shutil
import struct
import zipfile
import threading
import datetime

# GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Dataclasses
from dataclasses import dataclass

# -------------------------
# App constants (safe to tweak)
# -------------------------

APP_NAME: str    = "Sims4 Mod Sorter"
APP_VERSION: str = "1.1.0"

# Paths (change if you want a different settings/log location)
CONFIG_PATH: str = os.path.join(os.path.expanduser("~"), ".sims4_modsorter_settings.json")
LOG_NAME: str    = ".sims4_modsorter_moves.json"  # move/undo history written in Mods

# Detection pipeline order shown in Settings
# You can reorder at runtime; this is just the default.
DEFAULT_DETECTOR_ORDER: list[str] = ["name", "binary", "ext"]

# Where protected collision files are moved instead of deleted
COLLIDING_DIR_NAME: str = "Colliding Mods"

TOP_SLOTS = ("MCC", "UI Cheats", "CAS", "Build Mode", "Gameplay", "Animations")

FOLDER_PRESETS = {
    "MCC": ("MCC", "MC Command Center", "Core Mods", "Frameworks"),
    "UI Cheats": ("UI Cheats", "UI & Cheats", "Cheats", "UI Mods"),
    "CAS": ("CAS", "Create A Sim"),
    "Build Mode": ("Build Mode", "Build/Buy", "Build & Buy"),
    "Gameplay": ("Gameplay", "Game Mods"),
    "Animations": ("Animations", "Animation", "Poses"),
}

# -------------------------
# Themes
# Keys:
#  - bg: window background
#  - fg: default text
#  - alt: panels/cards background
#  - accent: primary/accent colour (buttons, focus)
#  - sel: selection or overlay tint
#
# Tip: keep fg/bg contrast ≥ 4.5:1 for body text. Accent/sel colours
# should keep selected text readable (white or very dark).
# -------------------------

THEMES: dict[str, dict[str, str]] = {
    "Dark Mode":        {"bg": "#111316", "fg": "#E6E6E6", "alt": "#161A1E", "accent": "#4C8BF5", "sel": "#2A2F3A"},
    "Slightly Dark":    {"bg": "#14161a", "fg": "#EAEAEA", "alt": "#1b1e24", "accent": "#6AA2FF", "sel": "#2f3642"},
    "Light Mode":       {"bg": "#FAFAFA", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#316DCA", "sel": "#E8F0FE"},
    "High Contrast":    {"bg": "#000000", "fg": "#FFFFFF", "alt": "#000000", "accent": "#FFD400", "sel": "#333333"},
    "Pink Holiday":     {"bg": "#1a1216", "fg": "#FFE7F3", "alt": "#23171e", "accent": "#FF5BA6", "sel": "#3a1f2c"},
    "Gothic":           {"bg": "#231128", "fg": "#F4EFFA", "alt": "#2F1B3A", "accent": "#C9A227", "sel": "#412454"},
    "Emo":              {"bg": "#000000", "fg": "#F1F1F1", "alt": "#15161A", "accent": "#FF2D95", "sel": "#2E3552"},
    "Melon":            {"bg": "#D9EF62", "fg": "#1F2328", "alt": "#A3CF5A", "accent": "#FF4044", "sel": "#FF7176"},
    "King":             {"bg": "#0B132B", "fg": "#E6EDF3", "alt": "#101B33", "accent": "#F2C94C", "sel": "#1B2A4A"},
    "Jester":           {"bg": "#0F0A14", "fg": "#EDECF5", "alt": "#161021", "accent": "#FF4D6D", "sel": "#26152F"},
}

# =========================
# Section 2 — Columns → Classification
# =========================

# ---- Tree columns (UI depends on these exact ids/order)
COLUMNS = ("inc", "rel", "name", "ext", "type", "size", "target", "notes", "conf")
HEADERS = {
    "inc": "✓",
    "rel": "Folder",
    "name": "File",
    "ext": "Ext",
    "type": "Type",
    "size": "MB",
    "target": "Target Folder",
    "notes": "Notes",
    "conf": "Conf",
}

# ---- Category order controls sort grouping in the UI
CATEGORY_ORDER = [
    "Script Mod",
    "Gameplay Mods",
    "Gameplay Tuning",
    "Adult - Gameplay",
    "Adult - CAS",
    "CAS Clothing",
    "CAS Hair",
    "CAS Accessories",
    "Build/Buy",
    "Overrides",
    "Animation",
    "Utilities",
    "Archive",
    "Other",
    "Unknown",
]

# ---- Default target folders for each category (you can rename the values)
DEFAULT_FOLDER_MAP: dict[str, str] = {
    "Script Mod": "Script Mods",
    "Gameplay Mods": "Gameplay Mods",
    "Gameplay Tuning": "Gameplay Tuning",
    "Adult - Gameplay": "Adult - Gameplay",
    "Adult - CAS": "Adult - CAS",
    "CAS Clothing": "CAS Clothing",
    "CAS Hair": "CAS Hair",
    "CAS Accessories": "CAS Accessories",
    "Build/Buy": "Build Buy",
    "Overrides": "Overrides",
    "Animation": "Animations",
    "Utilities": "Utilities",
    "Archive": "Archives",
    "Other": "Other",
    "Unknown": "Unsorted",
}

# ---- A row in the planning table
@dataclass
class FileItem:
    path: str
    name: str
    ext: str
    size_mb: float
    relpath: str
    guess_type: str
    confidence: float
    notes: str
    include: bool
    target_folder: str

# ---- General helpers

def get_default_mods_path() -> str:
    """Default Sims 4 Mods path. Change if your install differs."""
    return os.path.join(
        os.path.expanduser("~"),
        "Documents",
        "Electronic Arts",
        "The Sims 4",
        "Mods",
    )

def ensure_folder(path: str) -> None:
    """Create folder if missing."""
    os.makedirs(path, exist_ok=True)

def human_mb(size_bytes: int) -> float:
    """Convert bytes to MB with 2 decimals."""
    return round(size_bytes / (1024 * 1024), 2)

# Smarter prettifier: keeps extension, inserts spaces in Camel/PascalCase,
# splits letters↔digits, and normalises separators.
_CAMEL_SPLIT_RE = re.compile(
    r"""
    (?<=[A-Za-z])(?=[A-Z][a-z])   |  # ...aB  → a B   (TitleCase boundary)
    (?<=[a-z])(?=[A-Z])           |  # ...aB  → a B   (lower→UPPER)
    (?<=[A-Za-z])(?=\d)           |  # ...a1  → a 1   (letter→digit)
    (?<=\d)(?=[A-Za-z])              # ...1a  → 1 a   (digit→letter)
    """, re.X
)

def _humanize_stem(stem: str) -> str:
    # Normalise common separators first
    s = stem.replace("_", " ").replace("-", " ").replace(".", " ")
    # Insert spaces at camel/digit boundaries
    s = _CAMEL_SPLIT_RE.sub(" ", s)
    # Collapse repeats
    s = re.sub(r"\s+", " ", s).strip()
    return s

def prettify_for_ui(name: str) -> str:
    """Human-friendly filename for display: 'WerewolfCondomWrapper.package'
    → 'Werewolf Condom Wrapper.package'. Does not rename on disk."""
    base, ext = os.path.splitext(name)
    return f"{_humanize_stem(base)}{ext}"

def route_slot_for_category(cat: str) -> str:
    """Route any detected category label into one of the six top-level slots."""
    c = (cat or "").lower()

    # Highest priority
    if "ui cheat" in c:
        return "UI Cheats"

    # CAS buckets
    if any(k in c for k in ("cas", "adult - cas", "makeup", "eyes", "skin", "tattoo", "hair", "accessor")):
        return "CAS"

    # Build/Buy
    if "build/buy" in c or "build buy" in c or "build" in c or "recolour" in c or "recolor" in c or "object" in c:
        return "Build Mode"

    # Animations & poses
    if "animation" in c or "pose" in c:
        return "Animations"

    # Core/backends (frameworks, libraries, scripts)
    if any(k in c for k in ("script", "utility", "framework", "library")):
        return "MCC"

    # Gameplay / overrides / world / unknown → Gameplay
    return "Gameplay"


def map_type_to_folder(cat: str,
                       folder_map: dict[str, str] | None = None,
                       folder_slots: dict[str, str] | None = None) -> str:
    """
    Backwards compatible mapper:
    - if folder_slots is supplied (new six-slot model), use the router.
    - else fall back to folder_map (old per-category map).
    """
    if folder_slots:
        slot = route_slot_for_category(cat)
        return folder_slots.get(slot, slot)
    # legacy path
    folder_map = folder_map or DEFAULT_FOLDER_MAP
    return folder_map.get(cat, folder_map.get("Gameplay Mods", "Gameplay"))

def detect_real_ext(name: str) -> tuple[str, bool]:
    """
    Return (normalized_ext, disabled_flag).
    Treat *.off / *.disabled as disabled entries the user can later re-enable.
    """
    low = name.lower()
    disabled = low.endswith(".off") or low.endswith(".disabled")
    base = low
    if disabled:
        base = low[: -len(".off")] if low.endswith(".off") else low[: -len(".disabled")]
    ext = os.path.splitext(base)[1]
    return (ext if ext else ""), disabled

# One variable: sorted list of (keyword, category) tuples.
# - Keeps ALL provided entries (no removals).
# - Adds Adult signal terms and useful extras.
# - Normalises keywords to lowercase.
# - Sorted by (keyword, category) to keep lookups deterministic.

# Single variable: ALL keywords (original + extras), normalised to lowercase, sorted by (keyword, category).
# Categories are grouped with comments only for readability — the value is ONE list literal passed to sorted().
_KEYWORDS = sorted([
    # --- Script / Frameworks / Core ---
    ("ui cheats","script mod"),("uicheats","script mod"),("ui-cheats","script mod"),("cheats","script mod"),("cheat","script mod"),
    ("cmd","script mod"),("mccc","script mod"),("mc cmd center","script mod"),("mc command","script mod"),("mc command center","script mod"),
    (".ts4script","script mod"),("ts4script","script mod"),("better exceptions","script mod"),
    ("xml injector test","utility tool"),("xml injector","utility tool"),("xmlinjector","utility tool"),
    ("s4cl","utility tool"),("community library","utility tool"),("core library","utility tool"),("framework","utility tool"),("library","utility tool"),
    ("api","utility tool"),("shared","utility tool"),("tool","utility tool"),("tool v","utility tool"),("twistedmexi","utility tool"),("tmex","utility tool"),

    # --- Gameplay Tuning (non-adult) ---
    ("tuning","gameplay tuning"),("autonomy","gameplay tuning"),("module","gameplay tuning"),("overhaul","gameplay tuning"),
    ("addon","gameplay tuning"),("add-on","gameplay tuning"),("add on","gameplay tuning"),
    ("trait","gameplay tuning"),("career","gameplay tuning"),("aspiration","gameplay tuning"),
    ("buff","gameplay tuning"),("moodlet","gameplay tuning"),("interaction","gameplay tuning"),("interactions","gameplay tuning"),
    ("npc","gameplay tuning"),("patch","gameplay tuning"),("fix","gameplay tuning"),("bugfix","gameplay tuning"),
    ("lms","gameplay tuning"),("littlemssam","gameplay tuning"),("lumpinou","gameplay tuning"),
    ("royalty mod","gameplay tuning"),("royalty","gameplay tuning"),
    ("clubrequirements","gameplay tuning"),("club requirements","gameplay tuning"),("club filter","gameplay tuning"),
    ("club rules","gameplay tuning"),("clubrules","gameplay tuning"),
    ("recipe","gameplay tuning"),("recipes","gameplay tuning"),
    ("phone app","gameplay tuning"),("phoneapp","gameplay tuning"),
    ("weatherapp","gameplay tuning"),("sulsulweatherapp","gameplay tuning"),("weather app","gameplay tuning"),
    ("socialactivities","gameplay tuning"),("social activities","gameplay tuning"),
    ("live in services","gameplay tuning"),("liveinservices","gameplay tuning"),
    ("simda","gameplay tuning"),
    ("lot trait","gameplay tuning"),("lottrait","gameplay tuning"),
    ("lot challenge","gameplay tuning"),("lotchallenge","gameplay tuning"),
    ("classes","gameplay tuning"),("auto classes","gameplay tuning"),("auto-classes","gameplay tuning"),("autoclasses","gameplay tuning"),
    ("venue","gameplay tuning"),("venues","gameplay tuning"),
    ("calendar","gameplay tuning"),("bank","gameplay tuning"),("atm","gameplay tuning"),("loan","gameplay tuning"),
    ("interest","gameplay tuning"),("bill","gameplay tuning"),("utilities","gameplay tuning"),("power","gameplay tuning"),("water","gameplay tuning"),
    ("pregnancy overhaul","gameplay tuning"),("pregnancyoverhaul","gameplay tuning"),("pregnancy","gameplay tuning"),("pregnant","gameplay tuning"),
    ("miscarriage","gameplay tuning"),("abortion","gameplay tuning"),
    ("mood pack","gameplay tuning"),("moodpack","gameplay tuning"),
    ("ask","gameplay tuning"),("job","gameplay tuning"),("jobs","gameplay tuning"),

    # --- UI / Overrides ---
    ("ui override","override"),("default replacement","override"),("defaultreplac","override"),("default-replacement","override"),
    ("loading screen","override"),("cas lighting","override"),("lighting override","override"),
    ("simsiphone","override"),("iphone ui","override"),("phone ui","override"),("smartphone ui","override"),
    ("reskin","override"),("icon override","override"),
    ("cas background","override"),("default eyes","override"),("default skin","override"),("default brows","override"),("default eyebrows","override"),

    # --- CAS Clothing (garments) ---
    ("cosplay","cas clothing"),("outfit","cas clothing"),("uniform","cas clothing"),("schoolgirl","cas clothing"),("sailor","cas clothing"),
    ("kimono","cas clothing"),("cheongsam","cas clothing"),("qipao","cas clothing"),
    ("full body outfit","cas clothing"),("long sleeve","cas clothing"),("crop top","cas clothing"),
    ("top","cas clothing"),("bottom","cas clothing"),("shirt","cas clothing"),("blouse","cas clothing"),
    ("hoodie","cas clothing"),("jacket","cas clothing"),("coat","cas clothing"),
    ("dress","cas clothing"),("skirt","cas clothing"),("gown","cas clothing"),
    ("jeans","cas clothing"),("pants","cas clothing"),("trousers","cas clothing"),
    ("shorts","cas clothing"),("legging","cas clothing"),("activewear","cas clothing"),("tracksuit","cas clothing"),
    ("bikini","cas clothing"),("swimsuit","cas clothing"),("bodysuit","cas clothing"),("sweater","cas clothing"),("cardigan","cas clothing"),
    ("heels","cas clothing"),("boots","cas clothing"),("sandals","cas clothing"),
    ("sneaker","cas clothing"),("shoe","cas clothing"),("shoes","cas clothing"),
    ("underwear","cas clothing"),("knickers","cas clothing"),("boxers","cas clothing"),("socks","cas clothing"),
    ("gonna","cas clothing"),("maglietta","cas clothing"),("maternita","cas clothing"),("maternità","cas clothing"),
    ("stocking", "CAS Clothing"), ("stockings", "CAS Clothing"),

    # --- CAS Hair / Facial Hair ---
    ("hair","cas hair"),("beard","cas hair"),("mustache","cas hair"),("moustache","cas hair"),("goatee","cas hair"),("stubble","cas hair"),("sideburns","cas hair"),

    # --- CAS Makeup ---
    ("makeup","cas makeup"),("lipstick","cas makeup"),("blush","cas makeup"),("eyeliner","cas makeup"),
    ("eyeshadow","cas makeup"),("highlighter","cas makeup"),("contour","cas makeup"),("foundation","cas makeup"),

    # --- CAS Skin / Details ---
    ("skin","cas skin"),("overlay","cas skin"),("tattoo","cas skin"),
    ("eyelid","cas skin"),("eyefold","cas skin"),("freckle","cas skin"),("freckles","cas skin"),("skin detail","cas skin"),
    ("mole","cas skin"),("moles","cas skin"),("scar","cas skin"),("scars","cas skin"),

    # --- CAS Eyes ---
    ("eye","cas eyes"),("eyes","cas eyes"),("iris","cas eyes"),("pupil","cas eyes"),("heterochromia","cas eyes"),
    ("contacts","cas eyes"),("retinal","cas eyes"),

    # --- CAS Accessories / Tattoos ---
    ("glasses","cas accessories"),("spectacles","cas accessories"),("earring","cas accessories"),("eyebrow","cas accessories"),("brow","cas accessories"),
    ("lash","cas accessories"),("eyelash","cas accessories"),("ring","cas accessories"),("necklace","cas accessories"),("piercing","cas accessories"),
    ("nails","cas accessories"),("glove","cas accessories"),("bracelet","cas accessories"),("anklet","cas accessories"),("belt","cas accessories"),
    ("choker","cas accessories"),("collar","cas accessories"),("chain","cas accessories"),("barbell","cas accessories"),("stud","cas accessories"),
    ("septum","cas accessories"),("labret","cas accessories"),("industrial","cas accessories"),("bridge","cas accessories"),
    ("nose ring","cas accessories"),("lip ring","cas accessories"),("hoop","cas accessories"),
    ("gauge","cas accessories"),("eargauge","cas accessories"),
    ("headpiece","cas accessories"),("horn","cas accessories"),("horns","cas accessories"),("tail","cas accessories"),
    ("wing","cas accessories"),("wings","cas accessories"),
    ("mask","cas accessories"),
    ("tattoo","cas tattoos"),("tattoobody","cas tattoos"), ("tattoo", "CAS Tattoos"),

    # --- Build/Buy: Recolours ---
    ("recolor","buildbuy recolour"),("recolour","buildbuy recolour"),("swatch","buildbuy recolour"),

    # --- Build/Buy: Objects / Decor / Electronics ---
    ("object","buildbuy object"),("clutter","buildbuy object"),("deco","buildbuy object"),("furniture","buildbuy object"),
    ("sofa","buildbuy object"),("chair","buildbuy object"),("table","buildbuy object"),("coffee table","buildbuy object"),("dining table","buildbuy object"),
    ("end table","buildbuy object"),("side table","buildbuy object"),("bed","buildbuy object"),("nightstand","buildbuy object"),
    ("painting","buildbuy object"),("poster","buildbuy object"),("wall art","buildbuy object"),("frame","buildbuy object"),("picture frame","buildbuy object"),
    ("artwork","buildbuy object"),("canvas","buildbuy object"),("art","buildbuy object"),
    ("mirror","buildbuy object"),("plant","buildbuy object"),("rug","buildbuy object"),("curtain","buildbuy object"),
    ("window","buildbuy object"),("door","buildbuy object"),
    ("lamp","buildbuy object"),("ceiling light","buildbuy object"),("floor lamp","buildbuy object"),("wall lamp","buildbuy object"),
    ("desk","buildbuy object"),("dresser","buildbuy object"),("wardrobe","buildbuy object"),("shelf","buildbuy object"),("shelving","buildbuy object"),
    ("counter","buildbuy object"),("cabinet","buildbuy object"),
    ("stove","buildbuy object"),("oven","buildbuy object"),("fridge","buildbuy object"),("refrigerator","buildbuy object"),
    ("sink","buildbuy object"),("toilet","buildbuy object"),("shower","buildbuy object"),("bathtub","buildbuy object"),("bath","buildbuy object"),
    ("bookshelf","buildbuy object"),("bookcase","buildbuy object"),
    ("microwave","buildbuy object"),("dishwasher","buildbuy object"),
    ("washing machine","buildbuy object"),("washer","buildbuy object"),("dryer","buildbuy object"),
    ("tv","buildbuy object"),("television","buildbuy object"),("smart tv","buildbuy object"),("smartview","buildbuy object"),("monitor","buildbuy object"),("screen","buildbuy object"),
    ("computer","buildbuy object"),("pc","buildbuy object"),("laptop","buildbuy object"),("console","buildbuy object"),("speaker","buildbuy object"),
    ("stereo","buildbuy object"),("radio","buildbuy object"),("phone","buildbuy object"),("alarm","buildbuy object"),("alarmunit","buildbuy object"),

    # --- Misc Content Types ---
    ("animation","animation"),("animation pack","animation"),("anim_","animation"),("swimming","animation"),
    ("pose","pose"),("posepack","pose"),("pose pack","pose"),("cas pose","pose"),("pose player","pose"),("teleporter","pose"),
    ("preset","preset"),("slider","slider"),
    ("world","world"),("override","override"),("betterreactions","gameplay tuning"),

    # --- Adult: Gameplay / CAS / Objects (strong + weak signals and extras) ---
    ("wickedwhims","adult gameplay"),("turbodriver","adult gameplay"),("basemental","adult gameplay"),
    ("nisak","adult gameplay"),("nisa","adult gameplay"),("wild_guy","adult gameplay"),("wild guy","adult gameplay"),
    ("wickedperversions","adult gameplay"),("perversions","adult gameplay"),
    ("nsfw","adult gameplay"),("porn","adult gameplay"),("sex","adult gameplay"),("nude","adult gameplay"),("naked","adult gameplay"),
    ("strip","adult gameplay"),("lapdance","adult gameplay"),("prostitution","adult gameplay"),
    ("oral","adult gameplay"),("anal","adult gameplay"),("blowjob","adult gameplay"),("handjob","adult gameplay"),
    ("boobjob","adult gameplay"),("creampie","adult gameplay"),("cumshot","adult gameplay"),("bdsm","adult gameplay"),("bondage","adult gameplay"),("fetish","adult gameplay"),
    ("cum","adult gameplay"),("cock","adult gameplay"),
    ("lingerie","adult cas"),("pasties","adult cas"),("g-string","adult cas"),("gstring","adult cas"),("thong","adult cas"),
    ("strapon","adult cas"),("strap-on","adult cas"),("strap on","adult cas"),
    ("genital","adult cas"),("penis","adult cas"),("vagina","adult cas"),("pornstar","adult cas"),
    ("latex","adult cas"),("sheath","adult cas"),("rubber","adult cas"),("layer set","adult cas"),
    ("dildo","adult buildbuy"),("vibrator","adult buildbuy"),("plug","adult buildbuy"),("butt plug","adult buildbuy"),("buttplug","adult buildbuy"),
    ("anal beads","adult buildbuy"),
    ("wickedwhims animation","adult animation"),("ww animations","adult animation"),("ww anarcis","adult animation"),("anarcis","adult animation"),
    ("condom wrapper", "Adult CAS"), ("condomwrapper", "Adult CAS"), ("condom", "Adult BuildBuy"), ("condoms", "Adult BuildBuy"),
], key=lambda kv: (kv[0], kv[1]))

# --- Canonical category mapping (keywords may use synonyms/sub-cats)
_CANON = {
    # Adult
    "adult gameplay": "Adult - Gameplay",
    "adult animation": "Adult - Gameplay",   # funnel animations to gameplay bucket
    "adult cas": "Adult - CAS",
    "adult buildbuy": "Build/Buy",

    # Build/Buy
    "buildbuy object": "Build/Buy",
    "buildbuy recolour": "Build/Buy",

    # Utilities
    "utility tool": "Utilities",

    # CAS subtypes → closest existing buckets (adjust if you keep separate folders)
    "cas makeup": "CAS Accessories",
    "cas eyes": "CAS Accessories",
    "cas tattoos": "CAS Accessories",
    "cas skin": "CAS Accessories",
}

# Prefer longer phrases first: "phone ui" beats "phone"
_KW = sorted(((k.lower().strip(), v) for (k, v) in _KEYWORDS), key=lambda kv: (-len(kv[0]), kv[0]))

def _canon(cat: str) -> str:
    return _CANON.get(cat, cat)

# --- DBPF resource type → category hints (little-endian type IDs)
# These are safe heuristics; we don't fully parse DBPF (fast).
_RESOURCE_TYPE_HINTS = {
    0x034AEECB: ("CAS Clothing",   "DBPF: CASP"),   # CAS part
    0x015A1849: ("CAS Clothing",   "DBPF: GEOM"),   # geometry (often CAS)
    0x3453CF95: ("CAS Clothing",   "DBPF: RLE2"),   # CAS textures
    0x00B2D882: ("CAS Clothing",   "DBPF: RLE "),   # older texture chunk
    0x319E4F1D: ("Build/Buy",      "DBPF: OBJD"),   # object definition
    0x01D10F34: ("Build/Buy",      "DBPF: MLOD"),   # model LOD
    0x220557DA: ("Build/Buy",      "DBPF: STBL"),   # strings (neutral, but common)
    0x0333406C: ("Gameplay Tuning","DBPF: XML"),    # tuning xml
    0xEBCF4E9B: ("Gameplay Tuning","DBPF: SIMDATA"),# tuning simdata
    0xA0F3F4D4: ("Animation",      "DBPF: CLIP"),   # animation clip
}

# Precompute the byte sequences we want to find (little-endian)
_RESOURCE_TYPE_BYTES = {t: t.to_bytes(4, "little") for t in _RESOURCE_TYPE_HINTS.keys()}

def _scan_for_types_dbpf(path: str, head_bytes: int = 256 * 1024, tail_bytes: int = 128 * 1024) -> set[int]:
    """
    Fast string-scan for known DBPF type IDs in the head and tail of a file.
    We avoid full DBPF parsing for speed and robustness.
    Returns a set of int type IDs we detected.
    """
    hits: set[int] = set()
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            # Read head
            chunk = f.read(min(head_bytes, size))
            for tid, sig in _RESOURCE_TYPE_BYTES.items():
                if sig in chunk:
                    hits.add(tid)
            # Read tail
            if size > tail_bytes:
                f.seek(max(0, size - tail_bytes))
                chunk = f.read(tail_bytes)
                for tid, sig in _RESOURCE_TYPE_BYTES.items():
                    if sig in chunk:
                        hits.add(tid)
    except Exception:
        pass
    return hits

# Folder-name hints: if the file already lives under a meaningful folder,
# gently raise confidence toward the matching category.
_FOLDER_HINTS = {
    "mcc": "Script Mod",
    "ui cheats": "Script Mod",
    "script": "Script Mod",
    "framework": "Utilities",
    "utility": "Utilities",
    "utilities": "Utilities",
    "cas": "CAS Clothing",  # umbrella CAS bucket
    "create a sim": "CAS Clothing",
    "hair": "CAS Hair",
    "makeup": "CAS Accessories",
    "eyes": "CAS Accessories",
    "tattoo": "CAS Accessories",
    "accessor": "CAS Accessories",
    "build": "Build/Buy",
    "buy": "Build/Buy",
    "override": "Overrides",
    "overrides": "Overrides",
    "animation": "Animation",
    "animations": "Animation",
    "pose": "Animation",
    "poses": "Animation",
    "gameplay": "Gameplay Mods",
    "tuning": "Gameplay Tuning",
}

def _boost_from_parent_dirs(relpath: str, cur: tuple[str, float, str]) -> tuple[str, float, str]:
    """
    If parent directories look meaningful, nudge the classification up to 0.75 confidence.
    Never overrides a stronger (>=0.80) decision.
    """
    cat, conf, notes = cur
    if conf >= 0.80:
        return cur
    try:
        parts = [p.strip().lower() for p in os.path.dirname(relpath).split(os.sep) if p.strip()]
    except Exception:
        parts = []
    hint = None
    for p in parts[::-1]:  # nearest parent first
        for key, tgt in _FOLDER_HINTS.items():
            if key in p:
                hint = tgt
                break
        if hint:
            break
    if hint and (cat == "Unknown" or conf < 0.75):
        cat = _CANON.get(hint.lower(), hint)
        conf = 0.75
        notes = (notes + f"; parent hint: {hint}").strip("; ")
    return (cat, conf, notes)

def guess_type_for_name(name: str, ext: str) -> tuple[str, float, str]:
    """
    Tuple-aware keyword detector:
      - prioritises longer keyword hits,
      - canonicalises category labels,
      - keeps previous extension shortcuts.
    """
    n = name.lower()
    if ext == ".ts4script":
        return ("Script Mod", 0.95, "by extension")
    if ext in (".zip", ".rar", ".7z"):
        return ("Archive", 0.7, "archive")

    for kw, cat in _KW:
        if kw and kw in n:
            cat = _canon(cat)
            return (cat, 0.70, f"Keyword: {kw}")

    if ext == ".package":
        return ("Unknown", 0.40, "Package with no keyword match")
    return ("Other", 0.60, f"Unhandled ext {ext}" if ext else "No extension")

def _keywords_hit(name_lower: str, keys: list[str]) -> list[str]:
    return [k for k in keys if k in name_lower]

# ---- Binary (DBPF) peek for .package (safe/lightweight)
# Note: This is intentionally shallow. You can increase bytes to read if needed.
def guess_type_binary(path: str, current: tuple[str, float, str]) -> tuple[str, float, str]:
    """
    Deeper-but-fast DBPF probe: looks for known resource type IDs anywhere in
    the head/tail of the package. This catches CASP/OBJD/XML/CLIP, etc.
    """
    cat, conf, notes = current
    if not path.lower().endswith(".package"):
        return current
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"DBPF":
                return current
    except Exception:
        return current

    hits = _scan_for_types_dbpf(path)
    if not hits:
        return current

    # Prioritise the strongest semantic hits
    best_cat = None
    best_note = None
    # preference order
    order = [
        0x034AEECB, 0x319E4F1D, 0x0333406C, 0xEBCF4E9B, 0xA0F3F4D4,
        0x015A1849, 0x3453CF95, 0x00B2D882, 0x220557DA,
    ]
    for tid in order:
        if tid in hits:
            best_cat, best_note = _RESOURCE_TYPE_HINTS[tid]
            break

    if best_cat:
        # Raise to strong confidence if category differs or current is weak
        new_conf = max(conf, 0.85 if best_cat != cat else 0.80)
        new_notes = (notes + f"; {best_note}").strip("; ")
        return (best_cat, new_conf, new_notes)

    return current

# ---- Pluggable detector pipeline
_DETECTOR_FUNCS: dict[str, callable] = {
    "name":   lambda path, name, ext, cur: guess_type_for_name(name, ext),
    "binary": lambda path, name, ext, cur: guess_type_binary(path, cur),
    "ext":    lambda path, name, ext, cur: guess_type_for_name(name, ext),  # covered in name; left for order control
}

def classify_file(path: str, name: str, ext: str,
                  order: list[str] | None,
                  enable_binary: bool) -> tuple[str, float, str]:
    """
    Run detectors in chosen order, keep highest confidence.
    - order: list like ["name","binary","ext"]
    - enable_binary: skip 'binary' stage if False
    """
    cur: tuple[str, float, str] = ("Unknown", 0.0, "")
    order = order or DEFAULT_DETECTOR_ORDER
    for step in order:
        if step == "binary" and not enable_binary:
            continue
        fn = _DETECTOR_FUNCS.get(step)
        if not fn:
            continue
        res = fn(path, name, ext, cur)
        if not (isinstance(res, tuple) and len(res) == 3):
            continue
        cat, conf, note = res
        if conf >= cur[1]:
            merged = (cur[2] + ("; " if cur[2] and note else "") + (note or "")).strip("; ")
            cur = (cat, conf, merged)
    return cur

# =========================
# Section 3 — Scan, Bundle, Move, Undo
# =========================

# ---- Date parsing for collision decisions (filename > zip internals > m/ctime)
_MONTH = {m.lower(): i for i, m in enumerate(
    ["", "Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
)}

_DATE_PATTERNS = [
    re.compile(r'(?P<y>20\d{2})[._\- ]?(?P<m>0?[1-9]|1[0-2])[._\- ]?(?P<d>0?[1-9]|[12]\d|3[01])'),
    re.compile(r'(?P<d>0?[1-9]|[12]\d|3[01])[._\- ](?P<m>0?[1-9]|1[0-2])[._\- ](?P<y>20\d{2})'),
    re.compile(r'(?P<d>0?[1-9]|[12]\d|3[01])[\s._\-]?(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s._\-]?(?P<y>20\d{2})', re.I),
    re.compile(r'(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s._\-]?(?P<d>0?[1-9]|[12]\d|3[01])[\s._\-]?(?P<y>20\d{2})', re.I),
]

def _parse_date_from_name(name: str) -> float | None:
    s = name.lower()
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        g = m.groupdict()
        y = int(g["y"])
        if "mon" in g and g["mon"]:
            mth = _MONTH.get(g["mon"][:3].lower())
            d = int(g["d"])
        else:
            mth = int(g["m"])
            d = int(g["d"])
        try:
            return datetime.datetime(y, mth, d, 12, 0, 0).timestamp()
        except Exception:
            pass
    return None

def _date_from_zip(path: str) -> float | None:
    try:
        if not zipfile.is_zipfile(path):
            return None
        latest = None
        with zipfile.ZipFile(path, "r") as z:
            for zi in z.infolist():
                ts = datetime.datetime(*zi.date_time).timestamp()
                latest = ts if latest is None or ts > latest else latest
        return latest
    except Exception:
        return None

def best_date_for_file(path: str) -> tuple[float, str]:
    """Pick the most reliable timestamp for comparisons."""
    ts = _parse_date_from_name(os.path.basename(path))
    if ts: return ts, "filename"
    ts = _date_from_zip(path)
    if ts: return ts, "zip"
    try:  m = os.path.getmtime(path)
    except Exception: m = None
    try:  c = os.path.getctime(path)
    except Exception: c = None
    if m and c: return ((m, "mtime") if m >= c else (c, "ctime"))
    if m: return m, "mtime"
    if c: return c, "ctime"
    return 0.0, "unknown"

def plan_collisions(collisions: list[tuple[str, str, str]]) -> list[dict]:
    """
    Build a safe plan for name collisions.
    For each (src,dst), decide which is older using best available timestamps.
    Default action is PROTECT older (move to Colliding Mods) — not delete.
    """
    plan: list[dict] = []
    for src, dst, _ in collisions:
        s_ts, _sm = best_date_for_file(src)
        d_ts, _dm = best_date_for_file(dst)
        # Tie-break: keep destination (assume it's intentional/installed), so older=src
        if s_ts == d_ts:
            older_side = "src"
        else:
            older_side = "src" if s_ts < d_ts else "dst"
        plan.append({
            "src": src,
            "dst": dst,
            "src_ts": s_ts,
            "dst_ts": d_ts,
            "older": older_side,
            "protect": True,   # default SAFE: protect older (move to Colliding Mods)
        })
    return plan

# ---- Scanner
def scan_folder(root: str,
                folder_map: dict[str, str] | None = None,
                recurse: bool = True,
                ignore_exts: set[str] | None = None,
                ignore_name_contains: list[str] | None = None,
                detector_order: list[str] | None = None,
                use_binary_scan: bool = True,
                progress_cb=None,
                folder_slots: dict[str, str] | None = None) -> list[FileItem]:
    """
    Walk Mods, classify files, and return FileItems.
    """
    ignore_exts = ignore_exts or set()
    ignore_name_contains = ignore_name_contains or []
    files: list[str] = []

    for r, dnames, fnames in os.walk(root):
        for fn in fnames:
            files.append(os.path.join(r, fn))
        if not recurse:
            break

    out: list[FileItem] = []
    total = len(files)

    for i, fpath in enumerate(files, 1):
        try:
            fname = os.path.basename(fpath)
            low = fname.lower()
            ext, disabled = detect_real_ext(fname)

            if ext and not ext.startswith("."):
                ext = "." + ext
            if ext in ignore_exts:
                if progress_cb: progress_cb(i, total, fpath, "ignored_ext")
                continue
            if any(tok in low for tok in ignore_name_contains):
                if progress_cb: progress_cb(i, total, fpath, "ignored_name")
                continue

            cat, conf, notes = classify_file(
                fpath, fname, ext, order=detector_order or DEFAULT_DETECTOR_ORDER,
                enable_binary=use_binary_scan
            )
            rel = os.path.relpath(fpath, root)
            cat, conf, notes = _boost_from_parent_dirs(rel, (cat, conf, notes))
            if disabled:
                notes = (notes + "; disabled (.off)").strip("; ")

            target = map_type_to_folder(cat, folder_map, folder_slots)
            out.append(FileItem(
                path=fpath,
                name=fname,
                ext=ext,
                size_mb=human_mb(os.path.getsize(fpath)),
                relpath=os.path.relpath(fpath, root),
                guess_type=cat,
                confidence=conf,
                notes=notes,
                include=(not disabled),
                target_folder=target,
            ))
            if progress_cb: progress_cb(i, total, fpath, "ok")
        except Exception as e:
            out.append(FileItem(
                path=fpath,
                name=os.path.basename(fpath),
                ext=os.path.splitext(fpath)[1].lower(),
                size_mb=0.0,
                relpath=os.path.relpath(fpath, root) if os.path.isdir(root) else "",
                guess_type="Unknown",
                confidence=0.0,
                notes=f"scan error: {e}",
                include=False,
                target_folder=map_type_to_folder("Unknown", folder_map, folder_slots),
            ))
            if progress_cb: progress_cb(i, total, fpath, "error")

    out.sort(key=lambda fi: (
        CATEGORY_ORDER.index(fi.guess_type) if fi.guess_type in CATEGORY_ORDER else 999,
        os.path.dirname(fi.relpath).lower(),
        fi.name.lower(),
    ))
    return out

# ---- Optional: pair scripts with their packages (non-destructive)
def bundle_scripts_and_packages(items: list[FileItem]) -> None:
    """
    If a .ts4script and a .package share the same stem, push the package to
    the script's target folder (so pairs live together). Adds a small note.
    """
    by_stem_scripts: dict[str, FileItem] = {}
    for it in items:
        if it.ext == ".ts4script":
            stem = os.path.splitext(it.name)[0].lower()
            by_stem_scripts[stem] = it

    for it in items:
        if it.ext != ".package":
            continue
        stem = os.path.splitext(it.name)[0].lower()
        s = by_stem_scripts.get(stem)
        if not s:
            continue
        if it.target_folder != s.target_folder:
            it.target_folder = s.target_folder
            it.notes = (it.notes + "; paired with script").strip("; ")

# ---- Flatten + clean pass (post-move)
def _unique_path(p: str) -> str:
    base, ext = os.path.splitext(p); i = 1; out = p
    while os.path.exists(out):
        out = f"{base} ({i}){ext}"; i += 1
    return out

def flatten_and_clean_mods_root(mods_root: str,
                                folder_slots: dict[str, str],
                                use_binary_scan: bool = True) -> dict:
    """
    Promote files from nested dirs up into the correct top-level slot folders,
    then delete empty dirs. Returns summary info.
    """
    moves: list[dict] = []
    deleted = 0
    collisions: list[tuple[str,str,str]] = []

    for root, dirs, files in os.walk(mods_root, topdown=False):
        for fn in files:
            if fn.lower() in {"resource.cfg", LOG_NAME.lower()}:
                continue
            src = os.path.join(root, fn)
            ext, _ = detect_real_ext(fn)
            cat, conf, notes = classify_file(src, fn, ext, DEFAULT_DETECTOR_ORDER, use_binary_scan)
            slot = route_slot_for_category(cat)
            tgt_dir = os.path.join(mods_root, folder_slots.get(slot, slot))
            if os.path.abspath(os.path.dirname(src)) == os.path.abspath(tgt_dir):
                continue
            ensure_folder(tgt_dir)
            dst = os.path.join(tgt_dir, fn)
            if os.path.exists(dst):
                collisions.append((src, dst, "flatten name collision"))
                continue
            dst = _unique_path(dst)
            shutil.move(src, dst)
            moves.append({"from": src, "to": dst})

        if root != mods_root and not os.listdir(root):
            try:
                os.rmdir(root); deleted += 1
            except Exception:
                pass

    return {"moved": len(moves), "deleted_dirs": deleted, "collisions": collisions, "moves_log": moves}

# --- Folder name normalisation & empty-dir purge

# Synonyms/case-fixes for top-level folder names → desired name
# (Final names should match your DEFAULT_FOLDER_MAP values.)
_NORMALISE_DIRS = {
    "script mod": "Script Mods", "script mods": "Script Mods",
    "gameplay mod": "Gameplay Mods", "gameplay mods": "Gameplay Mods",
    "gameplay tuning": "Gameplay Tuning",
    "adult - gameplay": "Adult - Gameplay",
    "adult gameplay": "Adult - Gameplay",
    "adult - cas": "Adult - CAS",
    "adult cas": "Adult - CAS",
    "cas clothing": "CAS Clothing",
    "cas hair": "CAS Hair",
    "cas accessories": "CAS Accessories",
    "build buy": "Build Buy", "build/buy": "Build Buy", "build&buy": "Build Buy",
    "override": "Overrides", "overrides": "Overrides",
    "animation": "Animations", "animations": "Animations",
    "utilities": "Utilities", "utility": "Utilities",
    "archive": "Archives", "archives": "Archives",
    "other": "Other",
    "unsorted": "Unsorted",
    "colliding mods": COLLIDING_DIR_NAME,
}

_NORMALISE_DIRS.update({
    "mcc": "MCC", "mc command center": "MCC", "frameworks": "MCC", "core mods": "MCC",
    "ui cheats": "UI Cheats", "cheats": "UI Cheats", "ui mods": "UI Cheats",
    "cas": "CAS", "create a sim": "CAS",
    "build buy": "Build Mode", "build/buy": "Build Mode", "build & buy": "Build Mode", "build mode": "Build Mode",
    "gameplay": "Gameplay", "game mods": "Gameplay",
    "animation": "Animations", "animations": "Animations", "poses": "Animations", "pose": "Animations",
})

def _normalise_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("_"," ").replace("-"," ").strip().lower())

def _merge_or_rename_dir(src_dir: str, dst_dir: str) -> tuple[int,int]:
    """If dst exists, merge src into dst; else rename src→dst. Returns (moved_files, removed_dirs)."""
    moved = removed = 0
    if os.path.abspath(src_dir) == os.path.abspath(dst_dir):
        # Same path; might just be case change on Windows → force two-step rename
        parent = os.path.dirname(src_dir)
        tmp = _unique_path(os.path.join(parent, f".__tmp__{os.path.basename(dst_dir)}"))
        try:
            os.rename(src_dir, tmp)
            os.rename(tmp, dst_dir)
        except Exception:
            # Fall back to no-op if FS blocks case-only changes
            pass
        return (0, 0)

    if os.path.exists(dst_dir):
        # Merge: move files/dirs across then remove empty src
        for root, dirs, files in os.walk(src_dir, topdown=False):
            rel = os.path.relpath(root, src_dir)
            tgt_root = os.path.join(dst_dir, "" if rel == "." else rel)
            ensure_folder(tgt_root)
            for fn in files:
                s = os.path.join(root, fn)
                d = _unique_path(os.path.join(tgt_root, fn))
                try:
                    shutil.move(s, d); moved += 1
                except Exception:
                    pass
            if not os.listdir(root):
                try: os.rmdir(root); removed += 1
                except Exception: pass
        # Remove the (now empty) src_dir
        if os.path.isdir(src_dir):
            try: os.rmdir(src_dir); removed += 1
            except Exception: pass
    else:
        # Simple rename
        ensure_folder(os.path.dirname(dst_dir))
        try:
            os.rename(src_dir, dst_dir)
        except Exception:
            # Cross-device or permissions: fall back to merge semantics
            for root, dirs, files in os.walk(src_dir, topdown=False):
                rel = os.path.relpath(root, src_dir)
                tgt_root = os.path.join(dst_dir, "" if rel == "." else rel)
                ensure_folder(tgt_root)
                for fn in files:
                    s = os.path.join(root, fn)
                    d = _unique_path(os.path.join(tgt_root, fn))
                    try:
                        shutil.move(s, d); moved += 1
                    except Exception:
                        pass
                if not os.listdir(root):
                    try: os.rmdir(root); removed += 1
                    except Exception: pass
            if os.path.isdir(src_dir):
                try: os.rmdir(src_dir); removed += 1
                except Exception: pass
    return (moved, removed)

def normalise_top_level_folders(mods_root: str, folder_map: dict[str, str]) -> dict:
    """
    Ensure top-level folders match desired casing/names.
    - Renames case-insensitive matches to the exact desired name.
    - Maps common synonyms (e.g. 'override' → 'Overrides', 'cas' → 'CAS ...').
    - Creates any missing target folders.
    Returns summary dict.
    """
    renamed, merged, created = [], 0, 0

    # Desired set from folder_map + synonyms table
    desired_names = set(folder_map.values()) | set(_NORMALISE_DIRS.values())

    # Create any missing desired folders
    for name in sorted(desired_names):
        p = os.path.join(mods_root, name)
        if not os.path.isdir(p):
            try:
                os.makedirs(p, exist_ok=True); created += 1
            except Exception:
                pass

    # Build lookup for existing top-level dirs by normalised key
    existing = {}
    for entry in os.listdir(mods_root):
        p = os.path.join(mods_root, entry)
        if os.path.isdir(p):
            existing.setdefault(_normalise_key(entry), []).append(entry)

    # For each existing dir, compute the desired name (if any) and fix casing
    for key, names in existing.items():
        # pick a target: from synonyms or if key matches any desired name's key
        target = _NORMALISE_DIRS.get(key)
        if not target:
            # Try to match any desired by key
            for d in desired_names:
                if _normalise_key(d) == key:
                    target = d
                    break
        if not target:
            continue  # leave unknown folders alone

        dst = os.path.join(mods_root, target)
        for entry in names:
            src = os.path.join(mods_root, entry)
            if os.path.abspath(src) == os.path.abspath(dst) and entry == target:
                continue  # already correct
            moved, removed = _merge_or_rename_dir(src, dst)
            merged += moved
            if removed or (entry != target):
                renamed.append((entry, target))

    return {"renamed": renamed, "merged_files": merged, "created": created}

def purge_empty_dirs(mods_root: str) -> int:
    """Delete all empty directories under Mods (bottom-up), excluding Mods root."""
    removed = 0
    for root, dirs, files in os.walk(mods_root, topdown=False):
        if os.path.abspath(root) == os.path.abspath(mods_root):
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root); removed += 1
        except Exception:
            pass
    return removed

# ---- Move executor + logging + undo

def perform_moves(items: list[FileItem], mods_root: str) -> tuple[int,int,list[tuple[str,str,str]],list[dict]]:
    """
    Move included items to their target folders.
    Returns (moved_count, skipped_count, collisions, move_logs).
    """
    moved = skipped = 0
    collisions: list[tuple[str,str,str]] = []
    logs: list[dict] = []

    for it in items:
        if not it.include:
            skipped += 1
            continue
        dest_dir = os.path.join(mods_root, it.target_folder)
        ensure_folder(dest_dir)
        dest = os.path.join(dest_dir, it.name)
        if os.path.exists(dest):
            collisions.append((it.path, dest, "name collision"))
            continue
        dest = _unique_path(dest)
        shutil.move(it.path, dest)
        logs.append({"from": it.path, "to": dest})
        moved += 1

    return moved, skipped, collisions, logs

def save_moves_log(mods_root: str, logs: list[dict]) -> None:
    """Append this batch to the move log JSON (used by Undo)."""
    if not logs:
        return
    path = os.path.join(mods_root, LOG_NAME)
    data = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    data.append({"ts": time.time(), "ops": logs})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def undo_last_move(mods_root: str) -> str:
    """
    Revert the most recent batch of moves by swapping 'to' back to 'from'.
    Returns a short human-readable message.
    """
    path = os.path.join(mods_root, LOG_NAME)
    if not os.path.exists(path):
        return "No move log found."
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return "Move log unreadable."

    if not data:
        return "Move log empty."

    last = data.pop()
    undone = 0

    for op in reversed(last.get("ops", [])):
        src = op.get("from")
        dst = op.get("to")
        if not dst or not os.path.exists(dst):
            continue
        ensure_folder(os.path.dirname(src))
        try:
            shutil.move(dst, src)
            undone += 1
        except Exception:
            pass

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return f"Undid {undone} file(s)."

# =========================
# Section 4 — UI
# =========================

# ---- Settings persistence
def load_settings() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


class Sims4ModSorterApp(tk.Tk):
    """Main window and overlays."""

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.minsize(1000, 600)  # Window min size (W,H). Raise on 4K if you like.

        cfg = load_settings()

        default_slots = {slot: FOLDER_PRESETS[slot][0] for slot in TOP_SLOTS}
        self.folder_slots: dict[str, str] = cfg.get("folder_slots", default_slots)

        # Live state
        self.theme_name       = tk.StringVar(value=cfg.get("theme", "Dark Mode"))
        self.mods_root        = tk.StringVar(value=cfg.get("mods_root", get_default_mods_path()))
        self.summary_var      = tk.StringVar(value="No plan yet")
        self.status_var       = tk.StringVar(value="")
        self.items: list[FileItem] = []
        self.folder_map       = cfg.get("folder_map", DEFAULT_FOLDER_MAP.copy())
        self.use_binary_scan  = tk.BooleanVar(value=cfg.get("use_binary_scan", True))
        self.recurse_var      = tk.BooleanVar(value=cfg.get("recurse", True))
        self.ignore_exts_var  = tk.StringVar(value=cfg.get("ignore_exts", ""))   # e.g. ".txt,.md"
        self.ignore_names_var = tk.StringVar(value=cfg.get("ignore_names", ""))  # e.g. "readme,temp"
        self.detector_order   = (cfg.get("detector_order") or DEFAULT_DETECTOR_ORDER)[:]
        self.search_var       = tk.StringVar(value="")
        # Scan/Log UI state
        self.scan_started_at = 0.0
        self.scan_total = 0
        self.scan_done = 0
        self.scan_ok = 0
        self.scan_ignored = 0
        self.scan_errors = 0

        self.scan_count_var = tk.StringVar(value="0 / 0")
        self.scan_ok_var    = tk.StringVar(value="0 OK")
        self.scan_ign_var   = tk.StringVar(value="0 Ignored")
        self.scan_err_var   = tk.StringVar(value="0 Errors")
        self.scan_eta_var   = tk.StringVar(value="ETA —")
        self.cur_file_var   = tk.StringVar(value="")
        self.autoscroll_var = tk.BooleanVar(value=True)
        self._filtered_items: list[FileItem] | None = None
        self._respect_user_widths = bool(cfg.get("col_widths"))

        # Build UI
        self._build_style()
        self._build_ui()
        self._build_settings_overlay()
        self._build_collision_overlay()
        self.after(150, self._apply_launch_layout)

        # geometry (restore if saved, else a sensible default)
        g = load_settings().get("geometry") or "1400x820+120+80"
        self.geometry(g)
        self.minsize(1100, 680)  # floor so the tree never collapses

        # first clamp after everything exists
        self.after(50, self._clamp_initial_layout)

        # keep panes sensible while the user resizes
        self.bind("<Configure>", lambda e: self._on_resize())

        # save geometry on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- Style / theme

    def _build_style(self):
        self.style = ttk.Style(self)
        # Apply once now and again whenever the theme name changes
        self._apply_theme(self.theme_name.get())
        self.theme_name.trace_add("write",
            lambda *_: self._apply_theme(self.theme_name.get()))

    def _apply_theme(self, name: str):
        c = THEMES.get(name, THEMES["Dark Mode"])

        # ttk theme that honours colours
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        # Window
        self.configure(bg=c["bg"])

        # Base ttk colours
        for sty in ("TFrame", "TLabelframe", "TLabelframe.Label", "TLabel"):
            self.style.configure(sty, background=c["bg"], foreground=c["fg"])

        # Entries / Combo
        self.style.configure("TEntry", fieldbackground=c["alt"], foreground=c["fg"])
        self.style.configure("TCombobox", fieldbackground=c["alt"], foreground=c["fg"], background=c["alt"])
        try:
            self.style.configure("TCombobox", arrowcolor=c["fg"])
        except tk.TclError:
            pass

        # Treeview
        self.style.configure("Treeview", background=c["alt"], fieldbackground=c["alt"],
                             foreground=c["fg"], rowheight=22)
        self.style.map("Treeview",
                       background=[("selected", c["sel"])],
                       foreground=[("selected", c["fg"])])
        self.style.configure("Treeview.Heading", background=c["bg"], foreground=c["fg"])

        # Buttons
        def _contrast_on(hexcol: str) -> str:
            hx = hexcol.lstrip("#")
            if len(hx) == 3: hx = "".join(ch*2 for ch in hx)
            try:
                r = int(hx[0:2], 16) / 255.0
                g = int(hx[2:4], 16) / 255.0
                b = int(hx[4:6], 16) / 255.0
            except Exception:
                return "#FFFFFF"
            def lin(v): return (v/12.92) if v <= 0.03928 else ((v+0.055)/1.055) ** 2.4
            L = 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b)
            return "#000000" if L > 0.6 else "#FFFFFF"

        accent_fg = _contrast_on(c["accent"])
        self.style.configure("App.TButton", background=c["alt"], foreground=c["fg"], padding=6, relief="flat", borderwidth=1)
        self.style.map("App.TButton", background=[("active", c["sel"]), ("pressed", c["sel"])],
                       foreground=[("disabled", "#777")])

        self.style.configure("App.Accent.TButton", background=c["accent"], foreground=accent_fg,
                             padding=6, relief="flat", borderwidth=1)
        self.style.map("App.Accent.TButton", background=[("active", c["accent"]), ("pressed", c["accent"])],
                       foreground=[("disabled", "#555")])

        # Scrollbars / Progress
        self.style.configure("Vertical.TScrollbar", background=c["bg"])
        self.style.configure("Horizontal.TScrollbar", background=c["bg"])
        self.style.configure("Scan.Horizontal.TProgressbar", troughcolor=c["bg"], background=c["accent"])
        self.style.configure("Success.Horizontal.TProgressbar", troughcolor=c["bg"], background="#22C55E")
        self.style.configure("Error.Horizontal.TProgressbar", troughcolor=c["bg"], background="#EF4444")

        # Classic Tk palette (for tk.Text etc.)
        self.tk_setPalette(background=c["bg"], foreground=c["fg"],
                           activeBackground=c["sel"], activeForeground=c["fg"],
                           highlightColor=c["accent"], highlightBackground=c["bg"],
                           insertBackground=c["fg"], selectBackground=c["sel"], selectForeground=c["fg"])

        # Live widgets that need manual recolour
        self._theme = c
        if hasattr(self, "log_text"):
            self.log_text.configure(bg=c["alt"], fg=c["fg"])
            # reapply tags to pick up theme contrast
            self.log_text.tag_configure("OK",   foreground="#22C55E")
            self.log_text.tag_configure("INFO", foreground=c["fg"])
            self.log_text.tag_configure("WARN", foreground="#F59E0B")
            self.log_text.tag_configure("ERR",  foreground="#EF4444")

        # If settings overlay is open, repaint its frames too
        if hasattr(self, "overlay") and self.overlay.winfo_exists() and self.overlay.winfo_manager():
            self._settings_theme_refresh()

    # ---- Main layout

    def _build_ui(self):
        # --- Top bar -------------------------------------------------------------
        top = ttk.Frame(self); top.pack(fill="x", padx=12, pady=10)

        ttk.Label(top, text="Mods folder:").pack(side="left", padx=(0, 8))
        self.path_entry = ttk.Entry(top, textvariable=self.mods_root, width=72)
        self.path_entry.pack(side="left", padx=(0, 8))

        ttk.Button(top, text="Browse", style="App.TButton",
                   command=self.on_browse).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="Scan", style="App.TButton",
                   command=self.on_scan).pack(side="left")

        # right-side controls
        ttk.Button(top, text="Columns", style="App.TButton",
                   command=self._open_columns_dialog).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Undo Last", style="App.TButton",
                   command=self.on_undo).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="⚙", width=3, style="App.TButton",
                   command=self.toggle_settings).pack(side="right", padx=(0, 12))

        # --- Header strip: summary + filter -------------------------------------
        header = ttk.Frame(self); header.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(header, textvariable=self.summary_var).pack(side="left")
        ttk.Label(header, text="Filter:").pack(side="right")
        self.filter_entry = ttk.Entry(header, textvariable=self.search_var, width=24)
        self.filter_entry.pack(side="right", padx=(6, 0))
        self.filter_entry.bind("<KeyRelease>", self.on_filter)

        # --- Middle: paned window (tree left, selection panel right) ------------
        self.mid = ttk.PanedWindow(self, orient="horizontal")
        self.mid.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Left pane (Tree)
        left = ttk.Frame(self.mid, width=980)
        left.pack_propagate(False)
        self.mid.add(left, weight=5)

        # Right pane (selection/editor)
        right = ttk.Frame(self.mid, width=320)
        right.pack_propagate(False)
        self.mid.add(right, weight=0)

        # NEW: enforce min widths (ttk.PanedWindow needs paneconfigure, not add(..., minsize=...))
        try:
            self.mid.paneconfigure(left,  minsize=720)   # <- tweak if you want; floor for tree area
            self.mid.paneconfigure(right, minsize=280)   # <- right panel never shrinks too small
        except tk.TclError:
            pass

        # --- Tree + scrollbars ---------------------------------------------------
        # visible columns preference
        cfg_cols = load_settings().get("columns_visible")
        self.columns_visible = [c for c in (cfg_cols or COLUMNS) if c in COLUMNS] or COLUMNS[:]

        self.tree = ttk.Treeview(left, columns=COLUMNS, show="headings", selectmode="extended")

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)

        for col in COLUMNS:
            self.tree.heading(col, text=HEADERS.get(col, col), command=lambda c=col: self._sort_by(c))

        defaults = {"inc": 28, "rel": 200, "name": 360, "ext": 70, "type": 160,
                    "size": 70, "target": 200, "notes": 360, "conf": 66}
        for col, w in defaults.items():
            self.tree.column(
                col, width=w, minwidth=40, stretch=False,
                anchor=("w" if col in ("rel", "name", "target", "notes") else "center")
            )

        # restore saved widths
        saved = load_settings().get("col_widths") or {}
        if isinstance(saved, dict):
            for col, w in saved.items():
                if col in COLUMNS:
                    try: self.tree.column(col, width=int(w))
                    except Exception: pass

        # apply visible set and pack
        self._apply_displaycolumns()
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="left", fill="y")
        xsb.pack(side="bottom", fill="x")

        # persist widths after user drags a header/separator
        self.tree.bind("<ButtonRelease-1>", self._on_header_release, add="+")

        # --- Selection / editor panel -------------------------------------------
        ttk.Label(right, text="Selection").pack(anchor="w")
        self.sel_label = ttk.Label(right, text="None selected")
        self.sel_label.pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Type").pack(anchor="w")
        self.type_cb = ttk.Combobox(right, values=CATEGORY_ORDER, state="readonly")
        self.type_cb.pack(fill="x", pady=(0, 8))

        ttk.Label(right, text="Target Folder").pack(anchor="w")
        self.target_cb = ttk.Combobox(
            right, state="readonly",
            values=[self.folder_slots[s] for s in TOP_SLOTS]
        )
        self.target_cb.pack(fill="x", pady=(0, 8))
        self._refresh_target_cb_values()

        ttk.Button(right, text="Apply to Selected",      style="App.TButton",
                   command=self.on_apply_selected).pack(fill="x", pady=4)
        ttk.Button(right, text="Toggle Include",         style="App.TButton",
                   command=self.on_toggle_include).pack(fill="x", pady=4)
        ttk.Button(
            right, text="Batch Assign…", style="App.TButton",
            command=self._open_batch_assign_dialog
        ).pack(fill="x")
        ttk.Button(right, text="Recalculate Targets",    style="App.TButton",
                   command=self.on_recalc_targets).pack(fill="x", pady=4)
        ttk.Button(right, text="Select All",             style="App.TButton",
                   command=lambda: self.tree.selection_set(self.tree.get_children())).pack(fill="x", pady=2)
        ttk.Button(right, text="Select None",            style="App.TButton",
                   command=lambda: self.tree.selection_remove(self.tree.get_children())).pack(fill="x", pady=2)

        # --- Scan strip (counters + ETA) ----------------------------------------
        strip = ttk.Frame(self); strip.pack(fill="x", padx=12, pady=(4, 0))
        ttk.Label(strip, text="Scanned:").pack(side="left")
        ttk.Label(strip, textvariable=self.scan_count_var).pack(side="left", padx=(4, 12))
        ttk.Label(strip, textvariable=self.scan_ok_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_ign_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_err_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_eta_var).pack(side="left", padx=(0, 12))

        # --- Bottom bar: progress + actions -------------------------------------
        bottom = ttk.Frame(self); bottom.pack(fill="x", padx=12, pady=8)
        self.progress = ttk.Progressbar(
            bottom, orient="horizontal", mode="determinate",
            style="Scan.Horizontal.TProgressbar"
        )
        self.progress.pack(fill="x", side="left", expand=True)

        btns = ttk.Frame(bottom); btns.pack(side="right")
        ttk.Button(btns, text="Export Plan",      style="App.Accent.TButton",
                   command=self.on_export_plan).pack(side="left", padx=6)
        ttk.Button(btns, text="Complete Sorting", style="App.Accent.TButton",
                   command=self.on_complete).pack(side="left", padx=6)
        ttk.Button(btns, text="Clean Folders",    style="App.TButton",
                   command=self.on_clean_folders).pack(side="left", padx=6)

        # --- Logs ---------------------------------------------------------------
        logf = ttk.Frame(self); logf.pack(fill="both", padx=12, pady=(0, 10))
        toolbar = ttk.Frame(logf); toolbar.pack(fill="x", pady=(0, 4))
        ttk.Label(toolbar, text="Logs").pack(side="left")
        ttk.Button(toolbar, text="Clear", style="App.TButton",
                   command=lambda: (self.log_text.configure(state="normal"),
                                    self.log_text.delete("1.0", "end"),
                                    self.log_text.configure(state="disabled"))
                   ).pack(side="right", padx=(0, 8))
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.autoscroll_var).pack(side="right")

        self.log_text = tk.Text(logf, height=8, wrap="word", state="disabled", relief="flat",
                                bg=self._theme["alt"], fg=self._theme["fg"])
        self.log_text.pack(fill="both", expand=False)
        self.log_text.tag_configure("OK",   foreground="#22C55E")
        self.log_text.tag_configure("INFO", foreground=self._theme["fg"])
        self.log_text.tag_configure("WARN", foreground="#F59E0B")
        self.log_text.tag_configure("ERR",  foreground="#EF4444")

        # status line
        self.status_var.set("Ready")
        self.after(50, self._clamp_initial_layout)

    # ---- Settings overlay (inline, not modal)
    def _build_settings_overlay(self):
        c = self._theme
        theme_var = getattr(self, "theme_name", None) or getattr(self, "theme_var", None)
        if theme_var is None:
            self.theme_name = tk.StringVar(value=list(THEMES.keys())[0])
            theme_var = self.theme_name

        # Rebuild fresh
        if hasattr(self, "overlay") and self.overlay.winfo_exists():
            self.overlay.destroy()

        # Sheet covering the app (hidden until toggle_settings(True))
        self.overlay = tk.Frame(self, bg=c["sel"])
        self.overlay.place_forget()
        self.overlay.lift()

        # Card (sized later by _center_settings_card)
        self._settings_card = tk.Frame(self.overlay, bg=c["alt"], bd=0, highlightthickness=1)
        self._settings_card.configure(highlightbackground=c["sel"], highlightcolor=c["sel"])
        self._settings_card.place(relx=0.5, rely=0.5, anchor="center")

        # ----- Header
        hdr = ttk.Frame(self._settings_card); hdr.pack(fill="x", padx=20, pady=(14, 6))
        ttk.Label(hdr, text="Settings", font=("Segoe UI", 12, "bold")).pack(side="left")
        ttk.Button(hdr, text="×", width=3, style="App.TButton",
                   command=lambda: self.toggle_settings(False)).pack(side="right")

        # ----- Scrollable body (vertical)
        body_wrap = tk.Frame(self._settings_card, bg=c["alt"])
        body_wrap.pack(fill="both", expand=True)

        vcan = tk.Canvas(body_wrap, bg=c["alt"], highlightthickness=0)
        vbar = ttk.Scrollbar(body_wrap, orient="vertical", command=vcan.yview)
        vcan.configure(yscrollcommand=vbar.set)
        vcan.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=(0, 10))
        vbar.pack(side="right", fill="y", padx=(0, 20), pady=(0, 10))

        content = tk.Frame(vcan, bg=c["alt"])
        content_id = vcan.create_window((0, 0), window=content, anchor="nw")

        # Make inner frame fill the canvas width and keep the scrollregion accurate
        def _on_vcan_configure(e):
            vcan.itemconfigure(content_id, width=e.width)
        def _on_content_configure(_e=None):
            vcan.configure(scrollregion=vcan.bbox("all"))
        vcan.bind("<Configure>", _on_vcan_configure)
        content.bind("<Configure>", _on_content_configure)

        # ================= Appearance =================
        sec1 = ttk.Frame(content); sec1.pack(fill="x", pady=(6, 8))
        ttk.Label(sec1, text="Appearance", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(2, 8))

        # Theme row with its own horizontal scroller (always one row)
        row = tk.Frame(content, bg=c["alt"]); row.pack(fill="x")
        hcan = tk.Canvas(row, bg=c["alt"], height=96, highlightthickness=0)
        hbar = ttk.Scrollbar(row, orient="horizontal", command=hcan.xview)
        hcan.configure(xscrollcommand=hbar.set)
        hcan.pack(fill="x")
        hbar.pack(fill="x")

        chips_holder = tk.Frame(hcan, bg=c["alt"])
        chips_id = hcan.create_window((0, 0), window=chips_holder, anchor="nw")

        def _on_hcan_configure(e):
            # keep the chip strip height matched to canvas height
            hcan.itemconfigure(chips_id, height=e.height)
            hcan.configure(scrollregion=hcan.bbox("all"))
        chips_holder.bind("<Configure>", lambda _e: hcan.configure(scrollregion=hcan.bbox("all")))
        hcan.bind("<Configure>", _on_hcan_configure)

        self._theme_chip_frames = {}

        def _add_chip(col, name):
            sw = THEMES[name]
            fr = tk.Frame(chips_holder, bg=sw["alt"], bd=0, highlightthickness=2)
            fr.configure(highlightbackground=c["sel"], highlightcolor=c["sel"])
            fr.grid(row=0, column=col, padx=6, pady=6, sticky="n")

            tk.Frame(fr, bg=sw["accent"], height=6).pack(fill="x")
            inner = tk.Frame(fr, bg=sw["alt"]); inner.pack(fill="both", expand=True, padx=10, pady=8)
            tk.Label(inner, text=name, bg=sw["alt"], fg=sw["fg"]).pack(anchor="w")
            demo = tk.Frame(inner, bg=sw["bg"], height=30); demo.pack(fill="x", pady=(6,0))
            tk.Label(demo, text="Aa", bg=sw["bg"], fg=sw["fg"]).pack(side="left", padx=8, pady=4)
            tk.Frame(demo, bg=sw["accent"], width=44, height=18).pack(side="right", padx=8, pady=6)

            # full-tile click (recursive)
            self._bind_click_recursive(fr, lambda nm=name: self._theme_chip_clicked(nm))
            self._theme_chip_frames[name] = fr

        for idx, nm in enumerate(THEMES.keys()):
            _add_chip(idx, nm)

        self._repaint_theme_chips(theme_var.get())

        # ---- Folders (rename with presets)
        secF = ttk.Frame(content); secF.pack(fill="x", pady=(14, 4))
        ttk.Label(secF, text="Folders", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(2, 8))

        for slot in TOP_SLOTS:
            row = ttk.Frame(content); row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"{slot}").pack(side="left", padx=(0, 8))
            cb = ttk.Combobox(row, state="readonly", values=list(FOLDER_PRESETS[slot]))
            cb.set(self.folder_slots.get(slot, FOLDER_PRESETS[slot][0]))
            cb.pack(side="left")
            # bind save-back
            cb.bind("<<ComboboxSelected>>", lambda e, s=slot, c=cb: self.folder_slots.__setitem__(s, c.get()))

        # ================= Scanning =================
        sec2 = ttk.Frame(content); sec2.pack(fill="x", pady=(14, 4))
        ttk.Label(sec2, text="Scanning", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(2, 8))

        row_scan = ttk.Frame(content); row_scan.pack(fill="x", pady=(0, 6))
        ttk.Checkbutton(row_scan, text="Recurse into subfolders", variable=self.recurse_var).pack(side="left")
        ttk.Checkbutton(row_scan, text="Use binary scan (.package DBPF peek)", variable=self.use_binary_scan).pack(side="left", padx=16)

        # ================= Ignore rules =================
        sec3 = ttk.Frame(content); sec3.pack(fill="x", pady=(14, 4))
        ttk.Label(sec3, text="Ignore rules", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(2, 8))

        r_ext = ttk.Frame(content); r_ext.pack(fill="x", pady=2)
        ttk.Label(r_ext, text="Ignore extensions (e.g. .txt, .md)").pack(side="left")
        ttk.Entry(r_ext, textvariable=self.ignore_exts_var, width=46).pack(side="left", padx=8)

        r_nm = ttk.Frame(content); r_nm.pack(fill="x", pady=2)
        ttk.Label(r_nm, text="Ignore names contain (comma list)").pack(side="left")
        ttk.Entry(r_nm, textvariable=self.ignore_names_var, width=46).pack(side="left", padx=8)

        # ================= Detection order (drag & drop) =================
        sec4 = ttk.Frame(content); sec4.pack(fill="x", pady=(14, 4))
        ttk.Label(sec4, text="Detection order", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Separator(content, orient="horizontal").pack(fill="x", pady=(2, 8))

        row_det = ttk.Frame(content); row_det.pack(fill="x")
        self.lb_det = tk.Listbox(row_det, height=6, exportselection=False)
        # expand to available width
        self.lb_det.pack(side="left", fill="x", expand=True, padx=(0, 8))
        for k in self.detector_order:
            self.lb_det.insert("end", k)

        # DnD reorder
        self.lb_det.bind("<ButtonPress-1>", self._det_drag_begin)
        self.lb_det.bind("<B1-Motion>", self._det_drag_motion)
        self.lb_det.bind("<ButtonRelease-1>", self._det_drag_drop)

        det_btns = ttk.Frame(row_det); det_btns.pack(side="left")
        ttk.Button(det_btns, text="Reset", width=10, command=self._reset_detector_order).pack(fill="x", pady=2)

        # Footer
        ftr = ttk.Frame(content); ftr.pack(fill="x", pady=(16, 10))
        ttk.Button(ftr, text="Cancel", style="App.TButton",
                   command=lambda: self.toggle_settings(False)).pack(side="right")
        ttk.Button(ftr, text="Save & Close", style="App.Accent.TButton",
                   command=lambda: (self._read_detector_order(), self._refresh_target_cb_values(), self._save_live_settings(), self.toggle_settings(False))
                   ).pack(side="right", padx=8)

        # Make sure colours apply to this overlay right now
        self._settings_theme_refresh()

        # install one-time resize hook so the card always stays centred/sized
        self._install_settings_resize_watch()

    def toggle_settings(self, show: bool | None = None):
        if show is None:
            show = not bool(self.overlay.winfo_manager())
        if show:
            self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._center_settings_card()
            self.overlay.lift()
        else:
            self.overlay.place_forget()

    def _reorder_detector(self, delta: int):
        lb = self.lb_det
        sel = lb.curselection()
        if not sel: return
        i = sel[0]; j = i + delta
        if j < 0 or j >= lb.size(): return
        val = lb.get(i)
        lb.delete(i); lb.insert(j, val)
        lb.selection_clear(0, "end"); lb.selection_set(j)

    def _read_detector_order(self):
        self.detector_order = list(self.lb_det.get(0, "end"))

    def _reset_detector_order(self):
        self.lb_det.delete(0, "end")
        for k in DEFAULT_DETECTOR_ORDER:
            self.lb_det.insert("end", k)

    def _clamp_initial_layout(self):
        try:
            total = max(self.winfo_width(), 1000)
            right_min = 300
            pos = max(680, total - right_min - 40)
            self.mid.sashpos(0, pos)
        except Exception:
            pass
    
    # ---- Collision review overlay
    def _build_collision_overlay(self):
        c = self._theme
        self._col_overlay = tk.Frame(self, bg=c["sel"])
        self._col_overlay.place_forget()

        card = tk.Frame(self._col_overlay, bg=c["alt"], bd=1, relief="ridge")
        card.place(relx=0.5, rely=0.5, anchor="center")
        self._col_card = card

        ttk.Label(card, text="Collision Review", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12,6))

        cols = ("keep","older","older_date","kept","kept_date","target")
        self.col_tree = ttk.Treeview(card, columns=cols, show="headings", height=12, selectmode="extended")
        headers = {
            "keep":"Protect older?", "older":"Older file", "older_date":"Older date",
            "kept":"Newer file", "kept_date":"Newer date", "target":"Destination"
        }
        for ckey in cols:
            self.col_tree.heading(ckey, text=headers[ckey])
            self.col_tree.column(ckey, width=150 if ckey not in {"keep"} else 120, anchor="w")
        self.col_tree.pack(fill="both", expand=True, padx=16)

        btns = ttk.Frame(card); btns.pack(fill="x", padx=16, pady=(8,12))
        ttk.Button(btns, text="Protect Selected",   style="App.TButton", command=self._col_protect_selected).pack(side="left")
        ttk.Button(btns, text="Unprotect Selected", style="App.TButton", command=self._col_unprotect_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel",             style="App.TButton", command=lambda: self._toggle_collision(False)).pack(side="right")
        ttk.Button(btns, text="Confirm & Resolve",  style="App.Accent.TButton", command=self._col_apply).pack(side="right", padx=6)

        self._collision_plan: list[dict] = []

    def _toggle_collision(self, show: bool, plan: list[dict] | None = None):
        """Show/hide the collision overlay and populate rows."""
        if show:
            self._collision_plan = plan or []
            # clear
            for r in self.col_tree.get_children():
                self.col_tree.delete(r)
            # populate
            for i, p in enumerate(self._collision_plan):
                if p["older"] == "src":
                    older, newer = p["src"], p["dst"]
                    older_ts, newer_ts = p["src_ts"], p["dst_ts"]
                else:
                    older, newer = p["dst"], p["src"]
                    older_ts, newer_ts = p["dst_ts"], p["src_ts"]

                def _fmt(ts: float) -> str:
                    try:
                        if ts:
                            return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
                    except Exception:
                        pass
                    return "unknown"

                self.col_tree.insert(
                    "", "end", iid=str(i),
                    values=("Yes" if p.get("protect") else "No",
                            os.path.basename(older), _fmt(older_ts),
                            os.path.basename(newer), _fmt(newer_ts),
                            os.path.dirname(p["dst"]))
                )
            self._col_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            # centre card with sane width
            w = max(720, min(self.winfo_width()-160, 1000))
            self._col_card.configure(width=w)
            self._col_card.place_configure(relx=0.5, rely=0.5)
        else:
            self._col_overlay.place_forget()

    def _theme_chip_clicked(self, name: str):
        """Select a theme tile, live-preview it, and persist the variable."""
        var = getattr(self, "theme_name", None) or getattr(self, "theme_var", None)
        if var is None:
            self.theme_name = tk.StringVar(value=name)
            var = self.theme_name
        var.set(name)
        # live preview
        self._apply_theme(name)
        self._repaint_theme_chips(name)

    def _repaint_theme_chips(self, selected: str):
        """Update the highlight ring on theme chips."""
        for nm, fr in getattr(self, "_theme_chip_frames", {}).items():
            try:
                if nm == selected:
                    fr.configure(highlightbackground=THEMES[nm]["accent"], highlightcolor=THEMES[nm]["accent"])
                else:
                    fr.configure(highlightbackground=self._theme["sel"], highlightcolor=self._theme["sel"])
            except Exception:
                pass

    def _center_settings_card(self):
        """Size and centre the settings card based on current window geometry."""
        if not hasattr(self, "_settings_card") or not self._settings_card.winfo_exists():
            return
        # clamp to keep margins; tweak min/max if you want tighter layout
        win_w = max(self.winfo_width(), 800)
        win_h = max(self.winfo_height(), 600)
        w = max(720, min(win_w - 160, 1000))
        h = max(480, min(win_h - 160, 680))
        self._settings_card.place_configure(width=w, height=h)

    def _install_settings_resize_watch(self):
        """Bind root resize once to keep the card centred and sized."""
        if getattr(self, "_settings_resize_bound", False):
            return
        self.bind("<Configure>", self._on_root_resize, add="+")
        self._settings_resize_bound = True

    def _on_root_resize(self, _event=None):
        # When overlay visible, keep it covering and card centred
        if hasattr(self, "overlay") and self.overlay.winfo_exists() and self.overlay.winfo_manager():
            self.overlay.place_configure(relx=0, rely=0, relwidth=1, relheight=1)
            self._center_settings_card()

    def _bind_click_recursive(self, widget, cb):
        """Bind left-click to widget and all descendants (full-tile click)."""
        widget.bind("<Button-1>", lambda _e: cb())
        for ch in getattr(widget, "winfo_children", lambda: [])():
            self._bind_click_recursive(ch, cb)

    def _settings_theme_refresh(self):
        """Repaint overlay/card colours after a theme change."""
        if not hasattr(self, "overlay") or not self.overlay.winfo_exists():
            return
        c = self._theme
        try:
            self.overlay.configure(bg=c["sel"])
            self._settings_card.configure(bg=c["alt"], highlightbackground=c["sel"], highlightcolor=c["sel"])
            # repaint theme chips’ borders to match selection colour
            self._repaint_theme_chips((getattr(self, "theme_name", None) or getattr(self, "theme_var")).get())
        except Exception:
            pass

    def _apply_launch_layout(self):
        """One-shot: set the sash to give the tree most of the space and size columns."""
        try:
            if not hasattr(self, "mid") or not self.mid.winfo_ismapped():
                self.after(80, self._apply_launch_layout); return
            self.update_idletasks()

            total = self.mid.winfo_width()
            if total < 800:  # window not fully sized yet; try again shortly
                self.after(80, self._apply_launch_layout); return

            # Give the right panel a sensible fixed width and the rest to the tree
            right_w = 320  # tweak if you want the right side narrower/wider
            try:
                self.mid.sashpos(0, max(700, total - right_w))
            except tk.TclError:
                pass

            # Now set default column widths so "Target Folder" is visible by default
            self._set_tree_default_widths()
        finally:
            # Optional: also run the autosizer once (it shares spare space cleanly)
            self.after(1, self._autosize_wide_columns)


    def _set_tree_default_widths(self):
        """Initial column widths as percentages so the tree looks 'right' on open."""
        if not hasattr(self, "tree") or not self.tree.winfo_ismapped():
            return
        self.update_idletasks()
        tw = self.tree.winfo_width()
        if tw <= 0:
            return

        # Only adjust if these columns exist in your current view
        pct = {
            "rel":    0.20,  # Folder
            "name":   0.36,  # File
            "ext":    0.07,  # Ext
            "type":   0.12,  # Type
            "mb":     0.08,  # MB
            "target": 0.17,  # Target Folder
        }
        cols = set(self.tree["columns"])

        # Narrow fixed columns
        if "inc" in cols:
            self.tree.column("inc", width=24, stretch=False)

        # Apply percentages
        for col, p in pct.items():
            if col in cols:
                self.tree.column(col, width=int(tw * p), stretch=False)

    def _clamp_initial_layout(self):
        if not hasattr(self, "mid") or not self.mid.winfo_ismapped():
            return
        self.update_idletasks()
        total = self.mid.winfo_width()
        if total <= 0:
            return
        right_w = max(300, min(420, int(total * 0.25)))
        try:
            self.mid.sashpos(0, max(700, total - right_w))
        except tk.TclError:
            pass
        self.after(1, self._autosize_wide_columns)

    def _on_resize(self):
        if getattr(self, "_rsz_after", None):
            try: self.after_cancel(self._rsz_after)
            except Exception: pass
        self._rsz_after = self.after(80, self._clamp_initial_layout)

    def _autosize_wide_columns(self):
        if not hasattr(self, "tree") or not self.tree.winfo_ismapped():
            return
        self.update_idletasks()
        total = self.tree.winfo_width()
        if total <= 0:
            return
        widths = {c: int(self.tree.column(c, "width")) for c in self.tree["columns"]}
        flex = [c for c in ("name", "notes", "rel", "target") if c in widths]
        fixed = sum(widths[c] for c in self.tree["columns"] if c not in flex)
        want  = total - fixed - 20
        if want <= 0 or not flex:
            return
        share = max(1, want // len(flex))
        for c in flex:
            self.tree.column(c, width=max(widths[c], share))

    # ----- Detection order drag & drop -----
    def _det_drag_begin(self, event):
        self._det_drag_index = self.lb_det.nearest(event.y)

    def _det_drag_motion(self, event):
        i = getattr(self, "_det_drag_index", None)
        if i is None: return
        j = self.lb_det.nearest(event.y)
        if j == i or j < 0 or j >= self.lb_det.size(): return
        txt = self.lb_det.get(i)
        self.lb_det.delete(i)
        self.lb_det.insert(j, txt)
        self.lb_det.selection_clear(0, "end")
        self.lb_det.selection_set(j)
        self._det_drag_index = j

    def _det_drag_drop(self, _event):
        self._det_drag_index = None

    def _on_close(self):
        cfg = load_settings()
        cfg["geometry"] = self.geometry()
        save_settings(cfg)
        self.destroy()

# =========================
# Section 5 — Wiring & Handlers (after UI is built)
# =========================

# --- Small logger to the bottom Text box
def _safe_now():
    try:
        return time.strftime("%H:%M:%S")
    except Exception:
        return ""

def _uniq_name_in(folder: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    i = 1
    out = os.path.join(folder, name)
    while os.path.exists(out):
        out = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return out

def _norm_ignore_exts(s: str) -> set[str]:
    out = set()
    for tok in (s or "").split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        if not tok.startswith("."):
            tok = "." + tok
        out.add(tok)
    return out

def _norm_ignore_names(s: str) -> list[str]:
    out = []
    for tok in (s or "").split(","):
        tok = tok.strip().lower()
        if tok:
            out.append(tok)
    return out

def _flatten_notes(text: str) -> str:
    return "; ".join(p.strip() for p in re.split(r"[;\n]+", str(text or "")) if p.strip())

class Sims4ModSorterApp(Sims4ModSorterApp):  # extend with handlers
    # ---- utility UI methods

    def log(self, msg: str, level: str = "INFO"):
        """Append a one-line message to the log pane with colour tags."""
        level = level.upper()
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        self.log_text.configure(state="normal")
        try:
            self.log_text.insert("end", line, (level if level in {"OK","INFO","WARN","ERR"} else "INFO",))
            if self.autoscroll_var.get():
                self.log_text.see("end")
        finally:
            self.log_text.configure(state="disabled")

    # ---- Handlers

    def on_browse(self):
        """Pick Mods folder; saves to settings immediately."""
        path = filedialog.askdirectory(title="Select your Sims 4 Mods folder", mustexist=True)
        if not path:
            return
        self.mods_root.set(path)
        cfg = load_settings()
        cfg["mods_root"] = path
        save_settings(cfg)

    def on_scan(self):
        """Scan Mods, classify, and populate the table. Runs in a thread."""
        mods = self.mods_root.get()
        if not os.path.isdir(mods):
            messagebox.showerror("Scan", "Mods folder not found.")
            return

        # Pre-count files to set a correct maximum and nicer ETA
        total = 0
        for r, d, f in os.walk(mods):
            total += len(f)
            if not self.recurse_var.get():
                break
        self._progress_reset(total or 1)
        self.items = []
        self.status_var.set("Starting scan…")
        self.log("Scan started.", "INFO")

        def progress_cb(done, total_cb, path, state):
            # state from scanner: "ok", "ignored_ext", "ignored_name", "error"
            self.after(0, lambda d=done, t=total_cb, p=path, s=("ignored" if state.startswith("ignored") else state):
                             self._progress_update_ui(d, t or total, p, s))

        def worker():
            ignore_exts = _norm_ignore_exts(self.ignore_exts_var.get())
            ignore_names = _norm_ignore_names(self.ignore_names_var.get())

            items = scan_folder(
                mods,
                folder_map=self.folder_map,
                recurse=self.recurse_var.get(),
                ignore_exts=ignore_exts,
                ignore_name_contains=ignore_names,
                detector_order=self.detector_order,
                use_binary_scan=bool(self.use_binary_scan.get()),
                progress_cb=progress_cb,
                folder_slots=self.folder_slots,
            )
            bundle_scripts_and_packages(items)

            def ui_done():
                self.items = items
                self._filtered_items = None
                self._progress_finish(had_errors=(self.scan_errors > 0))
                self.summary_var.set(f"Scan complete: {len(self.items)} file(s)")
                self._refresh_tree()
                self.log(f"Scan complete. Files: {len(self.items)}, OK: {self.scan_ok}, "
                         f"Ignored: {self.scan_ignored}, Errors: {self.scan_errors}",
                         "WARN" if self.scan_errors else "OK")

            self.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()

    def on_undo(self):
        """Undo last move batch using the JSON log."""
        mods = self.mods_root.get()
        msg = undo_last_move(mods)
        self.log(msg)
        # Rescan to refresh table
        self.on_scan()

    def on_filter(self, event=None):
        """Update filtered view using the text in the Filter entry (case-insensitive)."""
        q = (self.search_var.get() or "").strip().lower()
        if not q:
            self._filtered_items = None
            self._refresh_tree()
            return
        toks = [t for t in re.split(r"[ ,;]+", q) if t]
        if not toks:
            self._filtered_items = None
            self._refresh_tree()
            return

        def match(it: FileItem) -> bool:
            blob = " ".join([it.name.lower(),
                             os.path.dirname(it.relpath or "").lower(),
                             str(it.ext).lower(),
                             str(it.guess_type).lower(),
                             (it.notes or "").lower()])
            return all(t in blob for t in toks)

        self._filtered_items = [it for it in self.items if match(it)]
        self._refresh_tree()

    def on_select(self, event=None):
        """Reflect selection into the right-hand editor."""
        sel = self.tree.selection()
        if not sel:
            self.sel_label.config(text="None selected")
            return
        self.sel_label.config(text=f"{len(sel)} selected")
        if len(sel) == 1:
            idx = int(sel[0])
            # Choose correct source list depending on filter
            src = self._filtered_items if self._filtered_items is not None else self.items
            if idx < 0 or idx >= len(src):
                return
            it = src[idx]
            self.type_cb.set(it.guess_type if it.guess_type in CATEGORY_ORDER else "")
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, it.target_folder)

    def on_double_click(self, event=None):
        """Double-click Type/Target columns to edit via the right-hand panel."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            self.on_toggle_include()
            return
        col = self.tree.identify_column(event.x)
        sel = self.tree.selection()
        if not sel:
            return
        # Type = #5, Target = #7 (based on COLUMNS order)
        if col == "#5":
            self.type_cb.focus_set()
        elif col == "#7":
            self.target_entry.focus_set()

    def on_apply_selected(self):
        """Apply the chosen Type/Target to the current selection."""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Apply to Selected", "Select one or more rows first.")
            return

        new_type = (self.type_cb.get() or "").strip()
        new_tgt  = (self.target_cb.get() or "").strip()
        if not new_type and not new_tgt:
            messagebox.showinfo("Apply to Selected", "Choose a Type and/or Target Folder first.")
            return

        items_src = self._filtered_items if self._filtered_items is not None else self.items
        key_to_item = { (os.path.dirname(it.relpath).replace("\\","/") or ".", it.name): it for it in items_src }

        changed = 0
        for iid in sel:
            key = (self.tree.set(iid, "rel"), self.tree.set(iid, "name"))
            it = key_to_item.get(key)
            if not it: continue
            if new_type:
                it.guess_type = new_type
            if new_tgt:
                it.target_folder = new_tgt
            else:
                it.target_folder = map_type_to_folder(it.guess_type, None, self.folder_slots)
            changed += 1

        if changed:
            self._refresh_tree_rows()
            self._log("OK", f"Applied to {changed} selected row(s).")

    def on_toggle_include(self):
        """Toggle Include flag for selected rows."""
        sel = self.tree.selection()
        if not sel:
            return
        src = self._filtered_items if self._filtered_items is not None else self.items
        for iid in sel:
            idx = int(iid)
            if idx < 0 or idx >= len(src):
                continue
            it = src[idx]
            it.include = not it.include
        self._refresh_tree(preserve_selection=True)

    def _open_batch_assign_dialog(self):
        """Small modal to choose scope for batch assign (no typing)."""
        if getattr(self, "_batch_win", None) and self._batch_win.winfo_exists():
            self._batch_win.lift(); return

        w = self._batch_win = tk.Toplevel(self)
        w.title("Batch Assign")
        w.transient(self); w.grab_set()
        w.resizable(False, False)

        self.batch_scope_var = tk.StringVar(value="selected")  # selected | same-type | visible

        ttk.Label(w, text="Apply the chosen Type/Target to:").pack(anchor="w", padx=12, pady=(12, 6))
        r = ttk.Frame(w); r.pack(fill="x", padx=12)

        ttk.Radiobutton(r, text="Selected rows", value="selected",
                        variable=self.batch_scope_var).pack(anchor="w")
        ttk.Radiobutton(r, text="All rows with the same current Type as the first selection",
                        value="same-type", variable=self.batch_scope_var).pack(anchor="w", pady=(4,0))
        ttk.Radiobutton(r, text="All visible rows (after filter)", value="visible",
                        variable=self.batch_scope_var).pack(anchor="w", pady=(4,8))

        btns = ttk.Frame(w); btns.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(btns, text="Cancel", style="App.TButton",
                   command=w.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Apply", style="App.Accent.TButton",
                   command=lambda: (self.on_batch_assign(), w.destroy())).pack(side="right")


    def on_batch_assign(self):
        """
        Batch-apply the Type from self.type_cb and/or Target from self.target_cb
        to a chosen scope. No typing needed.
        """
        new_type = (self.type_cb.get() or "").strip()
        new_tgt  = (self.target_cb.get() or "").strip()

        if not new_type and not new_tgt:
            messagebox.showinfo("Batch Assign", "Choose a Type and/or Target Folder first.")
            return

        # Helper: build key → FileItem mapping using (Folder, File) from the tree
        items_src = self._filtered_items if self._filtered_items is not None else self.items
        key_to_item = { (os.path.dirname(it.relpath).replace("\\","/") or ".", it.name): it for it in items_src }

        scope = getattr(self, "batch_scope_var", None)
        scope = scope.get() if scope else "selected"

        # Which rows?
        target_items: list[FileItem] = []

        if scope == "selected":
            for iid in self.tree.selection():
                key = (self.tree.set(iid, "rel"), self.tree.set(iid, "name"))
                it = key_to_item.get(key)
                if it: target_items.append(it)

        elif scope == "same-type":
            sel = self.tree.selection()
            if not sel:
                messagebox.showinfo("Batch Assign", "Select at least one row first."); return
            first_type = self.tree.set(sel[0], "type")
            target_items = [it for it in items_src if it.guess_type == first_type]

        else:  # visible
            target_items = list(items_src)

        # Apply changes
        changed = 0
        for it in target_items:
            if new_type:
                it.guess_type = new_type
            if new_tgt:
                it.target_folder = new_tgt
            else:
                # recompute from type via six-slot router
                it.target_folder = map_type_to_folder(it.guess_type, None, self.folder_slots)
            changed += 1

        if changed:
            self._refresh_tree_rows()
            self._log("OK", f"Batch updated {changed} row(s).")

    def on_recalc_targets(self) -> None:
        """Recalculate the Target folder from the current Type for all (visible) rows."""
        src = self._filtered_items if getattr(self, "_filtered_items", None) else self.items
        for it in src:
            # If you’re on the 6-folder layout with slots, use:
            # it.target_folder = map_type_to_folder(it.guess_type, None, self.folder_slots)
            it.target_folder = map_type_to_folder(it.guess_type, self.folder_map)
        self._refresh_tree_rows()

    def on_export_plan(self):
        # Export the currently visible plan (filtered if a filter is applied).
        items = self._filtered_items if self._filtered_items is not None else self.items
        if not items:
            messagebox.showinfo("Export Plan", "Nothing to export yet.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile="Sims4ModSorter_Plan.csv",
            title="Export Plan as CSV"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Folder", "File", "Ext", "Type", "MB", "Target Folder", "Notes", "Conf", "Include"])
                for it in items:
                    writer.writerow([
                        os.path.dirname(it.relpath).replace("\\", "/") or ".",
                        prettify_for_ui(it.name),
                        it.ext,
                        it.guess_type,
                        f"{it.size_mb:.2f}",
                        it.target_folder,
                        it.notes,
                        f"{it.confidence:.2f}",
                        "✓" if it.include else "✗",
                    ])
            self._log("OK", f"Exported plan → {path}")
        except Exception as e:
            self._log("ERR", f"Export failed: {e}")
            messagebox.showerror("Export Plan", f"Could not write file:\n{e}")

    def on_clean_folders(self, auto: bool = False):
        """Fix folder casing/names and remove empties. auto=True suppresses popups."""
        mods = self.mods_root.get()
        summary = flatten_and_clean_mods_root(self.mods_root.get(), self.folder_slots,
                                      use_binary_scan=self.use_binary_scan.get())
        removed = purge_empty_dirs(mods)
        self.log(f"Folders: created {summary['created']}, renamed {len(summary['renamed'])}, "
             f"merged {summary['merged_files']} files, removed {removed} empties.", "OK")
        # Refresh UI to reflect any renames
        self.on_scan()
        
    def on_complete(self):
        """
        Perform the move plan. Collisions trigger the review overlay.
        Progress bar shows per-file progress.
        """
        if not self.items:
            return
        mods = self.mods_root.get()
        # Use current view selection (include flags control what moves)
        plan = [it for it in (self._filtered_items or self.items) if it.include]
        if not plan:
            self.log("No files selected to move.")
            return

        self.log(f"Starting move of {len(plan)} file(s)…")
        self.log(f"Moving {len(plan)} file(s)…", "INFO")
        self.progress.configure(maximum=len(plan), value=0)

        def worker():
            moved_total = skipped_total = 0
            collisions_total: list[tuple[str,str,str]] = []
            moves_log_all: list[dict] = []

            for i, it in enumerate(plan, start=1):
                moved, skipped, collisions, moves_log = perform_moves([it], mods)
                moved_total += moved
                skipped_total += skipped
                collisions_total.extend(collisions)
                moves_log_all.extend(moves_log)
                self.after(0, lambda i=i: self.progress.configure(value=i))

            save_moves_log(mods, moves_log_all)

            def ui_done():
                if collisions_total:
                    plan_rows = plan_collisions(collisions_total)
                    self._toggle_collision(True, plan_rows)
                    self.status_var.set(f"Resolve {len(plan_rows)} collision(s)")
                    for s, d, r in collisions_total[:50]:
                        self.log(f"Collision: {os.path.basename(s)} -> {os.path.dirname(d)} ({r})")
                else:
                    self.status_var.set("Move complete")
                    self.on_clean_folders(auto=True)
                    self.log(f"Move complete. Moved {moved_total}, Skipped {skipped_total}, Issues 0")
                    self.on_scan()

            self.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()

    # --- Column UI helpers (MUST be inside Sims4ModSorterApp) ---

    def _apply_displaycolumns(self):
        """Show only selected columns without destroying others."""
        vis = [c for c in self.columns_visible if c in COLUMNS] or ["name"]
        self.tree.configure(displaycolumns=vis)

    def _on_header_release(self, ev=None):
        """Persist widths after a manual drag on any header/separator."""
        try:
            if self.tree.identify_region(ev.x, ev.y) not in ("separator", "heading"):
                return
        except Exception:
            pass
        self._respect_user_widths = True
        cw = {c: int(self.tree.column(c)["width"]) for c in COLUMNS}
        s = load_settings(); s["col_widths"] = cw; save_settings(s)

    def _sort_by(self, col: str):
        """Toggle sort order on a column and rebuild the view."""
        last_col = getattr(self, "_sort_col", None)
        last_desc = getattr(self, "_sort_desc", False)
        self._sort_col  = col
        self._sort_desc = (not last_desc) if (last_col == col) else False
        self._refresh_tree(preserve_selection=True)

    def _sort_key_for_item(self, it: FileItem):
        """Key fn used by _refresh_tree to sort rows."""
        col = getattr(self, "_sort_col", None)
        if not col: return 0
        if col == "name":   return prettify_for_ui(it.name).lower()
        if col == "rel":    return (os.path.dirname(it.relpath or "") or ".").lower()
        if col == "ext":    return (it.ext or "").lower()
        if col == "type":   return (it.guess_type or "").lower()
        if col == "size":   return float(getattr(it, "size_mb", 0.0))
        if col == "target": return (it.target_folder or "").lower()
        if col == "notes":  return (it.notes or "").lower()
        if col == "conf":
            try: return float(getattr(it, "confidence", 0.0))
            except Exception: return 0.0
        if col == "inc":    return 0 if it.include else 1
        return 0

    def _open_columns_dialog(self):
        """Popup with show/hide toggles for columns; persists on close."""
        win = tk.Toplevel(self)
        win.title("Columns")
        win.transient(self)
        win.resizable(False, False)
        try: win.configure(bg=self._theme["bg"])
        except Exception: pass

        vars_map = {}
        for col in COLUMNS:
            v = tk.BooleanVar(value=(col in getattr(self, "columns_visible", COLUMNS)))
            vars_map[col] = v
            ttk.Checkbutton(win, text=HEADERS.get(col, col), variable=v).pack(anchor="w", padx=12, pady=4)

        btns = ttk.Frame(win); btns.pack(fill="x", padx=12, pady=8)
        def _select_all(val: bool):
            for v in vars_map.values(): v.set(val)

        ttk.Button(btns, text="All",   style="App.TButton",   command=lambda: _select_all(True)).pack(side="left")
        ttk.Button(btns, text="None",  style="App.TButton",   command=lambda: _select_all(False)).pack(side="left", padx=6)
        ttk.Button(btns, text="Reset", style="App.TButton",
                   command=lambda: [vars_map[c].set(True) for c in COLUMNS]).pack(side="left", padx=6)

        def _apply_and_close():
            self.columns_visible = [c for c,v in vars_map.items() if v.get()]
            cfg = load_settings(); cfg["columns_visible"] = self.columns_visible; save_settings(cfg)
            self._apply_displaycolumns()
            win.destroy()

        ttk.Button(btns, text="Close", style="App.Accent.TButton", command=_apply_and_close).pack(side="right")
    
    def _progress_reset(self, total: int):
        self.scan_started_at = time.time()
        self.scan_total = total
        self.scan_done = self.scan_ok = self.scan_ignored = self.scan_errors = 0
        self.scan_count_var.set(f"0 / {total}")
        self.scan_ok_var.set("0 OK")
        self.scan_ign_var.set("0 Ignored")
        self.scan_err_var.set("0 Errors")
        self.scan_eta_var.set("ETA —")
        self.cur_file_var.set("")
        self.progress.configure(style="Scan.Horizontal.TProgressbar", maximum=max(1,total), value=0)

    def _progress_update_ui(self, done: int, total: int, path: str, state: str):
        # Counters
        self.scan_done = done
        if state in ("ok",):
            self.scan_ok += 1
        elif state in ("ignored","ignored_ext","ignored_name"):
            self.scan_ignored += 1
        elif state in ("error",):
            self.scan_errors += 1

        # ETA
        elapsed = max(0.001, time.time() - self.scan_started_at)
        rate = done / elapsed if done else 0.0
        rem = (total - done) / rate if rate > 0 else 0.0
        eta_txt = f"ETA {int(rem//60)}m {int(rem%60)}s" if rem else "ETA —"

        # UI text
        self.scan_count_var.set(f"{done} / {total}")
        self.scan_ok_var.set(f"{self.scan_ok} OK")
        self.scan_ign_var.set(f"{self.scan_ignored} Ignored")
        self.scan_err_var.set(f"{self.scan_errors} Errors")
        self.scan_eta_var.set(eta_txt)
        base = os.path.basename(path) if path else ""
        self.status_var.set(f"Scanning {done}/{total}: {base}" if base else "Scanning…")

        # Progressbar
        self.progress.configure(value=done)

    def _progress_finish(self, had_errors: bool):
        self.status_var.set("Scan complete")
        self.progress.configure(style=("Error.Horizontal.TProgressbar" if had_errors else "Success.Horizontal.TProgressbar"))
        
    # ---- Collision overlay actions

    def _col_protect_selected(self):
        for iid in self.col_tree.selection():
            i = int(iid)
            if 0 <= i < len(self._collision_plan):
                self._collision_plan[i]["protect"] = True
                self.col_tree.set(iid, "keep", "Yes")

    def _col_unprotect_selected(self):
        for iid in self.col_tree.selection():
            i = int(iid)
            if 0 <= i < len(self._collision_plan):
                self._collision_plan[i]["protect"] = False
                self.col_tree.set(iid, "keep", "No")

    def _col_apply(self):
        """
        SAFE resolution:
          - Older file is NEVER deleted.
          - If 'protect' is True (default): move older → Mods/Colliding Mods.
          - If 'protect' is False: still move older → Mods/Colliding Mods (no delete).
          - If older was the destination file, then move src into the dst path.
        This guarantees no data loss.
        """
        mods = self.mods_root.get()
        colliding_dir = os.path.join(mods, COLLIDING_DIR_NAME)
        ensure_folder(colliding_dir)
        moved_ops: list[dict] = []

        for p in list(self._collision_plan):
            src, dst = p.get("src"), p.get("dst")
            older_side = p.get("older")
            if not src or not dst:
                continue

            # Decide absolute paths
            older_path = src if older_side == "src" else dst
            newer_path = dst if older_side == "src" else src

            # Sanity: both paths must be inside Mods
            try:
                if not os.path.commonpath([mods, older_path]).startswith(os.path.abspath(mods)):
                    self.log(f"Skip collision outside Mods: {older_path}", "WARN"); continue
                if not os.path.commonpath([mods, newer_path]).startswith(os.path.abspath(mods)):
                    self.log(f"Skip collision outside Mods: {newer_path}", "WARN"); continue
            except Exception:
                # commonpath can throw on different drives; still proceed cautiously
                pass

            # If the paths are equal, do nothing
            if os.path.abspath(older_path) == os.path.abspath(newer_path):
                self.log(f"Skip identical paths: {os.path.basename(older_path)}", "WARN")
                continue

            try:
                # 1) Quarantine the older file
                if os.path.exists(older_path):
                    quarantine = _uniq_name_in(colliding_dir, os.path.basename(older_path))
                    ensure_folder(os.path.dirname(quarantine))
                    shutil.move(older_path, quarantine)
                    moved_ops.append({"from": older_path, "to": quarantine})
                    self.log(f"Quarantined older: {os.path.basename(older_path)} → {os.path.relpath(quarantine, mods)}", "OK")
                else:
                    self.log(f"Older missing, skip: {os.path.basename(older_path)}", "WARN")

                # 2) If destination was the older one we just moved away,
                #    move source into the intended destination path.
                if older_side == "dst" and os.path.exists(src):
                    ensure_folder(os.path.dirname(dst))
                    # dst path should now be free
                    final_dst = dst
                    if os.path.exists(final_dst):
                        final_dst = _uniq_name_in(os.path.dirname(dst), os.path.basename(dst))
                    shutil.move(src, final_dst)
                    moved_ops.append({"from": src, "to": final_dst})
                    self.log(f"Placed newer: {os.path.basename(src)} → {os.path.relpath(final_dst, mods)}", "OK")

            except Exception as e:
                self.log(f"Collision resolve error on {os.path.basename(older_path)}: {e}", "ERR")

        save_moves_log(mods, moved_ops)
        self._toggle_collision(False)
        # Optional tidy after resolving
        try:
            self.on_clean_folders(auto=True)
        except Exception:
            self.on_scan()

    # ---- Tree refresh & resize
    def _refresh_tree_rows(self) -> None:
        """
        Lightweight compatibility wrapper used by actions that previously
        tried to update individual rows. For now we re-render with
        selection preserved (fast enough for our table sizes).
        """
        self._refresh_tree(preserve_selection=True)

    def _refresh_tree(self, preserve_selection: bool = False) -> None:
        selected = set(self.tree.selection()) if preserve_selection else set()
        self.tree.delete(*self.tree.get_children())

        by_cat: dict[str, int] = {}
        total = len(self.items)

        for idx, it in enumerate(self.items):
            by_cat[it.guess_type] = by_cat.get(it.guess_type, 0) + 1

            inc = "✓" if it.include else ""
            rel = os.path.dirname(getattr(it, "relpath", "")) or "."

            # notes can be multi-line; flatten for a single-cell view
            flat_notes = "; ".join(
                p.strip() for p in re.split(r"[;\n]+", str(getattr(it, "notes", "") or "")) if p.strip()
            )

            vals = (
                inc,                          # Include mark
                rel,                          # Folder (relative)
                prettify_for_ui(it.name),     # File
                it.ext,                       # Ext
                it.guess_type,                # Type
                f"{getattr(it, 'size_mb', 0.0):.2f}",  # MB
                it.target_folder,             # Target Folder
                flat_notes,                   # Notes
                f"{getattr(it, 'confidence', 0.0):.2f}",  # Conf
            )
            iid = str(idx)
            self.tree.insert("", "end", iid=iid, values=vals)
            if iid in selected:
                self.tree.selection_add(iid)

        if total:
            topcats = sorted(by_cat.items(), key=lambda kv: -kv[1])[:4]
            frag = ", ".join(f"{k}: {v}" for k, v in topcats)
            self.summary_var.set(f"Planned {total} files | {frag}")
        else:
            self.summary_var.set("No plan yet")

        self._on_resize()

    def _on_resize(self, event=None):
        if getattr(self, "_respect_user_widths", False):
            return
        if load_settings().get("col_widths"):
            return
        # first-run only, gentle widening (optional)
        try:
            cur_w = self.tree.winfo_width()
        except Exception:
            return
        if cur_w < 900:
            return
        base = {"name": 360, "notes": 360}
        extra = max(0, cur_w - 1100)
        self.tree.column("name",  width=base["name"]  + int(extra * 0.55))
        self.tree.column("notes", width=base["notes"] + int(extra * 0.45))

    # ---- Settings save/load

    def _save_live_settings(self):
        """Write current in-memory settings to disk."""
        try:
            cfg = load_settings()
            cfg["folder_slots"] = self.folder_slots
            save_settings(cfg)
            cfg.update(dict(
                mods_root=self.mods_root.get(),
                theme=self.theme_name.get(),
                use_binary_scan=bool(self.use_binary_scan.get()),
                recurse=bool(self.recurse_var.get()),
                ignore_exts=self.ignore_exts_var.get(),
                ignore_names=self.ignore_names_var.get(),
                folder_map=self.folder_map,
                detector_order=self.detector_order,
            ))
            # Remember widths if user set them
            if getattr(self, "_respect_user_widths", False):
                cfg["col_widths"] = {c: int(self.tree.column(c)["width"]) for c in COLUMNS}
            save_settings(cfg)
            self.log("Settings saved.")
        except Exception as e:
            self.log(f"Settings save failed: {e}")

    def _refresh_target_cb_values(self):
        if hasattr(self, "target_cb") and self.target_cb.winfo_exists():
            self.target_cb["values"] = [self.folder_slots[s] for s in TOP_SLOTS]

# ---- Entry point
if __name__ == "__main__":
    # For no console window, run with pythonw.exe on Windows or rename to .pyw
    app = Sims4ModSorterApp()
    try:
        # Start centered-ish
        app.update_idletasks()
        w, h = 1100, 720   # Tweakable default window size (min safe: 1000x600)
        x = max(0, (app.winfo_screenwidth()  - w) // 2)
        y = max(0, (app.winfo_screenheight() - h) // 3)
        app.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        pass
    app.mainloop()
