# === Section 1 — Imports & Core Config ======================================
from __future__ import annotations

# stdlib
import os, sys, re, csv, json, time, shutil, threading
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

# GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# local config/data (split out)
from modly.config import (
    # user-tweakable settings & constants
    THEMES, COLUMNS, HEADERS, CATEGORY_ORDER, DEFAULT_FOLDER_MAP, _CANON,
    COLLIDING_DIR_NAME, NORMALISE_DIRS,
    MAX_TOPLEVEL_FOLDERS, MAX_SUBFOLDERS_PER_TOPLEVEL,
    RECURSE_DEFAULT, IGNORE_EXTENSIONS_DEFAULT, IGNORE_NAME_CONTAINS_DEFAULT,
    DEFAULT_THEME_NAME, INITIAL_GEOMETRY, LOG_AUTOSCROLL_DEFAULT,
    DEFAULT_COLUMN_WIDTHS, SCRIPT_EXTS, ARCHIVE_EXTS,
)
from modly.keywords_loader import load_keywords

APP_NAME = "Sims 4 Modly"
APP_ID = "sims4-modly"
APP_VERSION = "0.3.0"

# User settings + move logs (editable; absolute or relative). Keep filenames short.
SETTINGS_PATH = Path.home() / ".sims4_modly.json"
MOVES_LOG_NAME = ".sims4_modsorter_moves.json"

# Load the single keyword list and pre-sort by length (longest wins)
_KEYWORDS: list[tuple[str, str]] = [(k.lower().strip(), v) for (k, v) in load_keywords()]
_KW = sorted(_KEYWORDS, key=lambda kv: (-len(kv[0]), kv[0]))

# --- Small, shared helpers (used across sections) ----------------------------

def load_settings() -> dict[str, Any]:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}

def save_settings(cfg: dict[str, Any]) -> None:
    try:
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        tmp.replace(SETTINGS_PATH)
    except Exception:
        pass

def ensure_folder(p: str | Path) -> None:
    try:
        Path(p).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

def _unique_path(dst: str) -> str:
    base, ext = os.path.splitext(dst)
    n, res = 1, dst
    while os.path.exists(res):
        res = f"{base} ({n}){ext}"
        n += 1
    return res

def _uniq_name_in(folder: str, filename: str) -> str:
    return _unique_path(os.path.join(folder, filename))

def save_moves_log(mods_root: str, ops: list[dict[str, str]]) -> None:
    try:
        log_path = os.path.join(mods_root, MOVES_LOG_NAME)
        data: list[dict[str, Any]] = []
        if os.path.isfile(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                data = json.load(f) or []
        data.extend(ops)
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

# --- Keyword helpers / canon -------------------------------------------------

def _canon(cat: str) -> str:
    return _CANON.get(cat.lower().strip(), cat)

def _norm_ignore_exts(raw: str) -> set[str]:
    out: set[str] = set()
    for tok in re.split(r"[,\s]+", raw or ""):
        t = tok.strip().lower()
        if not t:
            continue
        if not t.startswith("."):
            t = "." + t
        out.add(t)
    return out

def _norm_ignore_names(raw: str) -> set[str]:
    return {t.strip().lower() for t in re.split(r"[,\s]+", raw or "") if t.strip()}

# --- Name prettifier (UI only) ----------------------------------------------
_CAMEL_SPLIT_RE = re.compile(
    r"""
    (?<=[A-Za-z])(?=[A-Z][a-z])   |
    (?<=[a-z])(?=[A-Z])           |
    (?<=[A-Za-z])(?=\d)           |
    (?<=\d)(?=[A-Za-z])
    """, re.X
)

def _humanize_stem(stem: str) -> str:
    s = stem.replace("_", " ").replace("-", " ").replace(".", " ")
    s = _CAMEL_SPLIT_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()

def prettify_for_ui(name: str) -> str:
    base, ext = os.path.splitext(name)
    return f"{_humanize_stem(base)}{ext}"

# --- File date heuristic (collisions) ---------------------------------------
def best_date_for_file(path: str) -> tuple[float, str]:
    try:
        st = os.stat(path)
        return (float(getattr(st, "st_mtime", 0.0)) or 0.0, "mtime")
    except Exception:
        return (0.0, "unknown")

# --- Theme/style hooks (theme dicts are in config; styling applied later) ---
# These are placeholders for Section 4 which builds and applies ttk styles.
# You can change the default theme name here.
DEFAULT_THEME_NAME = load_settings().get("theme_name", "Dark Mode")

# === Section 2 — Columns, Items, Classification =============================

# Columns/headers come from modly.config (imported in Section 1)

class FileItem:
    """Row model for the tree/grid."""
    __slots__ = (
        "include", "name", "ext", "abs_path", "relpath", "size_mb",
        "guess_type", "confidence", "notes", "target_folder"
    )
    def __init__(self, *, name: str, abs_path: str, relpath: str):
        self.include: bool = True
        self.name: str = name
        self.ext: str = os.path.splitext(name)[1].lower()
        self.abs_path: str = abs_path
        self.relpath: str = relpath.replace("\\", "/")
        try:
            self.size_mb: float = max(0.0, os.path.getsize(abs_path) / (1024 * 1024))
        except Exception:
            self.size_mb = 0.0
        self.guess_type: str = "Unknown"
        self.confidence: float = 0.0
        self.notes: str = ""
        self.target_folder: str = ""

    # Convenience for UI filters/sorters
    def display_name(self) -> str:
        return prettify_for_ui(self.name)

def _flatten_notes(notes: str | list[str] | None) -> str:
    if notes is None:
        return ""
    if isinstance(notes, str):
        return notes.strip()
    try:
        return "; ".join([str(x).strip() for x in notes if str(x).strip()])
    except Exception:
        return ""

def guess_type_for_name(name: str, ext: str) -> tuple[str, float, str]:
    n = name.lower()
    if ext in SCRIPT_EXTS:
        return ("Script Mod", 0.95, "by extension")
    if ext in ARCHIVE_EXTS:
        return ("Archive", 0.70, "archive")

    for kw, cat in _KW:  # longest keyword first
        if kw and kw in n:
            cat = _canon(cat)
            return (cat, 0.70, f"keyword:{kw}")

    if ext == ".package":
        return ("Unknown", 0.40, "no keyword")
    return ("Other", 0.60, "fallback")

def map_type_to_folder(cat: str, folder_map: dict[str, str]) -> str:
    cat = _canon(cat)
    return folder_map.get(cat, folder_map.get("Unknown", "Unsorted"))

def classify_item(it: FileItem, folder_map: dict[str, str]) -> None:
    cat, conf, why = guess_type_for_name(it.name, it.ext)
    it.guess_type = cat
    it.confidence = conf
    it.notes = why
    it.target_folder = map_type_to_folder(cat, folder_map)


# === Section 3 — Scan, Bundle, Move, Undo ===================================

def scan_folder(
    mods_root: str,
    *,
    folder_map: dict[str, str],
    recurse: bool = True,
    ignore_exts: set[str] | None = None,
    ignore_name_contains: set[str] | None = None,
    detector_order: list[str] | None = None,   # kept for compatibility
    use_binary_scan: bool = False,             # kept for compatibility
    progress_cb: Callable[[int, int, str, str], None] | None = None,
) -> list[FileItem]:
    """
    Walk Mods root, create FileItem list, classify, and report progress.
    progress_cb(done, total, path, state) where state ∈ {"ok","ignored","error"}.
    """
    root = os.path.abspath(mods_root)
    ignore_exts = ignore_exts or set()
    ignore_name_contains = ignore_name_contains or set()

    # Pre-count for nicer ETA
    total = 0
    for r, d, f in os.walk(root):
        total += len(f)
        if not recurse:
            d[:] = []  # don't descend
            break

    items: list[FileItem] = []
    done = 0
    for r, d, files in os.walk(root):
        if not recurse:
            d[:] = []
        for fn in files:
            done += 1
            try:
                ext = os.path.splitext(fn)[1].lower()
                rel = os.path.relpath(os.path.join(r, fn), root)
                abp = os.path.join(r, fn)

                # Ignore rules
                lower_name = fn.lower()
                if ext in ignore_exts:
                    if progress_cb: progress_cb(done, total, rel, "ignored")
                    continue
                if any(token in lower_name for token in ignore_name_contains):
                    if progress_cb: progress_cb(done, total, rel, "ignored")
                    continue

                it = FileItem(name=fn, abs_path=abp, relpath=rel)
                classify_item(it, folder_map)
                items.append(it)
                if progress_cb: progress_cb(done, total, rel, "ok")
            except Exception:
                if progress_cb: progress_cb(done, total, fn, "error")
                continue

    return items

def bundle_scripts_and_packages(items: list[FileItem]) -> None:
    """
    Optional post-scan tidy. Currently a no-op placeholder that can:
    - Merge duplicate .ts4script + .package pairs by name stem for display grouping.
    Keep lightweight to avoid mutating file lists behind the user's back.
    """
    return

# --- Folder normalisation & empty-dir purge (safe) --------------------------

_NORMALISE_DIRS = {
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
    "colliding mods": COLLIDING_DIR_NAME,
}

def _normalise_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("_"," ").replace("-"," ").strip().lower())

def _merge_or_rename_dir(src_dir: str, dst_dir: str) -> tuple[int, int]:
    """If dst exists, merge src→dst; else rename. Returns (moved_files, removed_dirs)."""
    moved = removed = 0
    if os.path.abspath(src_dir) == os.path.abspath(dst_dir):
        # Case-only change: attempt two-step rename to force case update
        parent = os.path.dirname(src_dir)
        tmp = _unique_path(os.path.join(parent, f".__tmp__{os.path.basename(dst_dir)}"))
        try:
            os.rename(src_dir, tmp)
            os.rename(tmp, dst_dir)
        except Exception:
            pass
        return (0, 0)

    if os.path.exists(dst_dir):
        # Merge
        for root, dirs, files in os.walk(src_dir, topdown=False):
            rel = os.path.relpath(root, src_dir)
            tgt_root = os.path.join(dst_dir, "" if rel == "." else rel)
            ensure_folder(tgt_root)
            for fn in files:
                s = os.path.join(root, fn)
                d = _uniq_name_in(tgt_root, fn)
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
    else:
        # Simple rename or fallback merge
        ensure_folder(os.path.dirname(dst_dir))
        try:
            os.rename(src_dir, dst_dir)
        except Exception:
            for root, dirs, files in os.walk(src_dir, topdown=False):
                rel = os.path.relpath(root, src_dir)
                tgt_root = os.path.join(dst_dir, "" if rel == "." else rel)
                ensure_folder(tgt_root)
                for fn in files:
                    s = os.path.join(root, fn)
                    d = _uniq_name_in(tgt_root, fn)
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
    renamed, merged, created = [], 0, 0
    desired_names = set(folder_map.values()) | set(NORMALISE_DIRS.values())

    for name in sorted(desired_names):
        p = os.path.join(mods_root, name)
        if not os.path.isdir(p):
            try: os.makedirs(p, exist_ok=True); created += 1
            except Exception: pass

    existing: dict[str, list[str]] = {}
    for entry in os.listdir(mods_root):
        p = os.path.join(mods_root, entry)
        if os.path.isdir(p):
            existing.setdefault(_normalise_key(entry), []).append(entry)

    for key, names in existing.items():
        target = NORMALISE_DIRS.get(key)
        if not target:
            for d in desired_names:
                if _normalise_key(d) == key:
                    target = d; break
        if not target:
            continue

        dst = os.path.join(mods_root, target)
        for entry in names:
            src = os.path.join(mods_root, entry)
            if os.path.abspath(src) == os.path.abspath(dst) and entry == target:
                continue
            moved, removed = _merge_or_rename_dir(src, dst)
            merged += moved
            if removed or (entry != target):
                renamed.append((entry, target))

    return {"renamed": renamed, "merged_files": merged, "created": created}

def purge_empty_dirs(mods_root: str) -> int:
    """Delete empty directories under Mods (bottom-up), excluding root."""
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

# --- Move planning and collisions -------------------------------------------

def build_move_plan(mods_root: str, items: list[FileItem]) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """
    Compute (src→dst) moves and detect collisions vs the filesystem.
    Returns (moves, collisions) where collisions are (src, dst, reason).
    """
    moves: list[tuple[str, str]] = []
    collisions: list[tuple[str, str, str]] = []

    for it in items:
        if not it.include:
            continue
        if not it.target_folder:
            it.target_folder = map_type_to_folder(it.guess_type, DEFAULT_FOLDER_MAP)
        dst_dir = os.path.join(mods_root, it.target_folder)
        ensure_folder(dst_dir)
        dst = os.path.join(dst_dir, it.name)

        # Skip no-op moves
        if os.path.abspath(dst) == os.path.abspath(it.abs_path):
            continue

        if os.path.exists(dst):
            collisions.append((it.abs_path, dst, "exists"))
        else:
            moves.append((it.abs_path, dst))
    return moves, collisions

def plan_collisions(collisions: list[tuple[str, str, str]]) -> list[dict]:
    """
    Build a SAFE plan for name collisions.
    For each (src,dst), decide which is older. Default action: quarantine older.
    """
    plan: list[dict] = []
    for src, dst, _ in collisions:
        s_ts, _sm = best_date_for_file(src)
        d_ts, _dm = best_date_for_file(dst)
        older_side = "src" if (s_ts <= d_ts) else "dst"  # tie → src older
        plan.append({
            "src": src, "dst": dst,
            "src_ts": s_ts, "dst_ts": d_ts,
            "older": older_side, "protect": True
        })
    return plan

def apply_collision_plan(mods_root: str, plan: list[dict]) -> list[dict]:
    """
    Execute SAFE collision resolution:
      - Move older file to Mods/Colliding Mods (quarantine).
      - If older was at dst, move src into dst afterwards.
    Returns move operations for logging.
    """
    colliding_dir = os.path.join(mods_root, COLLIDING_DIR_NAME)
    ensure_folder(colliding_dir)
    ops: list[dict] = []

    for p in plan:
        src, dst, older = p.get("src"), p.get("dst"), p.get("older")
        if not src or not dst or older not in ("src", "dst"):
            continue

        older_path = src if older == "src" else dst
        newer_path = dst if older == "src" else src

        # Quarantine older (never delete)
        if os.path.exists(older_path):
            quarantine = _uniq_name_in(colliding_dir, os.path.basename(older_path))
            ensure_folder(os.path.dirname(quarantine))
            shutil.move(older_path, quarantine)
            ops.append({"from": older_path, "to": quarantine})

        # If destination was older, place newer at dst
        if older == "dst" and os.path.exists(src):
            final_dst = dst if not os.path.exists(dst) else _uniq_name_in(os.path.dirname(dst), os.path.basename(dst))
            ensure_folder(os.path.dirname(final_dst))
            shutil.move(src, final_dst)
            ops.append({"from": src, "to": final_dst})

    return ops

def apply_moves(moves: list[tuple[str, str]]) -> list[dict]:
    """Perform non-colliding moves. Returns ops for logging."""
    ops: list[dict] = []
    for src, dst in moves:
        try:
            ensure_folder(os.path.dirname(dst))
            if os.path.exists(dst):
                dst = _uniq_name_in(os.path.dirname(dst), os.path.basename(dst))
            shutil.move(src, dst)
            ops.append({"from": src, "to": dst})
        except Exception:
            # Skip failed move; UI should log error
            continue
    return ops

def undo_last(mods_root: str, count: int | None = None) -> int:
    """
    Naive undo: moves files back using the end of the moves log.
    If count is None, undo the entire log batch (best-effort).
    Returns number of files restored.
    """
    log_path = os.path.join(mods_root, MOVES_LOG_NAME)
    if not os.path.isfile(log_path):
        return 0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return 0
        ops = data if count is None else data[-count:]
        restored = 0
        for op in reversed(ops):
            src = op.get("to"); dst = op.get("from")
            if not src or not dst: continue
            if not os.path.exists(src): continue
            ensure_folder(os.path.dirname(dst))
            try:
                if os.path.exists(dst):
                    dst = _uniq_name_in(os.path.dirname(dst), os.path.basename(dst))
                shutil.move(src, dst)
                restored += 1
            except Exception:
                continue
        # Trim log
        if count is None:
            newlog = []
        else:
            newlog = data[:-count]
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(newlog, f, indent=2)
        return restored
    except Exception:
        return 0
# === Section 4 — UI (Styles, Window, Widgets) ===============================

class Sims4ModSorterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry(INITIAL_GEOMETRY)  # from config

        cfg = load_settings()
        self.items: list[FileItem] = []
        self._filtered_items: list[FileItem] | None = None
        self.folder_map: dict[str, str] = dict(DEFAULT_FOLDER_MAP)

        # Vars with config fallbacks
        self.mods_root = tk.StringVar(value=cfg.get("mods_root", str(Path.home())))
        self.search_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Ready")
        self.summary_var = tk.StringVar(value="No plan yet")
        self.theme_var = tk.StringVar(value=cfg.get("theme_name", DEFAULT_THEME_NAME))
        self.recurse_var = tk.BooleanVar(value=cfg.get("recurse", RECURSE_DEFAULT))
        self.ignore_exts_var = tk.StringVar(value=cfg.get("ignore_exts", IGNORE_EXTENSIONS_DEFAULT))
        self.ignore_names_var = tk.StringVar(value=cfg.get("ignore_names", IGNORE_NAME_CONTAINS_DEFAULT))

        # Scan/log counters…
        self.scan_started_at = 0.0
        self.scan_total = self.scan_done = self.scan_ok = self.scan_ignored = self.scan_errors = 0
        self.scan_count_var = tk.StringVar(value="0 / 0")
        self.scan_ok_var    = tk.StringVar(value="0 OK")
        self.scan_ign_var   = tk.StringVar(value="0 Ignored")
        self.scan_err_var   = tk.StringVar(value="0 Errors")
        self.scan_eta_var   = tk.StringVar(value="ETA —")
        self.cur_file_var   = tk.StringVar(value="")
        self.autoscroll_var = tk.BooleanVar(value=cfg.get("log_autoscroll", LOG_AUTOSCROLL_DEFAULT))

        # Sorting/columns
        self.columns_visible: list[str] = cfg.get("columns_visible", list(COLUMNS))
        self._sort_col: str | None = None
        self._sort_desc: bool = False
        self._respect_user_widths = False

        self.detector_order: list[str] = cfg.get("detector_order", [])

        self.style = ttk.Style(self)
        self._apply_theme(self.theme_var.get())
        self._build_ui()
        self.after(50, self._clamp_initial_layout)

    # --- Styling / theme -----------------------------------------------------
    def _apply_theme(self, name: str):
        c = THEMES.get(name, THEMES["Dark Mode"])
        self._theme = c
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Base colours
        self.configure(bg=c["bg"])
        self.style.configure(".", background=c["bg"], foreground=c["fg"])
        self.style.configure("TFrame", background=c["bg"])
        self.style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        self.style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        self.style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"])
        self.style.configure("TButton", background=c["alt"], foreground=c["fg"], padding=6)
        self.style.map("TButton", foreground=[("disabled", "#888")])
        # Accent button
        self.style.configure("App.Accent.TButton", background=c["accent"], foreground="#ffffff", padding=6)
        self.style.map("App.Accent.TButton", background=[("active", c["accent"])], foreground=[("disabled", "#ddd")])

        # Entry/Combobox
        self.style.configure("TEntry", fieldbackground=c["alt"], foreground=c["fg"], bordercolor=c["sel"])
        self.style.configure("TCombobox", fieldbackground=c["alt"], foreground=c["fg"], background=c["alt"])
        # Treeview
        self.style.configure("Treeview",
                             background=c["alt"], fieldbackground=c["alt"], foreground=c["fg"])
        self.style.map("Treeview",
                       background=[("selected", c["sel"])],
                       foreground=[("selected", c["fg"])])
        self.style.configure("Treeview.Heading", background=c["alt"], foreground=c["fg"])

        # Progressbars
        self.style.configure("Scan.Horizontal.TProgressbar", troughcolor=c["bg"], background=c["accent"])
        self.style.configure("Success.Horizontal.TProgressbar", troughcolor=c["bg"], background="#22C55E")
        self.style.configure("Error.Horizontal.TProgressbar", troughcolor=c["bg"], background="#EF4444")

    # --- UI build ------------------------------------------------------------
    def _build_ui(self):
        # Top bar
        top = ttk.Frame(self); top.pack(fill="x", padx=12, pady=10)

        ttk.Label(top, text="Mods folder:").pack(side="left", padx=(0, 8))
        self.path_entry = ttk.Entry(top, textvariable=self.mods_root, width=72)
        self.path_entry.pack(side="left", padx=(0, 8))

        ttk.Button(top, text="Browse", style="App.TButton", command=self.on_browse).pack(side="left", padx=(0, 6))
        ttk.Button(top, text="Scan", style="App.TButton", command=self.on_scan).pack(side="left")

        # Right-of-top controls
        ttk.Button(top, text="Columns", style="App.TButton", command=self._open_columns_dialog).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="Undo Last", style="App.TButton", command=self.on_undo).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="⚙", width=3, style="App.TButton", command=self.toggle_settings).pack(side="right", padx=(0, 12))

        # Header strip: summary + filter
        header = ttk.Frame(self); header.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(header, textvariable=self.summary_var).pack(side="left")
        ttk.Label(header, text="Filter:").pack(side="right")
        self.filter_entry = ttk.Entry(header, textvariable=self.search_var, width=24)
        self.filter_entry.pack(side="right", padx=(6, 0))
        self.filter_entry.bind("<KeyRelease>", self.on_filter)

        # Paned middle area
        self.mid = ttk.PanedWindow(self, orient="horizontal")
        self.mid.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Left pane (tree)
        left = ttk.Frame(self.mid, width=980)
        left.pack_propagate(False)
        self.mid.add(left, weight=5)

        # Right pane (selection/editor)
        right = ttk.Frame(self.mid, width=300)
        right.pack_propagate(False)
        self.mid.add(right, weight=0)

        # Tree + scrollbars
        cfg_cols = load_settings().get("columns_visible")
        self.columns_visible = [c for c in (cfg_cols or COLUMNS) if c in COLUMNS] or list(COLUMNS)

        self.tree = ttk.Treeview(left, columns=COLUMNS, show="headings", selectmode="extended")
        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=ysb.set, xscroll=xsb.set)

        # Default column widths (from config)
        for col, w in DEFAULT_COLUMN_WIDTHS.items():
            self.tree.column(
                col, width=w, minwidth=40, stretch=False,
                anchor=("w" if col in ("rel", "name", "target", "notes") else "center")
            )
        # Default column widths (px). Minwidth is editable; stretch=False prevents tugging.
        defaults = {"inc": 28, "rel": 200, "name": 360, "ext": 70, "type": 160,
                    "size": 70, "target": 200, "notes": 360, "conf": 66}
        for col, w in defaults.items():
            self.tree.column(col, width=w, minwidth=40, stretch=False,
                             anchor=("w" if col in ("rel", "name", "target", "notes") else "center"))

        # Restore widths
        saved = load_settings().get("col_widths") or {}
        if isinstance(saved, dict):
            for col, w in saved.items():
                if col in COLUMNS:
                    try: self.tree.column(col, width=int(w))
                    except Exception: pass

        self._apply_displaycolumns()

        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="left", fill="y")
        xsb.pack(side="bottom", fill="x")

        self.tree.bind("<ButtonRelease-1>", self._on_header_release, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select, add="+")  # update selection label

        # Selection/editor panel (right)
        ttk.Label(right, text="Selection").pack(anchor="w")
        self.sel_label = ttk.Label(right, text="None selected")
        self.sel_label.pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Type").pack(anchor="w")
        self.type_cb = ttk.Combobox(right, values=CATEGORY_ORDER, state="readonly")
        self.type_cb.pack(fill="x", pady=(0, 8))

        ttk.Label(right, text="Target Folder").pack(anchor="w")
        self.target_entry = ttk.Entry(right)
        self.target_entry.pack(fill="x", pady=(0, 8))

        ttk.Button(right, text="Apply to Selected",      style="App.TButton", command=self.on_apply_selected).pack(fill="x", pady=4)
        ttk.Button(right, text="Toggle Include",         style="App.TButton", command=self.on_toggle_include).pack(fill="x", pady=4)
        ttk.Button(right, text="Assign Type to Matches", style="App.TButton", command=self.on_batch_assign).pack(fill="x")
        ttk.Button(right, text="Recalculate Targets",    style="App.TButton", command=self.on_recalc_targets).pack(fill="x", pady=4)
        ttk.Button(right, text="Select All",             style="App.TButton",
                   command=lambda: self.tree.selection_set(self.tree.get_children())).pack(fill="x", pady=2)
        ttk.Button(right, text="Select None",            style="App.TButton",
                   command=lambda: self.tree.selection_remove(self.tree.get_children())).pack(fill="x", pady=2)

        # Scan strip (counters + ETA)
        strip = ttk.Frame(self); strip.pack(fill="x", padx=12, pady=(4, 0))
        ttk.Label(strip, text="Scanned:").pack(side="left")
        ttk.Label(strip, textvariable=self.scan_count_var).pack(side="left", padx=(4, 12))
        ttk.Label(strip, textvariable=self.scan_ok_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_ign_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_err_var).pack(side="left", padx=(0, 12))
        ttk.Label(strip, textvariable=self.scan_eta_var).pack(side="left", padx=(0, 12))

        # Bottom bar: progress + actions
        bottom = ttk.Frame(self); bottom.pack(fill="x", padx=12, pady=8)
        self.progress = ttk.Progressbar(bottom, orient="horizontal", mode="determinate",
                                        style="Scan.Horizontal.TProgressbar")
        self.progress.pack(fill="x", side="left", expand=True)

        btns = ttk.Frame(bottom); btns.pack(side="right")
        ttk.Button(btns, text="Export Plan",      style="App.Accent.TButton", command=self.on_export_plan).pack(side="left", padx=6)
        ttk.Button(btns, text="Complete Sorting", style="App.Accent.TButton", command=self.on_complete).pack(side="left", padx=6)
        ttk.Button(btns, text="Clean Folders",    style="App.TButton",        command=self.on_clean_folders).pack(side="left", padx=6)

        # Logs
        logf = ttk.Frame(self); logf.pack(fill="both", padx=12, pady=(0, 10))
        toolbar = ttk.Frame(logf); toolbar.pack(fill="x", pady=(0, 4))
        ttk.Label(toolbar, text="Logs").pack(side="left")
        ttk.Button(toolbar, text="Clear", style="App.TButton",
                   command=lambda: (self.log_text.configure(state="normal"),
                                    self.log_text.delete("1.0", "end"),
                                    self.log_text.configure(state="disabled"))).pack(side="right", padx=(0, 8))
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.autoscroll_var).pack(side="right")

        self.log_text = tk.Text(logf, height=8, wrap="word", state="disabled", relief="flat",
                                bg=self._theme["alt"], fg=self._theme["fg"])
        self.log_text.pack(fill="both", expand=False)
        self.log_text.tag_configure("OK",   foreground="#22C55E")
        self.log_text.tag_configure("INFO", foreground=self._theme["fg"])
        self.log_text.tag_configure("WARN", foreground="#F59E0B")
        self.log_text.tag_configure("ERR",  foreground="#EF4444")

        # Settings panel (hidden by default)
        self._settings_shown = False
        self.settings_panel = ttk.Frame(self, padding=8)
        # build contents
        row1 = ttk.Frame(self.settings_panel); row1.pack(fill="x", pady=2)
        ttk.Checkbutton(row1, text="Recurse into subfolders", variable=self.recurse_var).pack(side="left")
        ttk.Label(row1, text="Theme:").pack(side="left", padx=(12, 4))
        theme_cb = ttk.Combobox(row1, state="readonly", values=sorted(THEMES.keys()), textvariable=self.theme_var, width=20)
        theme_cb.pack(side="left")
        theme_cb.bind("<<ComboboxSelected>>", lambda e: self._on_theme_change())

        row2 = ttk.Frame(self.settings_panel); row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Ignore extensions:").pack(side="left")
        ttk.Entry(row2, textvariable=self.ignore_exts_var, width=48).pack(side="left", padx=(6, 0))
        row3 = ttk.Frame(self.settings_panel); row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="Ignore names:").pack(side="left")
        ttk.Entry(row3, textvariable=self.ignore_names_var, width=48).pack(side="left", padx=(6, 0))

        # Collision overlay (hidden)
        self._collision_plan: list[dict] = []
        self._col_overlay = ttk.Frame(self, style="TFrame")
        self._col_overlay.place_forget()  # hidden

        card = ttk.Frame(self._col_overlay, padding=12)
        card.pack_propagate(False)
        self._col_card = card

        title = ttk.Label(card, text="Collision Review"); title.pack(anchor="w", pady=(0, 8))
        self.col_tree = ttk.Treeview(card, columns=("keep", "older", "older_dt", "newer", "newer_dt", "dest"),
                                     show="headings", height=12)
        for c, t, w in [
            ("keep", "Keep Older?", 100), ("older", "Older", 240), ("older_dt", "Older Date", 130),
            ("newer", "Newer", 240), ("newer_dt", "Newer Date", 130), ("dest", "Destination Folder", 200)
        ]:
            self.col_tree.heading(c, text=t)
            self.col_tree.column(c, width=w, stretch=False, anchor="w")
        y2 = ttk.Scrollbar(card, orient="vertical", command=self.col_tree.yview)
        self.col_tree.configure(yscroll=y2.set)
        self.col_tree.pack(side="left", fill="both", expand=True)
        y2.pack(side="right", fill="y")

        btnrow = ttk.Frame(card); btnrow.pack(fill="x", pady=(8, 0))
        ttk.Button(btnrow, text="Keep Older (Protect)", style="App.TButton", command=self._col_protect_selected).pack(side="left")
        ttk.Button(btnrow, text="Unprotect", style="App.TButton", command=self._col_unprotect_selected).pack(side="left", padx=6)
        ttk.Button(btnrow, text="Apply", style="App.Accent.TButton", command=self._col_apply).pack(side="right")
        ttk.Button(btnrow, text="Cancel", style="App.TButton", command=lambda: self._toggle_collision(False)).pack(side="right", padx=(0, 6))

    # Keep the sash sensible on first paint
    def _clamp_initial_layout(self):
        try:
            total = max(self.winfo_width(), 1000)
            right_min = 300
            pos = max(680, total - right_min - 40)
            self.mid.sashpos(0, pos)
        except Exception:
            pass

# === Section 5 — Handlers, Wiring, Logic ====================================

    # ----- Settings / theme -----
    def toggle_settings(self):
        if self._settings_shown:
            self.settings_panel.pack_forget()
            self._settings_shown = False
        else:
            self.settings_panel.pack(fill="x", padx=12, pady=(0, 8))
            self._settings_shown = True

    def _on_theme_change(self):
        name = self.theme_var.get()
        self._apply_theme(name)
        # Refresh widget colours that cache bg/fg
        try:
            self.log_text.configure(bg=self._theme["alt"], fg=self._theme["fg"])
        except Exception:
            pass
        cfg = load_settings(); cfg["theme_name"] = name; save_settings(cfg)

    # ----- Logging -----
    def log(self, msg: str, level: str = "INFO"):
        level = level.upper()
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        self.log_text.configure(state="normal")
        try:
            self.log_text.insert("end", line, (level if level in {"OK","INFO","WARN","ERR"} else "INFO",))
            if self.autoscroll_var.get():
                self.log_text.see("end")
        finally:
            self.log_text.configure(state="disabled")

    # ----- Progress helpers -----
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
        self.scan_done = done
        if state == "ok":
            self.scan_ok += 1
        elif state.startswith("ignored"):
            self.scan_ignored += 1
        elif state == "error":
            self.scan_errors += 1

        elapsed = max(0.001, time.time() - self.scan_started_at)
        rate = done / elapsed if done else 0.0
        rem = (total - done) / rate if rate > 0 else 0.0
        eta_txt = f"ETA {int(rem//60)}m {int(rem%60)}s" if rem else "ETA —"

        self.scan_count_var.set(f"{done} / {total}")
        self.scan_ok_var.set(f"{self.scan_ok} OK")
        self.scan_ign_var.set(f"{self.scan_ignored} Ignored")
        self.scan_err_var.set(f"{self.scan_errors} Errors")
        self.scan_eta_var.set(eta_txt)
        base = os.path.basename(path) if path else ""
        self.status_var.set(f"Scanning {done}/{total}: {base}" if base else "Scanning…")
        self.progress.configure(value=done)

    def _progress_finish(self, had_errors: bool):
        self.status_var.set("Scan complete")
        self.progress.configure(style=("Error.Horizontal.TProgressbar" if had_errors else "Success.Horizontal.TProgressbar"))

    # ----- Tree helpers -----
    def _apply_displaycolumns(self):
        vis = [c for c in self.columns_visible if c in COLUMNS]
        if not vis: vis = ["name"]
        self.tree.configure(displaycolumns=vis)

    def _on_header_release(self, ev=None):
        # Persist widths only when user interacts with heading/separator
        try:
            region = self.tree.identify_region(ev.x, ev.y)
            if region not in ("separator", "heading"):
                return
        except Exception:
            pass
        self._respect_user_widths = True
        cw = {c: int(self.tree.column(c)["width"]) for c in COLUMNS}
        s = load_settings(); s["col_widths"] = cw; save_settings(s)

    def _sort_by(self, col: str):
        last_col = self._sort_col
        last_desc = self._sort_desc
        self._sort_col = col
        self._sort_desc = (not last_desc) if (last_col == col) else False
        self._refresh_tree(preserve_selection=True)

    def _sort_key_for_item(self, it: FileItem):
        col = self._sort_col
        if not col: return 0
        if col == "name":   return it.display_name().lower()
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

    def _on_tree_select(self, _evt=None):
        sel = self.tree.selection()
        self.sel_label.configure(text=f"{len(sel)} selected" if sel else "None selected")

    def _refresh_tree(self, preserve_selection: bool = False):
        """Rebuild grid from items or filtered subset, respecting sort + visible columns."""
        selected = set(self.tree.selection()) if preserve_selection else set()
        self.tree.delete(*self.tree.get_children())

        src = self._filtered_items if self._filtered_items is not None else self.items
        if self._sort_col:
            try:
                src = sorted(src, key=self._sort_key_for_item, reverse=bool(self._sort_desc))
            except Exception:
                pass

        by_cat: dict[str, int] = {}
        for idx, it in enumerate(src):
            by_cat[it.guess_type] = by_cat.get(it.guess_type, 0) + 1
            inc = "✓" if it.include else ""
            rel = os.path.dirname(getattr(it, "relpath", "")) or "."
            vals = (inc, rel, it.display_name(), it.ext, it.guess_type,
                    f"{getattr(it,'size_mb',0.0):.2f}", it.target_folder,
                    _flatten_notes(it.notes), f"{getattr(it,'confidence',0.0):.2f}")
            iid = str(idx)
            self.tree.insert("", "end", iid=iid, values=vals)
            if iid in selected:
                self.tree.selection_add(iid)

        total = len(src)
        if total:
            topcats = sorted(by_cat.items(), key=lambda kv: -kv[1])[:4]
            frag = ", ".join(f"{k}: {v}" for k, v in topcats)
            self.summary_var.set(f"Planned {total} files | {frag}")
        else:
            self.summary_var.set("No plan yet")

        self._apply_displaycolumns()

    # ----- Column dialog -----
    def _open_columns_dialog(self):
        win = tk.Toplevel(self)
        win.title("Columns")
        win.transient(self)
        win.resizable(False, False)
        try: win.configure(bg=self._theme["bg"])
        except Exception: pass

        vars_map: dict[str, tk.BooleanVar] = {}
        for col in COLUMNS:
            v = tk.BooleanVar(value=(col in self.columns_visible))
            vars_map[col] = v
            ttk.Checkbutton(win, text=HEADERS.get(col, col), variable=v).pack(anchor="w", padx=12, pady=4)

        btns = ttk.Frame(win); btns.pack(fill="x", padx=12, pady=8)
        def _select_all(val: bool):
            for v in vars_map.values(): v.set(val)

        ttk.Button(btns, text="All",   style="App.TButton", command=lambda: _select_all(True)).pack(side="left")
        ttk.Button(btns, text="None",  style="App.TButton", command=lambda: _select_all(False)).pack(side="left", padx=6)
        ttk.Button(btns, text="Reset", style="App.TButton",
                   command=lambda: [vars_map[c].set(True) for c in COLUMNS]).pack(side="left", padx=6)

        def _apply_and_close():
            self.columns_visible = [c for c,v in vars_map.items() if v.get()]
            cfg = load_settings(); cfg["columns_visible"] = self.columns_visible; save_settings(cfg)
            self._apply_displaycolumns()
            win.destroy()

        ttk.Button(btns, text="Close", style="App.Accent.TButton", command=_apply_and_close).pack(side="right")

    # ----- Filter -----
    def on_filter(self, _evt=None):
        q = (self.search_var.get() or "").strip().lower()
        if not q:
            self._filtered_items = None
            self._refresh_tree()
            return
        src = self.items
        out: list[FileItem] = []
        for it in src:
            if q in it.display_name().lower() or q in (it.guess_type or "").lower() or q in (it.target_folder or "").lower() or q in (it.notes or "").lower():
                out.append(it)
        self._filtered_items = out
        self._refresh_tree()

    # ----- Browse -----
    def on_browse(self):
        d = filedialog.askdirectory(initialdir=self.mods_root.get(), title="Select Mods folder")
        if d:
            self.mods_root.set(d)
            cfg = load_settings(); cfg["mods_root"] = d; save_settings(cfg)

    # ----- Scan -----
    def on_scan(self):
        mods = self.mods_root.get()
        if not os.path.isdir(mods):
            messagebox.showerror("Scan", "Mods folder not found.")
            return

        # Pre-count files for accurate ETA
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
            self.after(0, lambda d=done, t=total_cb, p=path, s=("ignored" if str(state).startswith("ignored") else state):
                       self._progress_update_ui(d, t or total, p, s))

        def worker():
            ignore_exts = _norm_ignore_exts(self.ignore_exts_var.get())
            ignore_names = _norm_ignore_names(self.ignore_names_var.get())

            items = scan_folder(
                mods_root=mods,
                folder_map=self.folder_map,
                recurse=self.recurse_var.get(),
                ignore_exts=ignore_exts,
                ignore_name_contains=ignore_names,
                detector_order=self.detector_order,
                use_binary_scan=False,
                progress_cb=progress_cb,
            )
            bundle_scripts_and_packages(items)

            def ui_done():
                self.items = items
                self._filtered_items = None
                self._progress_finish(had_errors=(self.scan_errors > 0))
                self.summary_var.set(f"Scan complete: {len(self.items)} file(s)")
                self._refresh_tree()
                self.log(f"Scan complete. Files: {len(self.items)}, OK: {self.scan_ok}, Ignored: {self.scan_ignored}, Errors: {self.scan_errors}",
                         "WARN" if self.scan_errors else "OK")

            self.after(0, ui_done)

        threading.Thread(target=worker, daemon=True).start()

    # ----- Apply selection / batch -----
    def on_apply_selected(self):
        sel = self.tree.selection()
        if not sel: return
        typ = self.type_cb.get().strip() if self.type_cb.get() else None
        tgt = self.target_entry.get().strip() if self.target_entry.get() else None

        src = self._filtered_items if self._filtered_items is not None else self.items
        for iid in sel:
            try:
                idx = int(iid)
                it = src[idx]
                if typ:
                    it.guess_type = typ
                    it.target_folder = map_type_to_folder(typ, self.folder_map)
                if tgt:
                    it.target_folder = tgt
            except Exception:
                continue
        self._refresh_tree(preserve_selection=True)

    def on_toggle_include(self):
        sel = self.tree.selection()
        if not sel: return
        src = self._filtered_items if self._filtered_items is not None else self.items
        for iid in sel:
            try:
                idx = int(iid)
                it = src[idx]
                it.include = not it.include
            except Exception:
                continue
        self._refresh_tree(preserve_selection=True)

    def on_batch_assign(self):
        """Assign currently chosen Type to all rows matching the filter."""
        typ = self.type_cb.get().strip()
        if not typ:
            return
        src = self._filtered_items if self._filtered_items is not None else self.items
        for it in src:
            it.guess_type = typ
            it.target_folder = map_type_to_folder(typ, self.folder_map)
        self._refresh_tree()

    def on_recalc_targets(self):
        """Re-map all items to target folders using current folder_map."""
        src = self._filtered_items if self._filtered_items is not None else self.items
        for it in src:
            it.target_folder = map_type_to_folder(it.guess_type, self.folder_map)
        self._refresh_tree()

    # ----- Export / Complete -----
    def on_export_plan(self):
        if not self.items:
            messagebox.showinfo("Export", "Nothing to export. Scan first.")
            return
        mods = self.mods_root.get()
        csv_path = filedialog.asksaveasfilename(title="Export Plan (CSV)", defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")], initialdir=mods, initialfile="Modly_Plan.csv")
        if not csv_path:
            return

        def _cat_index(cat: str) -> int:
            c = _canon(cat)
            try:
                return CATEGORY_ORDER.index(c)
            except ValueError:
                return 999

        src = self._filtered_items if self._filtered_items is not None else self.items
        src_sorted = sorted(
            src,
            key=lambda it: (_cat_index(it.guess_type),
                            os.path.dirname(it.relpath or "").lower(),
                            it.name.lower())
        )
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Include","Folder","File","Ext","Type","MB","Target","Notes","Conf"])
            for it in src_sorted:
                w.writerow([
                    "Y" if it.include else "",
                    os.path.dirname(it.relpath or "") or ".",
                    it.name, it.ext, _canon(it.guess_type),
                    f"{getattr(it,'size_mb',0.0):.2f}",
                    it.target_folder,
                    _flatten_notes(it.notes),
                    f"{getattr(it,'confidence',0.0):.2f}",
                ])
        self.log(f"Plan exported: {csv_path}", "OK")

    def on_complete(self):
        """Move files to targets, resolve collisions safely (quarantine older)."""
        if not self.items:
            messagebox.showinfo("Complete Sorting", "Nothing to move. Scan first.")
            return
        mods = self.mods_root.get()
        moves, collisions = build_move_plan(mods, self.items)
        self.log(f"Planned moves: {len(moves)}; collisions: {len(collisions)}", "INFO")

        # Apply non-colliding moves first
        ops = apply_moves(moves)
        save_moves_log(mods, ops)
        self.log(f"Moved {len(ops)} file(s).", "OK")

        if collisions:
            # Build plan and show overlay
            plan = plan_collisions(collisions)
            self._toggle_collision(True, plan=plan)
        else:
            # Post tidy
            self.on_clean_folders(auto=True)
            self.status_var.set("Move complete")

    # ----- Collision overlay handlers -----
    def _toggle_collision(self, show: bool, plan: list[dict] | None = None):
        if show:
            self._collision_plan = plan or []
            for r in self.col_tree.get_children():
                self.col_tree.delete(r)

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
            # Show overlay filling window; centre card with sensible width
            self._col_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
            w = max(720, min(self.winfo_width()-160, 1000))
            self._col_card.configure(width=w)
            self._col_card.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self._col_overlay.place_forget()

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
        mods = self.mods_root.get()
        # SAFE: quarantine older; place newer if needed
        ops = apply_collision_plan(mods, self._collision_plan)
        save_moves_log(mods, ops)
        self._toggle_collision(False)
        # Tidy + refresh
        try:
            self.on_clean_folders(auto=True)
        except Exception:
            self.on_scan()

    # ----- Folder clean / undo -----
    def on_clean_folders(self, auto: bool = False):
        mods = self.mods_root.get()
        summary = normalise_top_level_folders(mods, self.folder_map)
        removed = purge_empty_dirs(mods)
        msg = (f"Folders cleaned: created {summary['created']}, "
               f"renamed {len(summary['renamed'])}, merged {summary['merged_files']} files, "
               f"removed {removed} empty folder(s).")
        self.log(msg, "OK")
        self.on_scan()

    def on_undo(self):
        mods = self.mods_root.get()
        n = undo_last(mods, count=None)
        self.log(f"Undo restored {n} file(s).", "OK")
        self.on_scan()

# === Section 6 — Entry Point ================================================

def _set_windows_dpi_awareness():
    """Improve Tk scaling on high-DPI Windows displays."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

def _install_excepthook():
    """Show a GUI message on unexpected crashes and write a minimal crash log."""
    def _hook(exc_type, exc, tb):
        import traceback
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            crash_path = Path.home() / "Sims4Modly_crash.log"
            crash_path.write_text(text, encoding="utf-8")
        except Exception:
            pass
        try:
            messagebox.showerror("Unexpected error",
                                 "The app hit an unexpected error.\n"
                                 "A crash log was written to your home folder.\n\n"
                                 f"{exc_type.__name__}: {exc}")
        finally:
            # Also print to stderr for dev runs
            print(text, file=sys.stderr)
    sys.excepthook = _hook

def main():
    # Optional: accept a Mods path as the first CLI argument
    cli_mods = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else None

    _set_windows_dpi_awareness()
    _install_excepthook()

    app = Sims4ModSorterApp()

    # Apply CLI Mods path if provided and valid
    if cli_mods and cli_mods.is_dir():
        app.mods_root.set(str(cli_mods))
        cfg = load_settings()
        cfg["mods_root"] = str(cli_mods)
        save_settings(cfg)

    app.mainloop()

if __name__ == "__main__":
    # Hides the console when packaged:
    # - PyInstaller: build with --noconsole
    # - Nuitka: use --windows-console-mode=disable
    # Running from source on Windows: use pythonw.exe instead of python.exe.
    main()



