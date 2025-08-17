# modly/config.py
from __future__ import annotations

# Top-level constants
COLLIDING_DIR_NAME = "Colliding Mods"

# Tree columns and headers
COLUMNS = ("inc","rel","name","ext","type","size","target","notes","conf")
HEADERS = {
    "inc":"✓","rel":"Folder","name":"File","ext":"Ext","type":"Type",
    "size":"MB","target":"Target Folder","notes":"Notes","conf":"Conf"
}

# Category order used in comboboxes/summary (match your current order)
CATEGORY_ORDER = [
    "Script Mod","Gameplay Tuning","Utilities","Overrides",
    "CAS Clothing","CAS Hair","CAS Accessories",
    "Build/Buy","Animations","Pose","Preset","Slider",
    "World","Archive","Other","Unknown",
    "Adult - Gameplay","Adult - CAS"
]

# Where categories map to folders (users can override via settings.json)
DEFAULT_FOLDER_MAP: dict[str,str] = {
    "Script Mod":"Script Mods",
    "Gameplay Tuning":"Gameplay Mods",
    "Utilities":"Utilities",
    "Overrides":"Overrides",
    "CAS Clothing":"CAS Clothing",
    "CAS Hair":"CAS Hair",
    "CAS Accessories":"CAS Accessories",
    "Build/Buy":"Build Buy",
    "Animations":"Animations",
    "Pose":"Poses",
    "Preset":"Presets",
    "Slider":"Sliders",
    "World":"World",
    "Archive":"Archives",
    "Other":"Other",
    "Unknown":"Unsorted",
    "Adult - Gameplay":"Adult - Gameplay",
    "Adult - CAS":"Adult - CAS",
}

# Canonicalisation for classifier outputs → map to your real buckets
_CANON = {
    "adult gameplay":"Adult - Gameplay",
    "adult animation":"Adult - Gameplay",
    "adult cas":"Adult - CAS",
    "adult buildbuy":"Build/Buy",
    "buildbuy object":"Build/Buy",
    "buildbuy recolour":"Build/Buy",
    "utility tool":"Utilities",
    # CAS subtypes → Accessories unless you split them elsewhere
    "cas makeup":"CAS Accessories",
    "cas eyes":"CAS Accessories",
    "cas tattoos":"CAS Accessories",
    "cas skin":"CAS Accessories",
}

# Theme palette (keep what you already have)
THEMES = {
    "Dark Mode": {"bg":"#111316","fg":"#E6E6E6","alt":"#161A1E","accent":"#4C8BF5","sel":"#2A2F3A"},
    "Slightly Dark Mode": {"bg":"#14161a","fg":"#EAEAEA","alt":"#1b1e24","accent":"#6AA2FF","sel":"#2f3642"},
    "Light Mode": {"bg":"#FAFAFA","fg":"#1f2328","alt":"#FFFFFF","accent":"#316DCA","sel":"#E8F0FE"},
    "High Contrast Mode": {"bg":"#000000","fg":"#FFFFFF","alt":"#000000","accent":"#FFD400","sel":"#333333"},
    "Pink Holiday": {"bg":"#1a1216","fg":"#FFE7F3","alt":"#23171e","accent":"#FF5BA6","sel":"#3a1f2c"},
    "Dracula": {"bg":"#282a36","fg":"#f8f8f2","alt":"#1e2029","accent":"#bd93f9","sel":"#44475a"},
    "Nord": {"bg":"#2E3440","fg":"#ECEFF4","alt":"#3B4252","accent":"#88C0D0","sel":"#434C5E"},
    "Ocean Dark": {"bg":"#0b1220","fg":"#e6edf3","alt":"#0f172a","accent":"#38bdf8","sel":"#18253f"},
    # your pink presets can live here too
}
