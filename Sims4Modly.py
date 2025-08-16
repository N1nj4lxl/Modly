# Sims4 Mod Sorter — single file (fixed)
# Python 3.10+
import os, re, io, json, time, shutil, struct, zipfile, threading, tkinter as tk
from dataclasses import dataclass
from tkinter import ttk, filedialog, messagebox
from typing import List, Dict, Tuple, Optional
import urllib.request
import urllib.parse
import csv
from datetime import datetime
import calendar

_WORD_SEP = re.compile(r"[_\-\.\[\]\(\)\{\}/\\]+")
_CAMEL_SPLIT = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPACE = re.compile(r"\s+")
WORD_SPLIT = re.compile(r"[^a-z0-9]+", re.I)

def _norm_name(s: str) -> str:
    return " ".join(t for t in WORD_SPLIT.split(s.lower()) if t)

def _family_key(s: str) -> str:
    n = re.sub(r'\.[^.]+$', '', s).lower()
    n = re.sub(r'[_\-\.\[\]\(\)\{\}\s]+', ' ', n)
    n = re.sub(r'\b(v|ver|version)\s*\d+(?:\.\d+)*\b', '', n)
    n = re.sub(r'\b(merged|pack|set|update|fix)\b', '', n)
    return " ".join(n.split()[:5]).strip()

def _adultize(cat: str) -> str:
    m = {
        "Script Mod": "Adult Script", "Gameplay Tuning": "Adult Gameplay",
        "Animation": "Adult Animation", "Pose": "Adult Pose", "Override": "Adult Override",
        "CAS Hair": "Adult CAS", "CAS Clothing": "Adult CAS", "CAS Makeup": "Adult CAS",
        "CAS Skin": "Adult CAS", "CAS Eyes": "Adult CAS", "CAS Accessories": "Adult CAS",
        "BuildBuy Object": "Adult BuildBuy", "BuildBuy Recolour": "Adult BuildBuy",
        "Other": "Adult Other", "Unknown": "Adult Other",
    }
    return m.get(cat, cat)

def family_label(filename: str) -> str:
    base = filename.rsplit(".", 1)[0].lower()
    tokens = [t for t in WORD_SPLIT.split(base) if t and t not in
              {"v","ver","version","merged","pack","set","update","fix"}]
    if not tokens:
        tokens = [t for t in WORD_SPLIT.split(base) if t][:3]
    return " ".join(w[:1].upper()+w[1:] for w in tokens[:3])

COLLIDING_DIR_NAME = "Colliding Mods"

_DATE_PATTERNS = [
    # 2024-08-15, 2024_08_15, 20240815
    re.compile(r'(?P<y>20\d{2})[._\- ]?(?P<m>0?[1-9]|1[0-2])[._\- ]?(?P<d>0?[1-9]|[12]\d|3[01])'),
    # 15-08-2024, 15_08_2024
    re.compile(r'(?P<d>0?[1-9]|[12]\d|3[01])[._\- ](?P<m>0?[1-9]|1[0-2])[._\- ](?P<y>20\d{2})'),
    # 15 Aug 2024 / Aug 15 2024 / 15-Aug-2024
    re.compile(r'(?P<d>0?[1-9]|[12]\d|3[01])[\s._\-]?(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s._\-]?(?P<y>20\d{2})', re.I),
    re.compile(r'(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s._\-]?(?P<d>0?[1-9]|[12]\d|3[01])[\s._\-]?(?P<y>20\d{2})', re.I),
]

_MON = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MON.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})

def _parse_date_from_name(name: str) -> tuple[float|None,str]:
    s = name.lower()
    for pat in _DATE_PATTERNS:
        m = pat.search(s)
        if not m: 
            continue
        gd = m.groupdict()
        y = int(gd.get("y"))
        if "mon" in gd and gd.get("mon"):
            mth = _MON.get(gd["mon"][:3].lower())
            if not mth: 
                continue
            d = int(gd.get("d"))
        else:
            mth = int(gd.get("m"))
            d = int(gd.get("d"))
        try:
            ts = datetime(y, mth, d, 12, 0, 0).timestamp()
            return ts, "filename"
        except Exception:
            continue
    return None, ""

def _date_from_zip(path: str) -> tuple[float|None,str]:
    try:
        if not zipfile.is_zipfile(path):
            return None, ""
        latest = None
        with zipfile.ZipFile(path, "r") as z:
            for zi in z.infolist():
                try:
                    ts = datetime(*zi.date_time).timestamp()
                    latest = ts if latest is None or ts > latest else latest
                except Exception:
                    continue
        return (latest, "zip-internal") if latest else (None, "")
    except Exception:
        return None, ""

def best_date_for_file(path: str) -> tuple[float,str]:
    """
    Returns (timestamp, source). Priority:
    1) explicit date in filename
    2) for zips/ts4script: newest internal file date
    3) filesystem modified time
    4) filesystem created/metadata time (Windows)
    Always returns something.
    """
    name = os.path.basename(path)
    ts, src = _parse_date_from_name(name)
    if ts: 
        return ts, src

    ts, src = _date_from_zip(path)
    if ts: 
        return ts, src

    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = None
    try:
        ctime = os.path.getctime(path)
    except Exception:
        ctime = None

    if mtime and ctime:
        # pick the newer to represent “this build looks newer”
        if mtime >= ctime:
            return mtime, "mtime"
        else:
            return ctime, "ctime"
    if mtime:
        return mtime, "mtime"
    if ctime:
        return ctime, "ctime"
    # last resort: now - 50 years (should never happen)
    return 0.0, "unknown"

def plan_collisions(collisions: list[tuple[str,str,str]]) -> list[dict]:
    """
    collisions: [(src_path, dst_path, reason)]
    Returns list of dicts:
      {src, dst, src_ts, src_src, dst_ts, dst_src, older: 'src'|'dst', protect: False}
    """
    plan = []
    for src, dst, _ in collisions:
        s_ts, s_src = best_date_for_file(src)
        d_ts, d_src = best_date_for_file(dst)
        older = "src" if s_ts < d_ts else "dst"
        plan.append({
            "src": src, "dst": dst,
            "src_ts": s_ts, "src_src": s_src,
            "dst_ts": d_ts, "dst_src": d_src,
            "older": older, "protect": False
        })
    return plan

# --- Name normalisation for matching and display ---

_CAMEL_LOWER_TO_UPPER = re.compile(r'(?<=[a-z0-9])(?=[A-Z])')
_ACRONYM_TO_WORD      = re.compile(r'(?<=[A-Z])(?=[A-Z][a-z])')
_DIGIT_LETTER_BOUND   = re.compile(r'(?<=[A-Za-z])(?=[0-9])|(?<=[0-9])(?=[A-Za-z])')
_SEP_CHARS            = re.compile(r'[\._\-]+')
_MULTI_SPACE          = re.compile(r'\s+')

def _normalise_core(s: str) -> str:
    s = os.path.splitext(s)[0]
    s = _SEP_CHARS.sub(' ', s)
    s = _ACRONYM_TO_WORD.sub(' ', s)
    s = _CAMEL_LOWER_TO_UPPER.sub(' ', s)
    s = _DIGIT_LETTER_BOUND.sub(' ', s)
    s = _MULTI_SPACE.sub(' ', s).strip()
    return s

def normalise_for_match(name: str) -> str:
    return _normalise_core(name).lower()

def prettify_for_ui(n: str) -> str:
    """Human-friendly file name: split delimiters + camelCase, collapse spaces, Title Case small words lightly."""
    base = re.sub(r'\.[^.]+$', '', n)                           # drop last extension
    base = re.sub(r'[_\-\.\[\]\(\)\{\}/\\]+', ' ', base)        # split common delimiters
    base = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', base)         # split CamelCase
    base = re.sub(r'\s+', ' ', base).strip()
    words = []
    for w in base.split():
        if len(w) <= 4 and w.isupper():                         # keep acronyms
            words.append(w)
        else:
            words.append(w[:1].upper() + w[1:])
    return ' '.join(words)

def detect_real_ext(fname: str) -> tuple[str, bool]:
    """
    Return ('normalized_ext', disabled) where normalized_ext is the logical file type.
    Handles things like *.package.off or *.ts4script.zip.
    """
    low = fname.lower()
    if low.endswith(".package.off"):
        return ".package", True
    if low.endswith(".ts4script.zip") or low.endswith(".ts4script.rar") or low.endswith(".ts4script.7z"):
        return ".ts4script", False
    # fall back to the last extension
    return os.path.splitext(fname)[1].lower(), False

# ---------------------------
# Data model
# ---------------------------
@dataclass
class FileItem:
    path: str
    name: str
    ext: str
    size_mb: float
    relpath: str = ""
    guess_type: str = "Unknown"
    confidence: float = 0.0
    notes: str = ""
    include: bool = True
    target_folder: str = "Unknown"
    bundle: str = ""      # script-package pairing key
    meta_tags: str = ""   # e.g., "CASP, OBJD, STBL"
    family: str = ""

# ---------------------------
# Categories and folders
# ---------------------------

# --- relatedwords.io integration (condom) ---
RELATEDWORDS_CACHE = {}
ADULT_RW_TERMS = set()

def _fetch_relatedwords_io(term: str, max_terms: int = 150, timeout: int = 10) -> List[str]:
    url = f"https://relatedwords.io/{urllib.parse.quote(term)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")
    raw = re.findall(r">([^<]{1,40})</a>", html)
    words = []
    seen = set()
    STOP = {"starting with a","starting with b","starting with c","starting with d","starting with e",
            "starting with f","starting with g","starting with h","starting with i","starting with j",
            "starting with k","starting with l","starting with m","starting with n","starting with o",
            "starting with p","starting with q","starting with r","starting with s","starting with t",
            "starting with u","starting with v","starting with w","starting with x","starting with y",
            "starting with z","close","sort by:","also related to:","highlight:"}
    for w in raw:
        w2 = w.strip().lower()
        if not w2 or w2 in seen: 
            continue
        if w2 in STOP: 
            continue
        if not all(ch.isalpha() or ch in " -'" for ch in w2):
            continue
        seen.add(w2); words.append(w2)
        if len(words) >= max_terms:
            break
    return words

def _load_relatedwords_condom(force: bool = False) -> set:
    global ADULT_RW_TERMS
    if ADULT_RW_TERMS and not force:
        return ADULT_RW_TERMS
    try:
        if "condom" not in RELATEDWORDS_CACHE or force:
            RELATEDWORDS_CACHE["condom"] = _fetch_relatedwords_io("condom", max_terms=180)
        terms = set(RELATEDWORDS_CACHE["condom"])
        NOISE = {"water","mask","butter","texas","cigarette","banana","sunscreen","marijuana",
                 "gluten","advertisement","advertisements","catholic","catholicism","diaper"}
        terms = {t for t in terms if t not in NOISE and len(t) >= 3}
        KEEP_PAT = re.compile(r"(condom|rubber|sheath|prophyl|latex|poly(?:urethane|isoprene)|"
                              r"contracept|birth control|sti|std|sexual|sex|intercourse|hiv|aids|"
                              r"penis|vagina|genital|ejac|orgasm|sperm|spermicid|lube|lubricant|"
                              r"durex|dam|diaphragm|female condom|chlamydia|syphilis|gonorrhea|hpv|iud)")
        terms = {t for t in terms if KEEP_PAT.search(t)}
        seeds = {"condom","condoms","rubber","sheath","prophylactic","latex","spermicide",
                 "personal lubricant","lube","durex","female condom"}
        ADULT_RW_TERMS = terms | seeds
    except Exception:
        ADULT_RW_TERMS = {"condom","condoms","rubber","sheath","prophylactic","latex","spermicide",
                          "personal lubricant","lube","durex","female condom"}
    return ADULT_RW_TERMS

def normalize_for_keywords(raw: str) -> str:
    s = raw.lower()
    s = re.sub(r"[\[\]\(\)\{\}]", " ", s)
    s = re.sub(r"[_\-\.\+]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

WORLD_TOKENS = {
    "willowcreek","oasisprings","magnoliapromenade","newcrest","windenburg","sanmyschuno",
    "forgottenhollow","brindletonbay","del","sol","valley","strangerville","glimmerbrook",
    "evergreenharbor","batuu","henfordonbagley","copperdale","sansequoia","tomarang",
}
VARIANT_TOKENS = {
    "m","f","am","af","male","female","child","teen","toddler","infant","adult",
    "blue","green","red","purple","magenta","orange","yellow","crimson","skyblue","steelblue",
    "humans","wolves","wolfs","wolf","human","amf","afm",
    "v1","v2","v3","v4",
}

def compute_family_label(filename: str) -> str:
    s = normalize_for_keywords(filename)
    toks = s.split()
    if not toks: 
        return s
    trimmed = list(toks)
    while trimmed:
        last = trimmed[-1]
        if last.isdigit() or last in WORLD_TOKENS or last in VARIANT_TOKENS:
            trimmed.pop()
        else:
            break
    if not trimmed:
        trimmed = toks[:2]
    fam = " ".join(trimmed[:3])
    pretty = " ".join(w if w.isupper() and len(w) <= 4 else (w[:1].upper() + w[1:]) for w in fam.split())
    return pretty

# ===== Heuristic keywords (name-first, normal before adult) =====
# (token, category)
KEYWORD_MAP: List[Tuple[str, str]] = [
    # Script / frameworks / tuning (non-adult)
    ("ui cheats", "Script Mod"), ("uicheats", "Script Mod"), ("cheats", "Script Mod"), ("cheat", "Script Mod"), ("cmd", "Script Mod"),
    ("mccc", "Script Mod"), ("mc cmd center", "Script Mod"), ("mc command", "Script Mod"),
    ("xml injector test", "Utility Tool"), ("xml injector", "Utility Tool"), ("xmlinjector", "Utility Tool"),
    ("s4cl", "Utility Tool"), ("community library", "Utility Tool"), ("framework", "Utility Tool"), ("library", "Utility Tool"),
    (".ts4script", "Script Mod"),
    ("better exceptions", "Script Mod"),
    ("core library", "Utility Tool"), ("api", "Utility Tool"), ("shared", "Utility Tool"),

    # Gameplay tuning
    ("tuning", "Gameplay Tuning"), ("autonomy", "Gameplay Tuning"),
    ("module", "Gameplay Tuning"), ("overhaul", "Gameplay Tuning"),
    ("addon", "Gameplay Tuning"), ("add-on", "Gameplay Tuning"), ("add on", "Gameplay Tuning"),
    ("trait", "Gameplay Tuning"), ("career", "Gameplay Tuning"), ("aspiration", "Gameplay Tuning"),
    ("buff", "Gameplay Tuning"), ("moodlet", "Gameplay Tuning"), ("interaction", "Gameplay Tuning"),
    ("interactions", "Gameplay Tuning"), ("npc", "Gameplay Tuning"), ("patch", "Gameplay Tuning"),
    ("fix", "Gameplay Tuning"), ("bugfix", "Gameplay Tuning"), ("lms", "Gameplay Tuning"),
    ("littlemssam", "Gameplay Tuning"), ("lumpinou", "Gameplay Tuning"),
    ("royalty mod", "Gameplay Tuning"), ("royalty", "Gameplay Tuning"),
    ("clubrequirements", "Gameplay Tuning"), ("club requirements", "Gameplay Tuning"), ("club filter", "Gameplay Tuning"),
    ("recipe", "Gameplay Tuning"), ("recipes", "Gameplay Tuning"),
    ("phone app", "Gameplay Tuning"), ("phoneapp", "Gameplay Tuning"),
    ("weatherapp", "Gameplay Tuning"), ("sulsulweatherapp", "Gameplay Tuning"),
    ("socialactivities", "Gameplay Tuning"), ("social activities", "Gameplay Tuning"),
    ("live in services", "Gameplay Tuning"), ("liveinservices", "Gameplay Tuning"),
    ("simda", "Gameplay Tuning"),
    ("lot trait", "Gameplay Tuning"), ("lottrait", "Gameplay Tuning"),
    ("lot challenge", "Gameplay Tuning"), ("lotchallenge", "Gameplay Tuning"),
    ("classes", "Gameplay Tuning"), ("auto classes", "Gameplay Tuning"), ("auto-classes", "Gameplay Tuning"),
    ("venue", "Gameplay Tuning"), ("venues", "Gameplay Tuning"),
    ("calendar", "Gameplay Tuning"), ("bank", "Gameplay Tuning"), ("atm", "Gameplay Tuning"),
    ("loan", "Gameplay Tuning"), ("interest", "Gameplay Tuning"), ("bill", "Gameplay Tuning"),
    ("utilities", "Gameplay Tuning"), ("power", "Gameplay Tuning"), ("water", "Gameplay Tuning"),
    ("pregnancy overhaul", "Gameplay Tuning"), ("pregnancyoverhaul", "Gameplay Tuning"),
    ("pregnancy", "Gameplay Tuning"), ("pregnant", "Gameplay Tuning"),
    ("miscarriage", "Gameplay Tuning"), ("abortion", "Gameplay Tuning"),
    ("mood pack", "Gameplay Tuning"), ("moodpack", "Gameplay Tuning"),
    ("autoclasses", "Gameplay Tuning"),
    ("weather app", "Gameplay Tuning"),
    ("club rules", "Gameplay Tuning"), ("clubrules", "Gameplay Tuning"),

    # UI / overrides
    ("ui override", "Override"), ("default replacement", "Override"), ("defaultreplac", "Override"),
    ("loading screen", "Override"), ("cas lighting", "Override"), ("lighting override", "Override"),
    ("simsiphone", "Override"), ("iphone ui", "Override"), ("phone ui", "Override"), ("smartphone ui", "Override"),
    ("default-replacement", "Override"),
    ("reskin", "Override"),
    ("icon override", "Override"),

    # CAS clothing & accessories
    ("cosplay", "CAS Clothing"), ("outfit", "CAS Clothing"), ("uniform", "CAS Clothing"), ("schoolgirl", "CAS Clothing"), ("sailor", "CAS Clothing"),
    ("kimono", "CAS Clothing"), ("cheongsam", "CAS Clothing"), ("qipao", "CAS Clothing"),
    ("full body outfit", "CAS Clothing"), ("long sleeve", "CAS Clothing"), ("crop top", "CAS Clothing"),
    ("top", "CAS Clothing"), ("bottom", "CAS Clothing"), ("shirt", "CAS Clothing"), ("blouse", "CAS Clothing"),
    ("hoodie", "CAS Clothing"), ("jacket", "CAS Clothing"), ("coat", "CAS Clothing"),
    ("dress", "CAS Clothing"), ("skirt", "CAS Clothing"), ("gown", "CAS Clothing"),
    ("jeans", "CAS Clothing"), ("pants", "CAS Clothing"), ("trousers", "CAS Clothing"),
    ("shorts", "CAS Clothing"), ("legging", "CAS Clothing"),
    ("gonna", "CAS Clothing"), ("maglietta", "CAS Clothing"), ("maternita", "CAS Clothing"), ("maternità", "CAS Clothing"),
    ("stocking", "CAS Clothing"), ("stockings", "CAS Clothing"),
    ("tights", "CAS Clothing"), ("pantyhose", "CAS Clothing"),
    ("sneaker", "CAS Clothing"), ("shoe", "CAS Clothing"), ("shoes", "CAS Clothing"),
    ("underwear", "CAS Clothing"), ("knickers", "CAS Clothing"), ("boxers", "CAS Clothing"),

    ("hair", "CAS Hair"),
    ("makeup", "CAS Makeup"), ("lipstick", "CAS Makeup"), ("blush", "CAS Makeup"), ("eyeliner", "CAS Makeup"),
    ("skin", "CAS Skin"), ("overlay", "CAS Skin"), ("tattoo", "CAS Skin"),

    ("eye", "CAS Eyes"), ("eyes", "CAS Eyes"), ("iris", "CAS Eyes"),
    ("eyelid", "CAS Skin"), ("eyefold", "CAS Skin"),
    ("freckle", "CAS Skin"), ("skin detail", "CAS Skin"),
    ("contacts", "CAS Eyes"), ("retinal", "CAS Eyes"),

    ("glasses", "CAS Accessories"), ("spectacles", "CAS Accessories"),
    ("earring", "CAS Accessories"), ("eyebrow", "CAS Accessories"), ("brow", "CAS Accessories"),
    ("lash", "CAS Accessories"), ("eyelash", "CAS Accessories"),
    ("ring", "CAS Accessories"), ("necklace", "CAS Accessories"), ("piercing", "CAS Accessories"),
    ("nails", "CAS Accessories"), ("glove", "CAS Accessories"),
    ("headpiece", "CAS Accessories"), ("horn", "CAS Accessories"), ("horns", "CAS Accessories"),
    ("tail", "CAS Accessories"), ("wing", "CAS Accessories"), ("wings", "CAS Accessories"),
    ("tattoo", "CAS Tattoos"), ("tattoobody", "CAS Tattoos"),
    ("choker", "CAS Accessories"), ("collar", "CAS Accessories"),
    ("chain", "CAS Accessories"), ("barbell", "CAS Accessories"), ("stud", "CAS Accessories"),
    ("septum", "CAS Accessories"), ("labret", "CAS Accessories"),
    ("industrial", "CAS Accessories"), ("bridge", "CAS Accessories"),
    ("nose ring", "CAS Accessories"), ("lip ring", "CAS Accessories"),
    ("hoop", "CAS Accessories"), ("gauge", "CAS Accessories"), ("eargauge", "CAS Accessories"),
    ("bracelet", "CAS Accessories"), ("anklet", "CAS Accessories"), ("belt", "CAS Accessories"),
    ("mask", "CAS Accessories"),

    # Build/Buy objects & recolours
    ("recolor", "BuildBuy Recolour"), ("recolour", "BuildBuy Recolour"), ("swatch", "BuildBuy Recolour"),
    ("object", "BuildBuy Object"), ("clutter", "BuildBuy Object"), ("deco", "BuildBuy Object"),
    ("furniture", "BuildBuy Object"), ("sofa", "BuildBuy Object"), ("chair", "BuildBuy Object"),
    ("table", "BuildBuy Object"), ("coffee table", "BuildBuy Object"), ("bed", "BuildBuy Object"),
    ("painting", "BuildBuy Object"), ("poster", "BuildBuy Object"), ("wall art", "BuildBuy Object"),
    ("mirror", "BuildBuy Object"), ("plant", "BuildBuy Object"), ("rug", "BuildBuy Object"),
    ("curtain", "BuildBuy Object"), ("window", "BuildBuy Object"), ("door", "BuildBuy Object"),
    ("lamp", "BuildBuy Object"), ("ceiling light", "BuildBuy Object"),
    ("floor lamp", "BuildBuy Object"), ("wall lamp", "BuildBuy Object"),
    ("tv", "BuildBuy Object"), ("television", "BuildBuy Object"), ("monitor", "BuildBuy Object"),
    ("screen", "BuildBuy Object"), ("computer", "BuildBuy Object"), ("pc", "BuildBuy Object"),
    ("laptop", "BuildBuy Object"), ("console", "BuildBuy Object"), ("speaker", "BuildBuy Object"),
    ("stereo", "BuildBuy Object"), ("radio", "BuildBuy Object"), ("phone", "BuildBuy Object"),
    ("alarm", "BuildBuy Object"), ("alarmunit", "BuildBuy Object"),
    ("desk", "BuildBuy Object"), ("dresser", "BuildBuy Object"), ("wardrobe", "BuildBuy Object"),
    ("counter", "BuildBuy Object"), ("cabinet", "BuildBuy Object"),
    ("stove", "BuildBuy Object"), ("oven", "BuildBuy Object"),
    ("fridge", "BuildBuy Object"), ("refrigerator", "BuildBuy Object"),
    ("sink", "BuildBuy Object"), ("toilet", "BuildBuy Object"),
    ("shower", "BuildBuy Object"), ("bathtub", "BuildBuy Object"), ("bath", "BuildBuy Object"),
    ("frame", "BuildBuy Object"), ("picture frame", "BuildBuy Object"),
    ("artwork", "BuildBuy Object"), ("canvas", "BuildBuy Object"), ("art", "BuildBuy Object"),
    ("smart tv", "BuildBuy Object"), ("smartview", "BuildBuy Object"),

    # Misc content
    ("animation", "Animation"), ("anim_", "Animation"), ("swimming", "Animation"), ("betterreactions", "Gameplay Tuning"),
    ("pose", "Pose"), ("posepack", "Pose"),
    ("preset", "Preset"), ("slider", "Slider"),
    ("world", "World"), ("override", "Override"),
    ("animation pack", "Animation"),
    ("pose pack", "Pose"), ("cas pose", "Pose"),
    ("ask", "Gameplay Tuning"),
    ("job", "Gameplay Tuning"), ("jobs", "Gameplay Tuning"),

    # Adult-specific (extra coverage)
    ("wickedperversions", "Adult Gameplay"), ("perversions", "Adult Gameplay"), 
    ("wickedwhims animation", "Adult Animation"),
    ("ww animations", "Adult Animation"),
    ("ww anarcis", "Adult Animation"), ("anarcis", "Adult Animation"),
    ("pornstar", "Adult CAS"),
    ("condom wrapper", "Adult CAS"), ("condomwrapper", "Adult CAS"), ("condom", "Adult BuildBuy"), ("condoms", "Adult BuildBuy"),
    ("latex", "Adult CAS"), ("sheath", "Adult CAS"), ("rubber", "Adult CAS"),
    ("butt plug", "Adult BuildBuy"),
    ("layer set", "Adult CAS"),
    ("cum", "Adult Gameplay"), ("penis", "Adult CAS"), ("cock", "Adult Gameplay"),
    ("vagina", "Adult CAS")
]

# Adult keyword signals
ADULT_STRONG = {
    "wickedwhims", "turbodriver", "basemental", "nisak", "nisa", "wild_guy", "wild guy",
    "wickedperversions", "perversions",
}
ADULT_WEAK = {
    "nsfw", "porn", "sex", "nude", "naked", "strip", "lapdance", "prostitution",
    "genital", "penis", "vagina", "condom", "dildo", "vibrator", "plug", "cum",
    "lingerie", "erotic", "aphrodisiac"
}

# Hints to split adult into sub-categories
ADULT_CAS_HINTS    = {"hair","top","dress","skirt","makeup","lipstick","blush","eyeliner","skin","overlay",
                      "bra","panties","stocking","stockings","tights","heels","lingerie","nipple","areola","pubic"}
ADULT_OBJECT_HINTS = {"object","toy","furniture","bed","pole","stripper","condom","vibrator","dildo","plug"}

def _adult_level(name: str) -> Tuple[str, List[str]]:
    low = name.lower()
    strong = sorted({k for k in ADULT_STRONG if k in low})
    if strong:
        return "strong", strong
    weak = sorted({k for k in ADULT_WEAK if k in low})
    if weak:
        return "weak", weak
    return "", []

CATEGORY_ORDER = [
    "Script Mod",
    "Gameplay Tuning",
    "CAS Hair", "CAS Clothing", "CAS Makeup", "CAS Skin", "CAS Eyes", "CAS Accessories",
    "BuildBuy Object", "BuildBuy Recolour",
    "Animation", "Preset", "Pose", "Slider",
    "World", "Override",
    "Utility Tool", "Archive", "Other", "Unknown",
    "Adult Script", "Adult Gameplay", "Adult Animation", "Adult Pose",
    "Adult CAS", "Adult BuildBuy", "Adult Override", "Adult Other",
]

DEFAULT_FOLDER_MAP = {
    "Adult Script": "Adult - Scripts",
    "Adult Gameplay": "Adult - Gameplay",
    "Adult Animation": "Adult - Animations",
    "Adult Pose": "Adult - Poses",
    "Adult CAS": "Adult - CAS",
    "Adult BuildBuy": "Adult - Objects",
    "Adult Override": "Adult - Overrides",
    "Adult Other": "Adult - Other",
    "Script Mod": "Script Mods",
    "Gameplay Tuning": "Gameplay Mods",
    "CAS Hair": "CAS Hair", "CAS Clothing": "CAS Clothing", "CAS Makeup": "CAS Makeup",
    "CAS Skin": "CAS Skin", "CAS Eyes": "CAS Eyes", "CAS Accessories": "CAS Accessories",
    "BuildBuy Object": "BuildBuy Objects", "BuildBuy Recolour": "BuildBuy Recolours",
    "Animation": "Animations", "Preset": "Presets", "Pose": "Poses", "Slider": "Sliders",
    "World": "World", "Override": "Overrides", "Utility Tool": "Utilities",
    "Archive": "Archives", "Other": "Other", "Unknown": "Unsorted",
}

# Resource type IDs used inside .package (DBPF)
TYPE_IDS = {
    0x034AEECB: "CASP",
    0x319E4F1D: "COBJ/OBJD",
    0x02D5DF13: "JAZZ",
    0x220557DA: "STBL",
    0x015A1849: "GEOM",
    0x01661233: "MODL",
    0x01D10F34: "MLOD",
    0x0354796A: "TONE",
    0x067CAA11: "BGEO",
    0x00B2D882: "IMG",
}

ARCHIVE_EXTS = {".zip", ".rar", ".7z"}
PACKAGE_EXTS = {".package"}
SCRIPT_EXTS = {".ts4script", ".t4script", ".zip"}  # zip counted only if it truly contains Python

LOG_NAME = ".sims4_modsorter_moves.json"

# ---------------------------
# Themes
# ---------------------------
THEMES = {
    "Dark Mode": {"bg": "#111316", "fg": "#E6E6E6", "alt": "#161A1E", "accent": "#4C8BF5", "sel": "#2A2F3A"},
    "Slightly Dark Mode": {"bg": "#14161a", "fg": "#EAEAEA", "alt": "#1b1e24", "accent": "#6AA2FF", "sel": "#2f3642"},
    "Light Mode": {"bg": "#FAFAFA", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#316DCA", "sel": "#E8F0FE"},
    "High Contrast Mode": {"bg": "#000000", "fg": "#FFFFFF", "alt": "#000000", "accent": "#FFD400", "sel": "#333333"},
    "Pink Holiday": {"bg": "#1a1216", "fg": "#FFE7F3", "alt": "#23171e", "accent": "#FF5BA6", "sel": "#3a1f2c"},
    "Dracula": {"bg": "#282a36", "fg": "#f8f8f2", "alt": "#1e2029", "accent": "#bd93f9", "sel": "#44475a"},
    "Nord": {"bg": "#2E3440", "fg": "#ECEFF4", "alt": "#3B4252", "accent": "#88C0D0", "sel": "#434C5E"},
    "Ocean Dark": {"bg": "#0b1220", "fg": "#e6edf3", "alt": "#0f172a", "accent": "#38bdf8", "sel": "#18253f"}}

PINK_THEMES = {
    "Sakura Light":       {"bg": "#FFF7FB", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#EC4899", "sel": "#FCE7F3"},
    "Sakura Dark":        {"bg": "#0f0f12", "fg": "#ECEAF0", "alt": "#15151a", "accent": "#FF2D7D", "sel": "#2A1320"},
    "Rose Quartz Light":  {"bg": "#FAF4F6", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#F43F5E", "sel": "#FFE4EA"},
    "Rose Quartz Dark":   {"bg": "#141319", "fg": "#EAE6EC", "alt": "#1B1A22", "accent": "#E11D48", "sel": "#2A1A22"},
    "Blush Minimal Light":{"bg": "#FCF2F5", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#FB7185", "sel": "#FFE3E8"},
    "Blush Minimal Dark": {"bg": "#131216", "fg": "#EDEAF0", "alt": "#19181E", "accent": "#F43F5E", "sel": "#2A1A1E"},
    "Magenta Noir":       {"bg": "#0B0B0F", "fg": "#EEEFF2", "alt": "#121217", "accent": "#D946EF", "sel": "#241428"},
    "Vaporwave Pink":     {"bg": "#0D1017", "fg": "#E6F0FF", "alt": "#131722", "accent": "#FF4D9E", "sel": "#241C2E"},
    "Rose Gold Dark":     {"bg": "#191A1C", "fg": "#F2EFE9", "alt": "#1F2023", "accent": "#D28B8E", "sel": "#2A2325"},
    "Mauve Mist Dark":    {"bg": "#121016", "fg": "#ECE9F2", "alt": "#181720", "accent": "#C084FC", "sel": "#241B2E"},
    "Cotton Candy Light": {"bg": "#FFF5FA", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#FF80C7", "sel": "#FFE3F2"},
    "Neon Pink Dark":     {"bg": "#0B0D10", "fg": "#EDEDED", "alt": "#11141A", "accent": "#FF2E97", "sel": "#1F0E1A"},
}
# merge into your existing THEMES dict
THEMES.update(PINK_THEMES)

COLUMNS = ("inc", "rel", "name", "ext", "type", "size", "target", "notes", "conf")
HEADERS = {
    "inc": "✔",
    "rel": "Folder",
    "name": "File",
    "ext": "Ext",
    "type": "Type",
    "size": "MB",
    "target": "Target Folder",
    "notes": "Notes",
    "conf": "Conf",
}
# ---------------------------
# Utilities
# ---------------------------
def _u32(b, off):
    return int.from_bytes(b[off:off+4], 'little', signed=False)

def dbpf_scan_types(path: str) -> Dict[int, int]:
    out: Dict[int, int] = {}
    with open(path, 'rb') as f:
        head = f.read(96)
        if len(head) < 96 or head[:4] != b'DBPF':
            return out
        try:
            count      = _u32(head, 0x20)
            index_pos  = _u32(head, 0x40)
            if not count or not index_pos:
                return out
        except Exception:
            return out

        f.seek(index_pos)
        try:
            flags = int.from_bytes(f.read(4), 'little')
            header_vals = []
            flagged_slots = [i for i in range(8) if (flags >> i) & 1]
            for _ in flagged_slots:
                header_vals.append(int.from_bytes(f.read(4), 'little'))
            per_entry_dwords = 8 - len(flagged_slots)

            for _ in range(count):
                entry_vals = [int.from_bytes(f.read(4), 'little') for __ in range(per_entry_dwords)]
                vals = {}
                hi = 0
                mi = 0
                for b in range(8):
                    if b in flagged_slots:
                        vals[b] = header_vals[hi]; hi += 1
                    else:
                        vals[b] = entry_vals[mi]; mi += 1
                rtype = vals.get(0, 0)
                out[rtype] = out.get(rtype, 0) + 1
        except Exception:
            return {}
    return out

def get_default_mods_path() -> str:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Documents", "Electronic Arts", "The Sims 4", "Mods"),
        os.path.join(home, "OneDrive", "Documents", "Electronic Arts", "The Sims 4", "Mods"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return candidates[0]

def human_mb(nbytes: int) -> float:
    return round(nbytes / (1024 * 1024), 2)

def pretty_display_name(filename: str) -> str:
    base = re.sub(r'\.[^.]+$', '', filename)
    base = re.sub(r'[_\-]+', ' ', base)
    base = re.sub(r'\s+', ' ', base).strip()
    parts = []
    for w in base.split(' '):
        if len(w) <= 4 and w.isupper():
            parts.append(w)
        else:
            parts.append(w[:1].upper() + w[1:])
    return ' '.join(parts)

def normalize_key(filename: str) -> str:
    base = re.sub(r'\.[^.]+$', '', filename).lower()
    base = re.sub(r'\[[^\]]+\]', '', base)
    base = re.sub(r'[_\-\s]+', '', base)
    base = re.sub(r'[^a-z0-9]+', '', base)
    return base

def _lcp(a: str, b: str) -> int:
    i = 0; m = min(len(a), len(b))
    while i < m and a[i] == b[i]: i += 1
    return i

def infer_from_peers(items: List[FileItem], folder_map: Dict[str, str]) -> int:
    fam_known: Dict[str, str] = {}
    counts: Dict[str, Dict[str, int]] = {}
    for it in items:
        fam = _family_key(it.name)
        if it.guess_type not in {"Unknown", "Other", "Adult Other"}:
            c = counts.setdefault(fam, {})
            c[it.guess_type] = c.get(it.guess_type, 0) + 1
    for fam, c in counts.items():
        fam_known[fam] = sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

    changed = 0
    for it in items:
        if it.guess_type in {"Unknown", "Other", "Adult Other"}:
            fam = _family_key(it.name)
            if fam in fam_known:
                it.guess_type = fam_known[fam]
                it.target_folder = folder_map.get(it.guess_type, "Unsorted")
                it.notes = (it.notes + ("; " if it.notes else "") + f"paired by family: {fam}").strip()
                changed += 1
    return changed

def _settings_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".sims4_modsorter_settings.json")

def load_settings() -> dict:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(d: dict) -> None:
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass

# ---------------------------
# Classification
# ---------------------------
# --- Detector pipeline (compact + configurable) ---

DEFAULT_DETECTOR_ORDER = ["name", "binary", "ext"]

def _det_by_ext(ext: str, current: tuple[str, float, str]) -> tuple[str, float, str]:
    # very light fallback; your name/binary detectors do the heavy lifting
    if ext == ".ts4script":
        return ("Script Mod", max(current[1], 0.9), "by extension")
    if ext in {".zip", ".rar", ".7z"}:
        return ("Archive", max(current[1], 0.6), "archive")
    return current

DETECTOR_FUNCS = {
    "name":   lambda path, name, ext, cur: guess_type_for_name(name, ext),
    "binary": lambda path, name, ext, cur: guess_type_binary(path, cur),
    "ext":    lambda path, name, ext, cur: _det_by_ext(ext, cur),
}

def classify_file(path: str, name: str, ext: str,
                  order: list[str] | None,
                  enable_binary: bool) -> tuple[str, float, str]:
    current: tuple[str, float, str] = ("Unknown", 0.0, "")
    order = order or DEFAULT_DETECTOR_ORDER
    for step in order:
        if step == "binary" and not enable_binary:
            continue
        fn = DETECTOR_FUNCS.get(step)
        if not fn:
            continue
        res = fn(path, name, ext, current)
        if not isinstance(res, tuple) or len(res) != 3:
            continue
        cat, conf, notes = res
        if conf >= current[1]:                         # prefer higher confidence
            merged = current[2]
            if notes:                                  # keep notes compact
                merged = (merged + "; " if merged else "") + notes
            current = (cat, conf, merged)
    return current

ADULT_TOKENS = {
    "wickedwhims", "turbodriver", "basemental", "nisa", "wild_guy",
    "nsfw", "porn", "sex", "nude", "naked", "strip", "lapdance", "prostitution",
    "genital", "penis", "vagina", "condom", "dildo", "vibrator", "plug", "cum"
}

def is_ts4script_or_zip_script(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext not in SCRIPT_EXTS:
        return False
    try:
        with zipfile.ZipFile(path, 'r') as z:
            for n in z.namelist():
                nl = n.lower()
                if nl.endswith('.py') or nl.endswith('.pyc'):
                    return True
    except Exception:
        return False
    return False

def classify_from_types(types: Dict[int, int], filename: str, adult_hint_strong: bool) -> Tuple[str, float, str, str]:
    if not types:
        return ("Unknown", 0.5, "No DBPF index", "")
    name = filename.lower()
    has = lambda tid: tid in types
    tags = ", ".join(f"{TYPE_IDS.get(t, hex(t))}:{n}" for t, n in types.items())
    notes = "Types: " + tags

    if has(0x034AEECB):  # CASP
        if any(k in name for k in ("glasses","eyeglass","spectacle","sunglass","eyewear","goggle","goggles","ring","necklace","ear","nail","piercing","tail")):
            base = "CAS Accessories"; conf = 0.85
        elif any(k in name for k in ("hair","brow","lash")):
            base = "CAS Hair"; conf = 0.85
        elif any(k in name for k in ("lip","liner","blush","makeup")):
            base = "CAS Makeup"; conf = 0.85
        elif any(k in name for k in ("skin","overlay","tattoo","freckle","scar")):
            base = "CAS Skin"; conf = 0.85
        elif any(k in name for k in ("eye","eyes","iris")):
            base = "CAS Eyes"; conf = 0.85
        else:
            base = "CAS Clothing"; conf = 0.80
    elif has(0x319E4F1D) or has(0x015A1849) or has(0x01661233) or has(0x01D10F34):
        base, conf = "BuildBuy Object", 0.85
    elif has(0x0354796A):
        base, conf = "CAS Skin", 0.85
    elif has(0x02D5DF13):
        base, conf = "Animation", 0.85
    elif has(0x220557DA):
        base, conf = "Gameplay Tuning", 0.75
    else:
        base, conf = "Other", 0.60

    if base == "Other":
        if any(k in name for k in ("overlay","wrapper","tattoo","bodypaint","skin","condom")):
            base, conf = "CAS Skin", 0.75
    cat = adultize_category(base) if adult_hint_strong else base
    return (cat, conf, notes, tags)

def guess_type_for_name(name: str, ext: str) -> Tuple[str, float, str]:
    # Tokenize rather than raw substring so CamelCase and glued words match
    tokens = [t for t in WORD_SPLIT.split(name.lower()) if t]
    toks = set(tokens)

    # adult hints
    adult_strong = {"wickedwhims","turbodriver","basemental","nisa","wild","wild_guy"}
    adult_weak   = {"nsfw","porn","sex","nude","naked","strip","lapdance","prostitution",
                    "genital","penis","vagina","condom","vibrator","dildo","plug"}
    is_adult = (adult_strong & toks) or (adult_weak & toks)

    if ext == ".ts4script":
        return ("Adult Script", 1.0, "Adult script") if is_adult else ("Script Mod", 1.0, "Script by extension")
    if ext in {".zip",".rar",".7z"}:
        return ("Adult Other", 0.95, f"Adult archive {ext}") if is_adult else ("Archive", 0.95, f"Archive {ext}")

    if is_adult:
        if {"anim","animation","animations"} & toks: return ("Adult Animation", 0.9, "Adult+animation")
        if "pose" in toks:                           return ("Adult Pose", 0.85, "Adult+pose")
        if {"hair","dress","skirt","makeup","lipstick","blush","eyeliner","overlay","skin",
            "lingerie","heels","stockings","bra","panties","nipple","areola","pubic"} & toks:
            return ("Adult CAS", 0.85, "Adult+CAS")
        if {"object","toy","furniture","bed","pole","stripper","condom","vibrator","dildo","plug"} & toks:
            return ("Adult BuildBuy", 0.8, "Adult+object")
        if "override" in toks:                       return ("Adult Override", 0.8, "Adult+override")
        return ("Adult Gameplay", 0.75, "Adult keyword")

    # non-adult keywords (your current map)
    hits = []
    for key, cat in KEYWORD_MAP:
        if key in " ".join(tokens):
            hits.append(cat)
    if hits:
        unique = sorted(set(hits), key=lambda c: CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 999)
        cat = unique[0]
        conf = 0.85 if len(set(hits)) > 1 else 0.7
        return (cat, conf, f"Keyword(s): {', '.join(sorted(set(hits)))}")

    if ext == ".package":
        return ("Unknown", 0.4, "Package with no keyword match")
    return ("Other", 0.2, f"Unhandled ext {ext}")

def map_type_to_folder(cat: str, folder_map: Dict[str, str]) -> str:
    return folder_map.get(cat, folder_map.get("Unknown", "Unsorted"))

BINARY_HINTS = {
    b"DBPF": None,            # sanity
    b"CASP": "CAS Clothing",
    b"OBJD": "BuildBuy Object",
    b"STBL": "Gameplay Tuning",
    b"JAZZ": "Animation",
}

def _u32(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off+4], "little", signed=False)

# minimal DBPF resource counter; returns {type_id: count}
def _dbpf_types(path: str) -> Dict[int, int]:
    out: Dict[int, int] = {}
    try:
        with open(path, "rb") as f:
            head = f.read(96)
            if len(head) < 96 or head[:4] != b"DBPF":
                return out
            count     = _u32(head, 0x20)
            index_pos = _u32(head, 0x40)
            if not count or not index_pos:
                return out
            f.seek(index_pos)
            flags = _u32(f.read(4), 0)
            header_vals = []
            flagged = [i for i in range(8) if (flags >> i) & 1]
            for _ in flagged:
                header_vals.append(_u32(f.read(4), 0))
            per_entry_dwords = 8 - len(flagged)
            for _ in range(count):
                entry = [_u32(f.read(4), 0) for __ in range(per_entry_dwords)]
                vals = {}
                hi = mi = 0
                for b in range(8):
                    if b in flagged:
                        vals[b] = header_vals[hi]; hi += 1
                    else:
                        vals[b] = entry[mi]; mi += 1
                rtype = vals.get(0, 0)
                out[rtype] = out.get(rtype, 0) + 1
    except Exception:
        return {}
    return out

TYPE_IDS = {
    0x034AEECB: "CASP",
    0x319E4F1D: "OBJD/COBJ",
    0x02D5DF13: "JAZZ",
    0x220557DA: "STBL",
    0x0354796A: "TONE",
    0x015A1849: "GEOM",
    0x01661233: "MODL",
    0x01D10F34: "MLOD",
}

def guess_type_binary(path: str, current: Tuple[str, float, str]) -> Tuple[str, float, str]:
    cat, conf, notes = current
    if not path.lower().endswith(".package"):
        return current

    types = _dbpf_types(path)
    if not types:
        return current

    name = os.path.basename(path).lower()
    tag_str = ", ".join(f"{TYPE_IDS.get(t, hex(t))}:{n}" for t, n in types.items())
    notes = (notes + ("; " if notes else "") + f"Types: {tag_str}").strip()

    # DBPF-guided category
    if 0x034AEECB in types:  # CASP
        if any(k in name for k in ("glasses","spectacle","sunglass","eyewear","goggle","ring","necklace","ear","nail","piercing","tail","horn","wing","headpiece")):
            return ("CAS Accessories", max(conf, 0.9), notes)
        if any(k in name for k in ("hair","brow","lash")):
            return ("CAS Hair", max(conf, 0.9), notes)
        if any(k in name for k in ("lip","liner","blush","makeup")):
            return ("CAS Makeup", max(conf, 0.9), notes)
        if any(k in name for k in ("skin","overlay","tattoo","freckle","scar")):
            return ("CAS Skin", max(conf, 0.9), notes)
        if any(k in name for k in ("eye","eyes","iris")):
            return ("CAS Eyes", max(conf, 0.9), notes)
        return ("CAS Clothing", max(conf, 0.85), notes)

    if 0x02D5DF13 in types:  # JAZZ
        return ("Animation", max(conf, 0.85), notes)

    if 0x319E4F1D in types or 0x015A1849 in types or 0x01661233 in types or 0x01D10F34 in types:
        # Build/Buy geometry/object presence
        return ("BuildBuy Object", max(conf, 0.8), notes)

    if set(types.keys()) == {0x220557DA}:
        # STBL-only often “tuning/data only”
        return ("Gameplay Tuning", max(conf, 0.8), notes)

    return (cat, conf, notes)

# ---------------------------
# Scan, bundle, move, undo
# ---------------------------
def get_downloads_dir() -> str:
    """Best-effort Windows Downloads folder (handles OneDrive variants)."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "OneDrive", "Downloads"),
        os.path.join(home, "OneDrive - " + os.environ.get("USERNAME", ""), "Downloads"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    # Fallback: make ~/Downloads
    dl = os.path.join(home, "Downloads")
    try:
        os.makedirs(dl, exist_ok=True)
    except Exception:
        pass
    return dl

def _stem(s: str) -> str:
    # tolerant stem: lower, no extension, collapse separators and common version tokens
    base = os.path.splitext(os.path.basename(s))[0].lower()
    for ch in ("_", "-", ".", " "):
        base = base.replace(ch, " ")
    # strip trivial version/pack tokens
    tokens = [t for t in base.split() if t not in {"v", "ver", "version", "merged", "pack"}]
    return " ".join(tokens)

def pair_scripts_and_packages(items: List[FileItem]) -> None:
    """
    If a .package is Unknown/Other but shares a stem with a Script Mod (.ts4script),
    promote it to 'Script Mod' so script + package don't get separated.
    """
    by_stem: Dict[str, List[FileItem]] = {}
    for it in items:
        by_stem.setdefault(_stem(it.name), []).append(it)

    for group in by_stem.values():
        has_script = any((it.ext in {".ts4script", ".t4script"} or it.guess_type == "Script Mod") for it in group)
        if not has_script:
            continue
        for it in group:
            if it.ext == ".package" and it.guess_type in {"Unknown", "Other"}:
                it.guess_type = "Script Mod"
                it.target_folder = DEFAULT_FOLDER_MAP["Script Mod"]
                it.confidence = max(it.confidence, 0.8)
                it.notes = (it.notes + "; paired with script").strip("; ")

def scan_folder(
    path: str,
    use_binary_scan: bool,
    folder_map: Dict[str, str],
    recurse: bool = True,
    ignore_exts: Optional[set] = None,
    ignore_name_contains: Optional[List[str]] = None,
    progress_cb=None,
    detector_order: Optional[List[str]] = None,
) -> List[FileItem]:
    out: List[FileItem] = []
    if not os.path.isdir(path):
        return out

    ignore_exts = {e.strip().lower() if e.strip().startswith('.') else f".{e.strip().lower()}"
                   for e in (ignore_exts or set()) if e.strip()}
    ignore_name_contains = [t.strip().lower() for t in (ignore_name_contains or []) if t.strip()]

    # enumerate candidates
    candidates: List[str] = []
    if recurse:
        for root, dirs, files in os.walk(path):
            for fname in files:
                candidates.append(os.path.join(root, fname))
    else:
        for entry in os.scandir(path):
            if entry.is_file():
                candidates.append(entry.path)

    total = len(candidates)
    for idx, fpath in enumerate(candidates, start=1):
        try:
            fname = os.path.basename(fpath)
            low   = fname.lower()
            ext_raw, disabled = detect_real_ext(fname)

            # ignore filters
            if ext_raw in ignore_exts:
                if progress_cb: progress_cb(idx, total, fpath, "ignored ext")
                continue
            if any(tok in low for tok in ignore_name_contains):
                if progress_cb: progress_cb(idx, total, fpath, "ignored name")
                continue

            size_mb = human_mb(os.path.getsize(fpath))
            cat, conf, notes = guess_type_for_name(fname, ext_raw)
            if use_binary_scan:
                cat, conf, notes = guess_type_binary(fpath, (cat, conf, notes))
            # NEW: single pipeline
            cat, conf, notes = classify_file(
                fpath, fname, ext_raw, order=detector_order, enable_binary=use_binary_scan
            )
            if disabled:
                notes = (notes + "; disabled (.off)").strip("; ")
            target = map_type_to_folder(cat, folder_map)

            target = map_type_to_folder(cat, folder_map)
            relp = os.path.relpath(fpath, path)
            out.append(FileItem(
                path=fpath, name=fname, ext=ext_raw, size_mb=size_mb,
                relpath=relp, guess_type=cat, confidence=conf, notes=notes,
                include=(not disabled), target_folder=target,
            ))
            if progress_cb: progress_cb(idx, total, fpath, "scanned")
        except Exception as e:
            relp = os.path.relpath(fpath, path)
            out.append(FileItem(
                path=fpath, name=os.path.basename(fpath),
                ext=os.path.splitext(fpath)[1].lower(), size_mb=0.0,
                relpath=relp, guess_type="Unknown", confidence=0.0,
                notes=f"scan error: {e}", include=False,
                target_folder=map_type_to_folder("Unknown", folder_map),
            ))
            if progress_cb: progress_cb(idx, total, fpath, "error")

    out.sort(key=lambda fi: (
        CATEGORY_ORDER.index(fi.guess_type) if fi.guess_type in CATEGORY_ORDER else 999,
        os.path.dirname(fi.relpath).lower(), fi.name.lower()))
    return out

def ensure_folder(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)

def perform_moves(items: List[FileItem], mods_root: str):
    moved = 0; skipped = 0; collisions = []; moves_log = []
    for it in items:
        if not it.include:
            skipped += 1; continue
        dst_dir = os.path.join(mods_root, it.target_folder)
        ensure_folder(dst_dir)
        dst_path = os.path.join(dst_dir, it.name)
        if os.path.abspath(dst_path) == os.path.abspath(it.path):
            skipped += 1; continue
        if os.path.exists(dst_path):
            collisions.append((it.path, dst_path, "name collision")); skipped += 1; continue
        try:
            shutil.move(it.path, dst_path)
            moved += 1
            moves_log.append({"from": it.path, "to": dst_path})
        except Exception as e:
            collisions.append((it.path, dst_path, f"move error: {e}")); skipped += 1
    return moved, skipped, collisions, moves_log

def save_moves_log(mods_root: str, moves):
    if not moves: return
    log_path = os.path.join(mods_root, LOG_NAME)
    try:
        existing = json.load(open(log_path, "r", encoding="utf-8")) if os.path.exists(log_path) else []
    except Exception:
        existing = []
    existing.append({"ts": time.time(), "moves": moves})
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass

def undo_last_moves(mods_root: str):
    log_path = os.path.join(mods_root, LOG_NAME)
    if not os.path.exists(log_path): return 0, 0, ["No log found"]
    try:
        history = json.load(open(log_path, "r", encoding="utf-8"))
    except Exception:
        return 0, 0, ["Log unreadable"]
    if not history: return 0, 0, ["No moves recorded"]
    last = history.pop()
    moves = last.get("moves", [])
    undone = failed = 0; errs = []
    for m in reversed(moves):
        src = m.get("to"); dst = m.get("from")
        try:
            if os.path.exists(src):
                ensure_folder(os.path.dirname(dst))
                if os.path.exists(dst):
                    errs.append(f"Collision on undo for {os.path.basename(dst)}"); failed += 1
                else:
                    shutil.move(src, dst); undone += 1
            else:
                errs.append(f"Missing {os.path.basename(src)} to undo"); failed += 1
        except Exception as e:
            errs.append(f"Undo error for {os.path.basename(src)}: {e}"); failed += 1
    try:
        with open(log_path, "w", encoding="utf-8") as f: json.dump(history, f, indent=2)
    except Exception:
        pass
    return undone, failed, errs

def bundle_scripts_and_packages(items: List[FileItem], folder_map: Dict[str, str]):
    scripts: Dict[str, FileItem] = {}
    for it in items:
        if it.ext in SCRIPT_EXTS and it.guess_type in {"Script Mod", "Adult Script"}:
            scripts[normalize_key(it.name)] = it

    linked = 0
    for it in items:
        if it.ext == ".package":
            key = normalize_key(it.name)
            if key in scripts:
                s = scripts[key]
                it.bundle = key
                it.target_folder = s.target_folder
                low = it.name.lower()
                if ("addon" in low or "add-on" in low or "module" in low or it.guess_type in {"Unknown","Other"}):
                    it.guess_type = s.guess_type
                    it.confidence = max(it.confidence, 0.8)
                it.notes = (it.notes + "; paired with script").strip("; ")
                linked += 1
    return {"linked": linked, "scripts": len(scripts)}

# ---------------------------
# UI
# ---------------------------
class Sims4ModSorterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # window sizing
        self.title("Sims4 Mod Sorter")
        self.geometry("1680x1000")
        self.minsize(1100, 740)
        self.resizable(True, True)

        # settings / state (add this if missing)
        self.use_binary_scan = tk.BooleanVar(value=True)

        self.folder_map: Dict[str, str] = DEFAULT_FOLDER_MAP.copy()
        self.recurse_var = tk.BooleanVar(value=True)
        self.ignore_exts_var = tk.StringVar(value=".log,.cfg,.txt,.html")
        self.ignore_names_var = tk.StringVar(value="thumbcache,desktop.ini,resource.cfg")
        self.theme_name = tk.StringVar(value="Dark Mode")
        self.mods_root = tk.StringVar(value=get_default_mods_path())
        self.items: List[FileItem] = []

        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="No plan yet")

        self._load_live_settings()

        # Settings / state
        cfg = load_settings()

        self.folder_map: Dict[str, str] = DEFAULT_FOLDER_MAP.copy()
        self.use_binary_scan = tk.BooleanVar(value=cfg.get("use_binary_scan", True))
        self.recurse_var    = tk.BooleanVar(value=cfg.get("recurse", True))
        self.ignore_exts_var  = tk.StringVar(value=cfg.get("ignore_exts", ".log,.cfg,.txt,.html"))
        self.ignore_names_var = tk.StringVar(value=cfg.get("ignore_names", "thumbcache,desktop.ini,resource.cfg"))
        self.theme_name     = tk.StringVar(value=cfg.get("theme", "Dark Mode"))
        self.mods_root      = tk.StringVar(value=cfg.get("mods_root", get_default_mods_path()))
        self.items: List[FileItem] = []

        self._build_style()
        self._build_ui()
        self._build_settings_overlay()     # build hidden in-window overlay
        self.bind("<Escape>", lambda e: self.toggle_settings(False))
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._collision_plan = []    # holds dicts from plan_collisions
        self._build_collision_overlay()

        self.bind("<Configure>", self._on_resize)

    def _build_style(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except Exception: pass
        theme = THEMES.get(self.theme_name.get(), THEMES["Dark Mode"])
        bg, fg, alt, accent, sel = theme["bg"], theme["fg"], theme["alt"], theme["accent"], theme["sel"]
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TButton", background=alt, foreground=fg, padding=6)
        style.map("TButton", background=[("active", sel)])
        style.configure("Treeview", background=alt, fieldbackground=alt, foreground=fg, rowheight=28, bordercolor=bg, borderwidth=0)
        style.map("Treeview", background=[("selected", sel)])
        style.configure("Treeview.Heading", background=bg, foreground=fg)
        style.configure("Horizontal.TProgressbar", background=accent, troughcolor=alt)
        self.configure(bg=bg)
        self._theme_cache = dict(bg=bg, fg=fg, alt=alt, accent=accent, sel=sel)

    def _build_ui(self):
        # ── Top bar ────────────────────────────────────────────────────────────────
        top = ttk.Frame(self); top.pack(fill="x", padx=12, pady=10)

        ttk.Label(top, text="Mods folder:").pack(side="left")
        self.entry_path = ttk.Entry(top, textvariable=self.mods_root, width=80)
        self.entry_path.pack(side="left", padx=8)

        ttk.Button(top, text="Browse", command=self.on_browse).pack(side="left", padx=4)
        ttk.Button(top, text="Scan",   command=self.on_scan).pack(side="left", padx=4)
        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=12)

        ttk.Button(top, text="⚙", width=3, command=self.toggle_settings).pack(side="right")
        ttk.Button(top, text="Undo Last", command=self.on_undo).pack(side="right", padx=6)

        # ── Middle area ───────────────────────────────────────────────────────────
        mid = ttk.Frame(self); mid.pack(fill="both", expand=True, padx=12, pady=(6, 8))

        header = ttk.Frame(mid); header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, textvariable=self.summary_var).pack(side="left")

        # Left: Tree + vscroll
        left = ttk.Frame(mid); left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=COLUMNS, show="headings", selectmode="extended")

        for col in COLUMNS:
            self.tree.heading(col, text=HEADERS.get(col, col))

        # sensible defaults (overridden by saved widths, then frozen once user resizes)
        defaults = {
            "inc": 28, "rel": 160, "name": 420, "ext": 80, "type": 150,
            "size": 70, "target": 180, "notes": 520, "conf": 60,
        }
        for col, w in defaults.items():
            self.tree.column(col, width=w,
                             anchor=("w" if col in ("rel","name","target","notes") else "center"),
                             stretch=(col in ("rel","name","target","notes")))

        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="left", fill="y")

        # restore saved column widths (if any)
        cfg = load_settings()
        saved = cfg.get("col_widths") or {}
        self._respect_user_widths = bool(saved)
        for col, w in (saved.items() if isinstance(saved, dict) else []):
            if col in COLUMNS:
                try: self.tree.column(col, width=int(w))
                except Exception: pass

        # Right: editor panel — all original controls present
        right = ttk.Frame(mid); right.pack(side="left", fill="y", padx=(10, 0))

        ttk.Label(right, text="Selection").pack(anchor="w")
        self.sel_label = ttk.Label(right, text="None selected")
        self.sel_label.pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Type").pack(anchor="w")
        self.type_cb = ttk.Combobox(right, values=CATEGORY_ORDER, state="readonly")
        self.type_cb.pack(fill="x", pady=(0, 8))

        ttk.Label(right, text="Target Folder").pack(anchor="w")
        self.target_entry = ttk.Entry(right); self.target_entry.pack(fill="x", pady=(0, 8))

        ttk.Button(right, text="Apply to Selected", command=self.on_apply_selected).pack(fill="x", pady=4)
        ttk.Button(right, text="Toggle Include",   command=self.on_toggle_include).pack(fill="x", pady=4)

        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Label(right, text="Batch assign by keyword").pack(anchor="w")
        self.batch_keyword = ttk.Entry(right); self.batch_keyword.pack(fill="x", pady=(0, 6))
        ttk.Button(right, text="Assign Type to Matches", command=self.on_batch_assign).pack(fill="x")

        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Button(right, text="Recalculate Targets", command=self.on_recalc_targets).pack(fill="x", pady=4)
        ttk.Button(right, text="Select All",
                   command=lambda: self.tree.selection_set(self.tree.get_children())
                   ).pack(fill="x", pady=2)
        ttk.Button(right, text="Select None",
                   command=lambda: self.tree.selection_remove(self.tree.get_children())
                   ).pack(fill="x", pady=2)

        # ── Bottom bar ────────────────────────────────────────────────────────────
        bottom = ttk.Frame(self); bottom.pack(fill="x", padx=12, pady=8)
        self.progress = ttk.Progressbar(bottom, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True)
        ttk.Button(bottom, text="Export Plan",     command=self.on_export_plan).pack(side="right", padx=6)
        ttk.Button(bottom, text="Complete Sorting", command=self.on_complete).pack(side="right", padx=6)

        # Log area
        logf = ttk.Frame(self); logf.pack(fill="both", padx=12, pady=(0, 10))
        self.log_text = tk.Text(logf, height=6, wrap="word", state="disabled", relief="flat",
                                bg=self._theme_cache["alt"], fg=self._theme_cache["fg"])
        self.log_text.pack(fill="both", expand=False)

        # events
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.bind("<Configure>", self._on_resize, add="+")  # auto-size only until the user resizes

    # detect header drag → freeze widths and persist immediately
    def _on_header_release(ev):
        if self.tree.identify_region(ev.x, ev.y) in ("separator", "heading"):
            self._respect_user_widths = True
            cw = {c: int(self.tree.column(c)["width"]) for c in COLUMNS}
            s = load_settings(); s["col_widths"] = cw; save_settings(s)
    self.tree.bind("<ButtonRelease-1>", _on_header_release, add="+")

    # In-window settings overlay
    def _build_settings_overlay(self):
        """Create a full-size in-window overlay with a centered card for settings."""
        # full-window translucent-looking overlay (solid color in Tk)
        self._overlay = tk.Frame(self, bg=self._theme_cache["sel"])
        self._overlay.place_forget()            # hidden initially
        self._overlay.bind("<Button-1>", lambda e: self.toggle_settings(False))  # click outside to close

        # the centered card that holds controls
        self._settings_card = tk.Frame(
            self._overlay, bg=self._theme_cache["alt"], bd=1, relief="ridge"
        )
        # simple centering with place
        self._settings_card.place(relx=0.5, rely=0.5, anchor="center")

        # Title
        title = ttk.Label(self._settings_card, text="Settings", font=("Segoe UI", 11, "bold"))
        title.pack(anchor="w", padx=16, pady=(12, 6))

        # Row: Theme
        row1 = ttk.Frame(self._settings_card)
        row1.pack(fill="x", padx=16, pady=6)
        ttk.Label(row1, text="Theme").pack(side="left")
        self.theme_cb = ttk.Combobox(row1, values=list(THEMES.keys()),
                                     textvariable=self.theme_name, state="readonly", width=24)
        self.theme_cb.pack(side="left", padx=8)
        ttk.Button(row1, text="Apply", command=self.on_apply_theme).pack(side="left")

        # Row: Scan options
        row2 = ttk.Frame(self._settings_card)
        row2.pack(fill="x", padx=16, pady=6)
        self.chk_bin = ttk.Checkbutton(row2, text="Binary hints", variable=self.use_binary_scan)
        self.chk_bin.pack(side="left", padx=4)
        self.chk_recurse = ttk.Checkbutton(row2, text="Scan subfolders", variable=self.recurse_var)
        self.chk_recurse.pack(side="left", padx=12)

        # Row: Detection order (in-window, no pop-ups)
        row_det = ttk.Frame(self._settings_card)
        row_det.pack(fill="x", padx=16, pady=6)

        ttk.Label(row_det, text="Detection order").pack(side="left")

        self.lb_det = tk.Listbox(row_det, height=4, exportselection=False, width=18)
        for k in self.detector_order:
            self.lb_det.insert("end", k)
        self.lb_det.pack(side="left", padx=8)

        btns_det = ttk.Frame(row_det); btns_det.pack(side="left", padx=6)
        ttk.Button(btns_det, text="Up", width=6,
                   command=lambda: self._reorder_detector(-1)).pack(fill="x", pady=2)
        ttk.Button(btns_det, text="Down", width=6,
                   command=lambda: self._reorder_detector(1)).pack(fill="x", pady=2)
        ttk.Button(btns_det, text="Reset", width=6,
                   command=lambda: self._reset_detector_order()).pack(fill="x", pady=2)

        # Row: Ignores
        row3 = ttk.Frame(self._settings_card)
        row3.pack(fill="x", padx=16, pady=6)
        ttk.Label(row3, text="Ignore extensions (csv)").pack(side="left")
        ttk.Entry(row3, textvariable=self.ignore_exts_var, width=30).pack(side="left", padx=6)
        ttk.Label(row3, text="Ignore names contains (csv)").pack(side="left", padx=(12, 0))
        ttk.Entry(row3, textvariable=self.ignore_names_var, width=40).pack(side="left", padx=6)

        # Buttons row
        btns = ttk.Frame(self._settings_card)
        btns.pack(fill="x", padx=16, pady=(10, 14))
        ttk.Button(btns, text="Save & Close",
           command=lambda: (self._read_detector_order(), self.toggle_settings(False))
        ).pack(side="right")

        # internal flag
        self._settings_open = False

        # events
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.bind("<Configure>", self._on_resize, add="+")  # auto-size only until user resizes

        # detect header drag → freeze widths and persist immediately
        def _on_header_release(ev):
            if self.tree.identify_region(ev.x, ev.y) in ("separator", "heading"):
                self._respect_user_widths = True
                col_widths = {c: int(self.tree.column(c)["width"]) for c in COLUMNS}
                s = load_settings()
                s["col_widths"] = col_widths
                save_settings(s)

        self.tree.bind("<ButtonRelease-1>", _on_header_release, add="+")

    def _build_collision_overlay(self):
        self._col_overlay = tk.Frame(self, bg=self._theme_cache["sel"])
        self._col_overlay.place_forget()
        card = tk.Frame(self._col_overlay, bg=self._theme_cache["alt"], bd=1, relief="ridge")
        card.place(relx=0.5, rely=0.5, anchor="center")
        self._col_card = card

        ttk.Label(card, text="Collision Review", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=16, pady=(12,6))

        # Tree of planned deletions
        cols = ("keep","older","older_date","kept","kept_date","target")
        self.col_tree = ttk.Treeview(card, columns=cols, show="headings", height=12, selectmode="extended")
        headers = {
            "keep":"Protect older?", "older":"Older file", "older_date":"Older date",
            "kept":"Newer file", "kept_date":"Newer date", "target":"Destination"
        }
        for c in cols:
            self.col_tree.heading(c, text=headers[c])
            self.col_tree.column(c, width=160 if c not in {"keep"} else 110, anchor="w")
        self.col_tree.pack(fill="both", expand=True, padx=16)

        btns = ttk.Frame(card); btns.pack(fill="x", padx=16, pady=(8,12))
        ttk.Button(btns, text="Protect Selected", command=self._col_protect_selected).pack(side="left")
        ttk.Button(btns, text="Unprotect Selected", command=self._col_unprotect_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Cancel", command=lambda: self._toggle_collision(False)).pack(side="right")
        ttk.Button(btns, text="Confirm & Resolve", command=self._col_apply).pack(side="right", padx=6)

    def _toggle_collision(self, show: bool, plan: list[dict] | None = None):
        if show:
            self._collision_plan = plan or []
            # fill tree
            for r in self.col_tree.get_children(): self.col_tree.delete(r)
            for i, p in enumerate(self._collision_plan):
                if p["older"] == "src":
                    older, newer = p["src"], p["dst"]
                    older_ts, newer_ts = p["src_ts"], p["dst_ts"]
                else:
                    older, newer = p["dst"], p["src"]
                    older_ts, newer_ts = p["dst_ts"], p["src_ts"]
                self.col_tree.insert("", "end", iid=str(i), values=(
                    "No", os.path.basename(older), time.strftime("%Y-%m-%d", time.localtime(older_ts)),
                    os.path.basename(newer), time.strftime("%Y-%m-%d", time.localtime(newer_ts)),
                    os.path.dirname(p["dst"])
                ))
            # show overlay
            self._col_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            w = max(700, min(self.winfo_width()-160, 1000))
            self._col_card.configure(width=w)
            self._col_card.place_configure(relx=0.5, rely=0.5)
        else:
            self._col_overlay.place_forget()

    def _col_protect_selected(self):
        for iid in self.col_tree.selection():
            self._collision_plan[int(iid)]["protect"] = True
            self.col_tree.set(iid, "keep", "Yes")

    def _col_unprotect_selected(self):
        for iid in self.col_tree.selection():
            self._collision_plan[int(iid)]["protect"] = False
            self.col_tree.set(iid, "keep", "No")

    def toggle_settings(self, show: bool | None = None):
        """Show/Hide the in-window overlay. If show is None, toggle."""
        if show is None:
            show = not getattr(self, "_settings_open", False)

        if show:
            # cover the whole client area and raise
            self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            # size the card relative to window width so it’s always readable
            w = max(520, min(self.winfo_width() - 160, 800))
            self._settings_card.configure(width=w)
            self._settings_card.place_configure(relx=0.5, rely=0.5)
            self._overlay.tkraise()
            self._settings_open = True
            self._overlay.focus_set()
        else:
            self._overlay.place_forget()
            self._settings_open = False
            self.focus_set()  # give focus back to main UI

    def show_settings(self):
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay.tkraise()
        self.overlay.focus_set()

    def hide_settings(self):
        self.overlay.place_forget()

    def _selected_keys(self) -> set[tuple[str, str]]:
        """Return {(folder_display, file_name)} for currently selected tree rows."""
        keys = set()
        for iid in self.tree.selection():
            folder = (self.tree.set(iid, "rel") or "").replace("\\", "/")
            fname  = self.tree.set(iid, "name")
            keys.add((folder, fname))
        return keys

    def _on_resize(self, event=None):
        if getattr(self, "_respect_user_widths", False):
            return
        try:
            cur_w = self.tree.winfo_width()
        except Exception:
            return
        if getattr(self, "_last_tree_width", None) == cur_w or cur_w <= 1:
            return
        self._last_tree_width = cur_w

        # fixed cols keep their widths; distribute the rest
        fixed = ("inc", "ext", "type", "size", "conf")
        fixed_total = sum(self.tree.column(c)["width"] for c in fixed if c in COLUMNS)
        avail = max(100, cur_w - fixed_total - 12)

        shares = {"rel": 0.18, "name": 0.42, "target": 0.18, "notes": 0.22}
        for col, r in shares.items():
            if col in COLUMNS:
                self.tree.column(col, width=max(60, int(avail * r)))

    # --- Methods
    def _col_apply(self):
        mods = self.mods_root.get()
        colliding_dir = os.path.join(mods, COLLIDING_DIR_NAME)
        ensure_folder(colliding_dir)
        moved_ops = []

        for p in self._collision_plan:
            src, dst = p["src"], p["dst"]
            older_side = p["older"]
            older_path = src if older_side == "src" else dst
            newer_path = dst if older_side == "src" else src
            # If the destination is the older, we need to free the name for the move
            try:
                if p["protect"]:
                    # Move the older file to Colliding Mods
                    safe_name = os.path.basename(older_path)
                    target = os.path.join(colliding_dir, safe_name)
                    i = 1
                    while os.path.exists(target):
                        base, ext = os.path.splitext(safe_name)
                        target = os.path.join(colliding_dir, f"{base} ({i}){ext}"); i += 1
                    shutil.move(older_path, target)
                    self.log(f"Protected -> moved to Colliding Mods: {os.path.basename(older_path)}")
                    moved_ops.append({"from": older_path, "to": target})
                else:
                    # Delete the older one
                    os.remove(older_path)
                    self.log(f"Deleted older: {os.path.basename(older_path)}")

                # If the older file was the destination, we can now move the source into place
                if older_side == "dst":
                    if os.path.exists(src):
                        ensure_folder(os.path.dirname(dst))
                        shutil.move(src, dst)
                        moved_ops.append({"from": src, "to": dst})
                        self.log(f"Resolved -> moved {os.path.basename(src)} into {os.path.dirname(dst)}")
                else:
                    # older was source; if not protected we already deleted it; nothing else to move
                    pass
            except Exception as e:
                self.log(f"Collision resolve error: {os.path.basename(older_path)} -> {e}")

        save_moves_log(mods, moved_ops)
        self._toggle_collision(False)
        self.on_scan()

    def _reorder_detector(self, delta: int):
        lb = self.lb_det
        sel = lb.curselection()
        if not sel:
            return
        i = sel[0]
        j = i + delta
        if j < 0 or j >= lb.size():
            return
        val = lb.get(i)
        lb.delete(i)
        lb.insert(j, val)
        lb.selection_clear(0, "end")
        lb.selection_set(j)

    def _read_detector_order(self):
        self.detector_order = list(self.lb_det.get(0, "end"))
        self._save_live_settings()

    def _reset_detector_order(self):
        self.lb_det.delete(0, "end")
        for k in DEFAULT_DETECTOR_ORDER:
            self.lb_det.insert("end", k)

    def _export_selected_categories(self) -> set[str]:
        sel_idx = self.cat_list.curselection() if hasattr(self, "cat_list") else ()
        if not sel_idx:
            return set(CATEGORY_ORDER)
        return {self.cat_list.get(i) for i in sel_idx}

    def _filter_for_export(self) -> list:
        cats = self._export_selected_categories()
        sel_keys = self._selected_keys() if hasattr(self, "tree") else set()
        out = []
        for it in self.items:
            folder_disp = (os.path.dirname(it.relpath).replace("\\", "/") if it.relpath else "")
            is_unsorted = (it.target_folder == DEFAULT_FOLDER_MAP.get("Unknown", "Unsorted"))
            is_unknown  = (it.guess_type == "Unknown") or ("no keyword" in (it.notes or "").lower())
            is_error    = (it.notes or "").lower().startswith("scan error")
            is_selected = (folder_disp, it.name) in sel_keys
            if cats and it.guess_type not in cats:           # category filter
                continue
            if getattr(self, "flag_selected", tk.BooleanVar(value=False)).get() and not is_selected:
                continue
            if getattr(self, "flag_unsorted", tk.BooleanVar(value=False)).get() and not is_unsorted:
                continue
            if getattr(self, "flag_unknown", tk.BooleanVar(value=False)).get() and not is_unknown:
                continue
            if getattr(self, "flag_errors", tk.BooleanVar(value=False)).get() and not is_error:
                continue
            out.append(it)
        return out

    def on_export_plan(self) -> None:
        if not self.items:
            messagebox.showinfo("Export Plan", "No plan to export. Run Scan first.")
            return

        # Respect filters (selected rows / unsorted / unknown / errors + category ticks)
        items = self._filter_for_export() if hasattr(self, "_filter_for_export") else self.items
        if not items:
            messagebox.showinfo("Export Plan", "Nothing matched your export filters.")
            return

        rows = []
        for it in items:
            rows.append({
                "folder": os.path.dirname(it.relpath).replace("\\", "/") if getattr(it, "relpath", "") else "",
                "file": it.name,
                "mb": float(getattr(it, "size_mb", 0.0)),
                "type": it.guess_type,
                "target": it.target_folder,
                "conf": round(float(getattr(it, "confidence", 0.0)), 2),
                "notes": it.notes or "",
            })

        ts = time.strftime("%Y%m%d_%H%M%S")
        base = f"Sims4ModSorter_Plan_{ts}"
        dl   = get_downloads_dir()
        json_path = os.path.join(dl, base + ".json")
        csv_path  = os.path.join(dl, base + ".csv")

        # JSON
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Export Plan", f"Failed to write JSON:\n{e}")
            return

        # CSV
        try:
            import csv
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["folder","file","mb","type","target","conf","notes"])
                w.writeheader()
                w.writerows(rows)
        except Exception as e:
            messagebox.showerror("Export Plan", f"Exported JSON, but CSV failed:\n{e}")
            return

        # Console feedback (no pop-up)
        ts2 = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts2}] Exported plan to Downloads:\n  {json_path}\n  {csv_path}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ---- helpers
    def log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def on_apply_theme(self):
        self._build_style()
        # recolor overlay & card to match the theme
        if hasattr(self, "_overlay"):
            self._overlay.configure(bg=self._theme_cache["sel"])
        if hasattr(self, "_settings_card"):
            self._settings_card.configure(bg=self._theme_cache["alt"])
        # keep the console colors in sync
        if hasattr(self, "log_text"):
            self.log_text.configure(bg=self._theme_cache["alt"], fg=self._theme_cache["fg"])
        self._save_live_settings()

    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".sims4_modsorter_config.json")

    def _save_live_settings(self):
        cfg = dict(
            mods_root=self.mods_root.get(),
            theme=self.theme_name.get(),
            use_binary_scan=self.use_binary_scan.get(),
            recurse=self.recurse_var.get(),
            ignore_exts=self.ignore_exts_var.get(),
            ignore_names=self.ignore_names_var.get(),
            detector_order=self.detector_order
        )
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def _load_live_settings(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.mods_root.set(cfg.get("mods_root", self.mods_root.get()))
            self.theme_name.set(cfg.get("theme", self.theme_name.get()))
            self.use_binary_scan.set(cfg.get("use_binary_scan", True))
            self.recurse_var.set(cfg.get("recurse", True))
            self.ignore_exts_var.set(cfg.get("ignore_exts", self.ignore_exts_var.get()))
            self.ignore_names_var.set(cfg.get("ignore_names", self.ignore_names_var.get()))
            self.detector_order = cfg.get("detector_order", DEFAULT_DETECTOR_ORDER.copy())
        except Exception:
            pass

    def load_config(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.mods_root.set(cfg.get("mods_root", self.mods_root.get()))
            self.theme_name.set(cfg.get("theme", self.theme_name.get()))
            self.use_binary_scan.set(cfg.get("use_binary_scan", True))
            self.recurse_var.set(cfg.get("recurse", True))
            self.ignore_exts_var.set(cfg.get("ignore_exts", self.ignore_exts_var.get()))
            self.ignore_names_var.set(cfg.get("ignore_names", self.ignore_names_var.get()))
        except Exception:
            pass

    def save_config(self):
        cfg = dict(
            mods_root=self.mods_root.get(),
            theme=self.theme_name.get(),
            use_binary_scan=self.use_binary_scan.get(),
            recurse=self.recurse_var.get(),
            ignore_exts=self.ignore_exts_var.get(),
            ignore_names=self.ignore_names_var.get(),
        )
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    def on_close(self):
        # collect column widths if the tree already exists
        col_widths = {}
        try:
            for c in ("inc", "rel", "name", "ext", "size", "type", "target", "conf", "notes"):
                col_widths[c] = int(self.tree.column(c, "width"))
        except Exception:
            pass

        cfg = load_settings()
        cfg.update({
            "use_binary_scan": bool(self.use_binary_scan.get()),
            "recurse":         bool(self.recurse_var.get()),
            "ignore_exts":     self.ignore_exts_var.get(),
            "ignore_names":    self.ignore_names_var.get(),
            "theme":           self.theme_name.get(),
            "mods_root":       self.mods_root.get(),
            "col_widths":      col_widths,
        })
        save_settings(cfg)
        self.destroy()

    # ---- actions
    def on_browse(self):
        p = filedialog.askdirectory(initialdir=self.mods_root.get(), title="Select Mods folder")
        if p: self.mods_root.set(p)

    def on_scan(self):
        mods = self.mods_root.get()
        if not os.path.isdir(mods):
            self.status_var.set("Folder not found")
            messagebox.showerror("Scan", "Mods folder not found.")
            return

        self.status_var.set("Scanning…")
        self.progress.configure(maximum=100, value=0)
        self.items = []

        def progress_cb(done, total, path, state):
            pct = int(done / total * 100) if total else 0
            self.progress.configure(value=pct)
            # keep the status light and non-spammy
            if state == "error":
                self.status_var.set(f"Scanning {done}/{total}: {os.path.basename(path)} (error)")
            elif done % 25 == 0 or done == total:
                self.status_var.set(f"Scanning {done}/{total}: {os.path.basename(path)}")

        def worker():
            # normalise ignore_exts to have leading dots
            ignore_exts = {
                (e.strip().lower() if e.strip().startswith('.') else f".{e.strip().lower()}")
                for e in self.ignore_exts_var.get().split(',') if e.strip()
            }
            ignore_names = [t.strip().lower() for t in self.ignore_names_var.get().split(',') if t.strip()]

            items = scan_folder(
                mods,
                use_binary_scan=self.use_binary_scan.get(),
                folder_map=self.folder_map,
                recurse=self.recurse_var.get(),
                ignore_exts=ignore_exts,
                ignore_name_contains=ignore_names,
                progress_cb=progress_cb,
                detector_order=getattr(self, "detector_order", DEFAULT_DETECTOR_ORDER),
            )

            def ui_done():
                self.items = items
                self._refresh_tree()
                self.progress.configure(value=100)
                self.status_var.set(f"Scan complete: {len(self.items)} files")

            self.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()

    def on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self.sel_label.config(text="None selected")
            return
        self.sel_label.config(text=f"{len(sel)} selected")

        # when single row is selected, mirror its Type/Target into the editors
        if len(sel) == 1:
            idx = int(sel[0]); it = self.items[idx]
            if it.guess_type in CATEGORY_ORDER:
                self.type_cb.set(it.guess_type)
            else:
                self.type_cb.set("")
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, it.target_folder)

    def on_double_click(self, event=None):
        if self.tree.identify_region(event.x, event.y) != "cell":
            self.on_toggle_include()
            return
        col = self.tree.identify_column(event.x)
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0]); it = self.items[idx]

        if col == "#5":     # Type
            self.type_cb.set(it.guess_type if it.guess_type in CATEGORY_ORDER else "")
            self.type_cb.focus_set()
        elif col == "#7":   # Target
            self.target_entry.delete(0, tk.END)
            self.target_entry.insert(0, it.target_folder)
            self.target_entry.focus_set()

    def on_apply_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        new_type = self.type_cb.get().strip()
        new_target = self.target_entry.get().strip()

        for iid in sel:
            it = self.items[int(iid)]
            if new_type:
                it.guess_type = new_type
                it.confidence = max(it.confidence, 0.85)
                it.notes = (str(getattr(it, "notes", "")) + "; manual type").strip("; ")
            if new_target:
                it.target_folder = new_target
        self._refresh_tree(preserve_selection=True)

    def on_toggle_include(self):
        sel = self.tree.selection()
        if not sel:
            return
        for iid in sel:
            it = self.items[int(iid)]
            it.include = not it.include
        self._refresh_tree(preserve_selection=True)

    def on_batch_assign(self):
        kw = self.batch_keyword.get().strip().lower()
        t  = self.type_cb.get().strip()
        if not kw or not t:
            return
        tokens = [k for k in re.split(r"[ ,;]+", kw) if k]
        for it in self.items:
            low = it.name.lower()
            if any(tok in low for tok in tokens):
                it.guess_type = t
                it.confidence = max(it.confidence, 0.85)
                it.target_folder = map_type_to_folder(t, self.folder_map)
                it.notes = (str(getattr(it, "notes", "")) + "; batch type").strip("; ")
        self._refresh_tree()

    def on_recalc_targets(self):
        for it in self.items:
            it.target_folder = map_type_to_folder(it.guess_type, self.folder_map)
        self._refresh_tree(preserve_selection=True)

    def on_complete(self):
        if not self.items:
            return
        mods = self.mods_root.get()
        plan = [it for it in self.items if it.include]
        if not plan:
            self.log("No files selected to move.")
            return

        self.log(f"Starting move of {len(plan)} file(s)…")
        self.progress.configure(maximum=len(plan), value=0)

        def worker():
            moved_total = skipped_total = 0
            collisions_total, moves_log_all = [], []
            for i, it in enumerate(plan, start=1):
                moved, skipped, collisions, moves_log = perform_moves([it], mods)
                moved_total += moved; skipped_total += skipped
                collisions_total.extend(collisions); moves_log_all.extend(moves_log)
                self.after(0, lambda i=i: self.progress.configure(value=i))
            save_moves_log(mods, moves_log_all)

            def ui_done():
                self.status_var.set("Move complete")
                self.log(f"Move complete. Moved {moved_total}, Skipped {skipped_total}, Issues {len(collisions_total)}")
                for s, d, r in collisions_total[:50]:
                    self.log(f"Collision: {os.path.basename(s)} -> {os.path.dirname(d)} ({r})")
                self.on_scan()
            self.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()

    def on_undo(self):
        mods = self.mods_root.get()
        undone, failed, errs = undo_last_moves(mods)
        self.log(f"Undo: {undone} restored, {failed} failed")
        for e in errs[:50]: self.log(e)
        self.on_scan()

    def _refresh_tree(self, preserve_selection: bool = False):
        selected = set(self.tree.selection()) if preserve_selection else set()
        self.tree.delete(*self.tree.get_children())

        by_cat = {}
        for idx, it in enumerate(self.items):
            by_cat[it.guess_type] = by_cat.get(it.guess_type, 0) + 1
            inc = "✓" if it.include else ""
            rel = os.path.dirname(getattr(it, "relpath", "")) or "."

            flat_notes = "; ".join(
                p.strip() for p in re.split(r"[;\n]+", str(getattr(it, "notes", "") or "")) if p.strip()
            )

            vals = (
                inc,                                   # inc
                rel,                                   # rel
                prettify_for_ui(it.name),              # name
                it.ext,                                # ext
                it.guess_type,                         # type
                f"{getattr(it, 'size_mb', 0.0):.2f}",  # size
                it.target_folder,                      # target
                flat_notes,                            # notes
                f"{getattr(it, 'confidence', 0.0):.2f}"# conf
            )
            iid = str(idx)
            self.tree.insert("", "end", iid=iid, values=vals)
            if iid in selected:
                self.tree.selection_add(iid)

        total = len(self.items)
        if total:
            topcats = sorted(by_cat.items(), key=lambda kv: -kv[1])[:4]
            frag = ", ".join(f"{k}: {v}" for k, v in topcats)
            self.summary_var.set(f"Planned {total} files | {frag}")
        else:
            self.summary_var.set("No plan yet")

        self._on_resize()

# ---------------------------
# Entry
# ---------------------------
def main():
    app = Sims4ModSorterApp()
    app.mainloop()

if __name__ == "__main__":
    main()
