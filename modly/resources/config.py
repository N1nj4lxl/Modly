# modly/config.py
# Clean, centralised settings. Safe to edit. Keep values within noted ranges.

from __future__ import annotations

# === Safety & Behaviour ======================================================

# NEVER delete on collisions. Older file is quarantined to this folder.
COLLIDING_DIR_NAME: str = "Colliding Mods"

# Extra guard. Leave False unless you add an explicit “Delete permanently” mode.
ALLOW_PERMANENT_DELETE: bool = False  # True/False

# Normalise known folder name variants (top-level only).
# Edit if you prefer different canonical names.
NORMALISE_DIRS: dict[str, str] = {
    "script mod": "Script Mods", "script mods": "Script Mods",
    "gameplay mod": "Gameplay Mods", "gameplay mods": "Gameplay Mods",
    "gameplay tuning": "Gameplay Tuning",
    "adult - gameplay": "Adult - Gameplay", "adult gameplay": "Adult - Gameplay",
    "adult - cas": "Adult - CAS", "adult cas": "Adult - CAS",
    "cas clothing": "CAS Clothing", "cas hair": "CAS Hair", "cas accessories": "CAS Accessories",
    "build buy": "Build Buy", "build/buy": "Build Buy", "build&buy": "Build Buy",
    "override": "Overrides", "overrides": "Overrides",
    "animation": "Animations", "animations": "Animations",
    "utilities": "Utilities", "utility": "Utilities",
    "archive": "Archives", "archives": "Archives",
    "other": "Other", "unsorted": "Unsorted",
    "colliding mods": "Colliding Mods",
}

# Folder count limits (for future enforcement in UI/workflow).
MAX_TOPLEVEL_FOLDERS: int = 6      # 1–12 sensible
MAX_SUBFOLDERS_PER_TOPLEVEL: int = 4  # 1–10 sensible

# === Scan Defaults ===========================================================

# Recurse into subfolders by default.
RECURSE_DEFAULT: bool = True  # True/False

# Space/comma separated extensions to ignore. Words may include the leading dot or not.
# Examples: ".txt .md, .psd"
IGNORE_EXTENSIONS_DEFAULT: str = ".txt .md .psd .png .jpg .jpeg"

# Space/comma separated substrings in filenames to ignore (case-insensitive).
IGNORE_NAME_CONTAINS_DEFAULT: str = "readme license changelog"

# File-type shortcuts (keep lists small and focused)
SCRIPT_EXTS: tuple[str, ...] = (".ts4script",)
ARCHIVE_EXTS: tuple[str, ...] = (".zip", ".rar", ".7z")

# === UI Defaults =============================================================

# Start-up theme. Must be a key from THEMES below.
DEFAULT_THEME_NAME: str = "Dark Mode"

# Initial window size (WxH). Users can resize freely.
INITIAL_GEOMETRY: str = "1280x720"

# Autoscroll logs by default.
LOG_AUTOSCROLL_DEFAULT: bool = True  # True/False

# Tree columns and headers (keep names stable; shown in the Columns dialog)
COLUMNS: tuple[str, ...] = ("inc", "rel", "name", "ext", "type", "size", "target", "notes", "conf")
HEADERS: dict[str, str] = {
    "inc": "✓", "rel": "Folder", "name": "File", "ext": "Ext", "type": "Type",
    "size": "MB", "target": "Target Folder", "notes": "Notes", "conf": "Conf",
}

# Default column widths in pixels. Min: 40, Max: 1200 (practical).
DEFAULT_COLUMN_WIDTHS: dict[str, int] = {
    "inc": 28, "rel": 200, "name": 360, "ext": 70, "type": 160,
    "size": 70, "target": 200, "notes": 360, "conf": 66,
}

# === Categories & Folder Map =================================================

# Category order used in dropdowns and summaries. Add/remove as needed.
CATEGORY_ORDER: list[str] = [
    "Script Mod",
    "Gameplay Tuning",
    "Utilities",
    "Overrides",
    "CAS Clothing",
    "CAS Hair",
    "CAS Accessories",
    "Build/Buy",
    "Animations",
    "Pose",
    "Preset",
    "Slider",
    "World",
    "Archive",
    "Other",
    "Unknown",
    "Adult - Gameplay",
    "Adult - CAS",
]

# Where categories map to target folders. Change names to suit your structure.
DEFAULT_FOLDER_MAP: dict[str, str] = {
    "Script Mod": "Script Mods",
    "Gameplay Tuning": "Gameplay Mods",
    "Utilities": "Utilities",
    "Overrides": "Overrides",
    "CAS Clothing": "CAS Clothing",
    "CAS Hair": "CAS Hair",
    "CAS Accessories": "CAS Accessories",
    "Build/Buy": "Build Buy",
    "Animations": "Animations",
    "Pose": "Poses",
    "Preset": "Presets",
    "Slider": "Sliders",
    "World": "World",
    "Archive": "Archives",
    "Other": "Other",
    "Unknown": "Unsorted",
    "Adult - Gameplay": "Adult - Gameplay",
    "Adult - CAS": "Adult - CAS",
}

# Canonicalisation: unify loose/sub-categories to real buckets.
_CANON: dict[str, str] = {
    "adult gameplay": "Adult - Gameplay",
    "adult animation": "Adult - Gameplay",
    "adult cas": "Adult - CAS",
    "adult buildbuy": "Build/Buy",
    "buildbuy object": "Build/Buy",
    "buildbuy recolour": "Build/Buy",
    "utility tool": "Utilities",
    # CAS subtypes funnel to Accessories by default
    "cas makeup": "CAS Accessories",
    "cas eyes": "CAS Accessories",
    "cas tattoos": "CAS Accessories",
    "cas skin": "CAS Accessories",
}

# === Themes ==================================================================
# Colours: bg (window), fg (text), alt (cards/inputs), accent (primary), sel (selection)
THEMES: dict[str, dict[str, str]] = {
    "Dark Mode":          {"bg": "#111316", "fg": "#E6E6E6", "alt": "#161A1E", "accent": "#4C8BF5", "sel": "#2A2F3A"},
    "Slightly Dark Mode": {"bg": "#14161a", "fg": "#EAEAEA", "alt": "#1b1e24", "accent": "#6AA2FF", "sel": "#2f3642"},
    "Light Mode":         {"bg": "#FAFAFA", "fg": "#1f2328", "alt": "#FFFFFF", "accent": "#316DCA", "sel": "#E8F0FE"},
    "High Contrast Mode": {"bg": "#000000", "fg": "#FFFFFF", "alt": "#000000", "accent": "#FFD400", "sel": "#333333"},
    "Dracula":            {"bg": "#282a36", "fg": "#f8f8f2", "alt": "#1e2029", "accent": "#bd93f9", "sel": "#44475a"},
    "Nord":               {"bg": "#2E3440", "fg": "#ECEFF4", "alt": "#3B4252", "accent": "#88C0D0", "sel": "#434C5E"},
    "Ocean Dark":         {"bg": "#0b1220", "fg": "#e6edf3", "alt": "#0f172a", "accent": "#38bdf8", "sel": "#18253f"}
}
