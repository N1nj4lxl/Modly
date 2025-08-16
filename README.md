# Modly

A fast desktop tool to scan your Sims 4 Mods folder, classify files, and move them into tidy subfolders. Built with Tkinter. No extra Python packages.

> Not affiliated with EA or Maxis.

---

## Features

* Smart classification using filename keywords, optional package header scan, and file extension.
* User-defined detector order. Choose how decisions are made: name, binary, extension.
* Adult content aware routing into separate buckets.
* Collision handling with date comparison
  Finds dates from filenames, zip internals, or file timestamps. Deletes the older by default, or lets you protect items and move them to **Colliding Mods**.
* Flatten and clean
  Pulls files up from random subfolders and deletes emptied folders.
* Undo last move with a persistent move log.
* Column widths persist. Resize once and it remembers.
* Multiple themes including pink presets.
* Export plan to CSV.

---

## Requirements

* Windows 10 or 11.
* Python 3.10 or newer. Tkinter is included with standard Python on Windows.

---

## Quick Start

1. **Download or clone** this repository.
2. **Run** with no console window:

   * Double-click `Sims4Modly.py` if your system runs `.py` files with `pythonw`, or
   * `pythonw Sims4Modly.py`
3. In the app, click **Browse** and select your Mods folder
   `Documents\Electronic Arts\The Sims 4\Mods`
4. Click **Scan**.
5. Review the table, adjust Type or Target Folder if needed, then click **Complete Sorting**.
   Use **Undo Last** to roll back the previous batch.
6. Optional: **Export Plan** to CSV.

Always keep a backup of your Mods folder.

---

## Using the App

1. **Browse** to your Mods folder.
2. **Scan**. The table fills with files and the proposed target folders.
3. **Selection panel** on the right:

   * Choose **Type** from the dropdown.
   * Edit **Target Folder** if you want a custom destination.
   * Click **Apply to Selected** to update marked rows.
   * **Toggle Include** to include or exclude selected files from the move.
   * **Assign Type to Matches** applies the current Type to files containing the keywords you enter.
   * **Recalculate Targets** rebuilds target folders based on the latest Type values.
4. **Complete Sorting** to perform the moves.
5. **Undo Last** to revert the last completed move batch.
6. **Export Plan** to save the current table to CSV.

---

## Settings

Open the settings overlay in the top bar.

* **Detector order**
  Order of classification steps, for example `["name", "binary", "ext"]`. Higher confidence wins. Notes are merged.
* **Binary scan**
  Reads DBPF headers of `.package` files to improve Type detection for CAS, BuildBuy, Tuning, Animation.
* **Ignore lists**
  Skip by file extension or name substrings.
* **Themes**
  Dark, Light, High Contrast, plus pink themes such as Sakura Dark and Rose Quartz Light.

Settings and column widths are saved to
`%USERPROFILE%\.sims4_modsorter_settings.json`

---

## Collisions

If a destination already has a file with the same name, the app prepares a collision plan.

* The tool derives a **best date** for each side in this order:

  1. Date inside the filename, for example `2024-08-15`, `15 Aug 2024`, `20240815`
  2. For archives and script bundles, newest file date inside the zip
  3. File modified time
  4. File created time
* Default action: **delete the older** file and complete the move.
* You can mark items as **Protected**. Protected older files are moved to
  `Mods\Colliding Mods\` instead of deleted.

All resolution operations are added to the same undo log.

---

## Undo

Each move writes to
`Mods\.sims4_modsorter_moves.json`

Click **Undo Last** to revert the most recent batch.

---

## Packaging to EXE

Build a single file with PyInstaller:

```bash
pyinstaller -F -w -i app.ico Sims4Modly.py
```

* `-F` produces one EXE.
* `-w` runs without a console window.
* Output goes to `dist\`.

Tip: rename the script to `Sims4Modly.pyw` for dev runs without a console.

---

## Troubleshooting

* **Columns keep changing width**
  Drag a header separator to your preferred widths. The app saves them.
  To reset, delete `%USERPROFILE%\.sims4_modsorter_settings.json`.
* **Scan shows nothing**
  Check the Mods path, ensure Python 3.10+. See the log pane for errors.
* **Sorting appears stuck**
  Large moves can be slow if OneDrive is syncing. Watch the progress bar. Collisions are listed at the end.
* **Antivirus blocks moves**
  Add an exception for your Mods folder and the EXE.
* **Very long paths**
  Windows path limits still apply. Keep nested folder names short.

---

## FAQ

**Does this edit package contents?**
No. It only reads headers for detection and moves files.

**Can I run it on macOS or Linux?**
The UI is Windows focused and paths assume Windows. It may run with Python and Tkinter elsewhere, but it is not supported.

**Where are logs stored?**
A move log is kept in the Mods folder. General app logs write to the log panel in the window.

---

## Contributing

* Open issues for false classifications, missing categories, or UI defects.
* Pull requests are welcome. Keep code self-contained and avoid new runtime dependencies.

---
