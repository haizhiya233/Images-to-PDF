# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-09  
**Commit:** 89212209  
**Branch:** main  
**Version:** v2.0.0 (TUI + Performance Optimized)

## OVERVIEW

Python CLI tool that merges image folders into multi-page PDFs by shelling out to IrfanView's `/multipdf`. Stdlib-only. Features:
- **Core:** Single image folder → single PDF; parent folder with subfolders → batch mode (one PDF per subfolder)
- **Performance:** 4-thread parallel batch processing (3-4x faster), IrfanView path cached to memory (80x fewer detections)
- **UX:** Beautiful TUI progress grid, real-time percentage (0-100%), ETA estimation
- **Portable:** Auto-downloads official IrfanView-64 to `%TEMP%` cache (ephemeral, auto-cleaned on exit)

## STRUCTURE

```
Images-to-PDF/
├── folder_to_pdf.py        # core app: TUI + parallel batch + caching
├── launcher.py             # portable launcher: download/extract IrfanView cache
├── test_folder_to_pdf.py   # unittest suite (18 tests)
├── README.md               # comprehensive usage docs (zh/en)
├── AGENTS.md               # this file
└── LICENSE                 # MIT
```

Single flat module — no packages, no subdirectories.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Entry point + loop | `folder_to_pdf.py:main()` | non-closing console loop; supports `--irfanview-path` |
| Convert dispatch (single vs batch) | `convert_folder()` | auto-detects subdirs-with-images → single/batch mode |
| **Batch parallel processing** | `convert_folder_batch()` | ThreadPoolExecutor(4), real-time TUI grid updates |
| **TUI progress grid** | `class TUIProgressGrid` | renders percentage, ETA, emoji grid (✅/❌/⏳) |
| One subfolder → PDF | `convert_single_folder()` | core conversion, reused by batch, returns Path or None |
| Batch detection | `subfolders_with_images()` | returns only image-bearing subdirs, natural-sorted |
| Image gathering | `collect_images()` | top-level only, natural sort |
| Command builder | `build_multipdf_cmd()` | returns shell STRING; fallback to filelist on >3800 chars |
| **IrfanView locate + cache** | `resolve_irfanview()` | override → .lnk → PATH → registry; result cached in memory |
| PDF plugin check | `check_pdf_plugin()` | requires `Plugins/PDF.dll` |
| Natural sort key | `natural_key()` | numeric-aware; `2` before `10` |
| Input prompt | `prompt_folder()` | drag-and-drop; exit on `exit/quit/q`/empty |
| Portable launcher | `launcher.py:main()` | downloads IrfanView cache, then runs folder_to_pdf |
| Download/extract pipeline | `launcher.py:ensure_irfanview()` | handles anti-bot midpage + SHA-256 verify + DLL relocation |

## CODE MAP

### folder_to_pdf.py (Main Module)

| Symbol | Type | Location | Caller Count | Role |
|--------|------|----------|--------------|------|
| `main` | func | :289 | - | console loop; argparse for `--irfanview-path`/folder |
| `convert_folder` | func | :247 | 1 (main loop) | dispatcher: single file → single PDF; batch → parallel TUI grid |
| `convert_folder_batch` | func | :265 | 1 (convert_folder) | **NEW:** ThreadPoolExecutor(MAX_WORKERS), TUI grid render, ETA calc |
| `convert_single_folder` | func | :219 | 2 (batch executor, single mode) | per-folder conversion; no console output (silent for batch threads) |
| `subfolders_with_images` | func | :257 | 2 (convert_folder, TUI setup) | batch subdir detection |
| `collect_images` | func | :157 | 1 (convert_single_folder) | image gather + natural sort |
| `build_multipdf_cmd` | func | :170 | 1 (convert_single_folder) | shell command build; filelist fallback on long paths |
| `resolve_irfanview` | func | :79 | 1 (convert_folder) | IrfanView detection (5 strategies); cached to `_irfanview_cache` (memory) |
| `set_irfanview_override` | func | :76 | 1 (main) | portable path injection; sets global `_irfanview_override` |
| `check_pdf_plugin` | func | :146 | 1 (convert_folder) | PDF.dll check |
| `natural_key` | func | :61 | 3 (collect_images, subfolders_with_images, test) | natural sort key generator |
| `prompt_folder` | func | :213 | 1 (main loop) | input prompt + exit handling |
| **class TaskStatus** | enum-like | :51 | - | **NEW:** status emoji constants (⏳/✅/❌) |
| **class TUIProgressGrid** | class | :278 | 1 (batch) | **NEW:** renders progress, percentage, ETA, emoji grid |

### launcher.py (Portable Mode)

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `main` | func | :202 | entry point; orchestrates download/cleanup |
| `ensure_irfanview` | func | :58 | download/extract IrfanView cache; handles SHA-256 verify |
| `cleanup_cache` | func | :49 | purge cache dir (idempotent) |
| `run_main` | func | :191 | launch folder_to_pdf with portable exe path |
| `_download_verified` | func | :111 | download + SHA-256 + anti-bot midpage handling |
| `_fetch` | func | :136 | download with UA/Referer headers |
| `_extract_zip` | func | :164 | safe zip extraction (zip-slip protection) |
| `_relocate_plugin_dlls` | func | :175 | move root DLLs into Plugins/ subdirectory |

## CONVENTIONS

- Single-file app; NO packages/subpackages. All functions top-level in `folder_to_pdf.py`.
- **New (v2.0):** `class TUIProgressGrid` for OOP progress state management.
- User-editable config block at top: `OUTPUT_DIR`, `MAX_WORKERS`, `GRID_WIDTH`.
- Console output is Chinese (zh-CN) — keep it localized.
- Function naming: snake_case, one responsibility per function.
- Global state: `_irfanview_cache`, `_irfanview_lock` (thread-safe), `_irfanview_override`.
- No third-party deps — stdlib only.

## KEY IMPROVEMENTS (v2.0)

### 1. Caching: IrfanView Path (Memory)
```python
_irfanview_cache = None
_irfanview_lock = threading.Lock()

def resolve_irfanview():
    global _irfanview_cache
    if _irfanview_cache is not None:
        return _irfanview_cache  # fast path, no lock
    with _irfanview_lock:
        if _irfanview_cache is not None:
            return _irfanview_cache  # double-check
        # ... detect IrfanView ...
        _irfanview_cache = p  # cache to memory
        return p
```
**Benefit:** Batch processing 80 folders: 80 detections → 1 detection (80x fewer registry queries).

### 2. Parallel Batch Processing
```python
def convert_folder_batch(folder, irfan):
    grid = TUIProgressGrid(len(subdirs), grid_width=GRID_WIDTH)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, sub in enumerate(subdirs):
            future = executor.submit(convert_single_folder, sub, irfan)
            futures[future] = i
        for future in as_completed(futures):
            idx = futures[future]
            grid.update(idx, status)
            grid.render()
```
**Benefit:** 4 threads convert in parallel; 80 folders × 30s each: 40 min → 10 min (3-4x faster).

### 3. TUI Progress Grid
```python
class TUIProgressGrid:
    def render(self):
        # 1. Calc percentage
        percent = (completed / self.total) * 100
        # 2. Estimate ETA
        if completed > 0:
            avg_time = elapsed / completed
            remaining = (self.total - completed) * avg_time
        # 3. Draw grid (emoji per task)
        for i in range(0, self.total, self.grid_width):
            row = self.results[i:i+self.grid_width]
            print(" ".join(status for status in row))
```
**Display Example:**
```
進度：42/80 (52.5%) ETA: 120s
--------------------------------------------------------------------
✅ ✅ ✅ ✅ ✅ ✅ ✅ ✅
✅ ✅ ❌ ✅ ✅ ✅ ✅ ✅
✅ ✅ ✅ ✅ ✅ ✅ ⏳ ⏳
...
```

### 4. Task Status Enum
```python
class TaskStatus:
    PENDING = "⏳"
    SUCCESS = "✅"
    FAILED = "❌"
```

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER pass a list to `subprocess.run` for the IrfanView call.** Windows `list2cmdline` escapes embedded quotes and silently breaks `/multipdf=(...)`. The command MUST be a string run with `shell=True`.
- **NEVER recurse into subfolders** in `collect_images` — it uses `folder.iterdir()` (top-level only). Recursion is handled separately via batch mode on the parent folder.
- **NEVER remove the `shell=True`** on the `subprocess.run(cmd, ...)` call.
- **NEVER remove the `_irfanview_lock`** in `resolve_irfanview()` — multiple threads may call it during batch; lock ensures first caller initializes cache, others wait.
- Do NOT introduce third-party deps (natsort, Pillow, PyPDF2, tqdm) — stdlib only.
- **NEVER hardcode a stale SHA-256** in launcher.py — official downloads return varying versions; repin to the actual value. Use `--no-verify` when repinning a new version.

## UNIQUE STYLES & TRICKS

### Memory Caching (Process-Lifetime)
- IrfanView path is detected once, cached to `_irfanview_cache`, and discarded when process exits.
- Avoids disk residue (unlike launcher's `%TEMP%` cache which is ephemeral by design).
- Thread-safe via `threading.Lock`.

### Parallel + Real-Time TUI
- `ThreadPoolExecutor(max_workers=4)` runs conversions concurrently.
- `as_completed()` iterates tasks in completion order (not submission order).
- Each completion updates `grid.results[idx]`, re-renders percentage + ETA + emoji grid.
- No blocking; grid is refreshed in real-time as tasks finish.

### Filelist Fallback
- `build_multipdf_cmd` switches to a `filelist=` temp file when the CLI exceeds 3800 chars.
- Written in ANSI (`mbcs`) encoding for Chinese-path compat (with a `LookupError` fallback to system default).
- Temp file is cleaned up after `subprocess.run`.

### Natural Sort
- Implemented via inline regex split (no natsort dep): `re.split(r"(\d+)", name)`.
- Numeric parts are cast to int; alpha parts lowercased for case-insensitive sort.

### IrfanView Detection (5 Strategies)
1. Resolve desktop `.lnk` target (handles non-standard installs like `D:\电脑应用\IrfanView`).
2. Check `C:\Program Files\IrfanView\i_view64.exe`.
3. Check `C:\Program Files (x86)\IrfanView\i_view32.exe`.
4. Scan `PATH` environment variable.
5. Query Windows registry `HKCU\Software\IrfanView`.

### Portable Mode
- Launcher downloads official IrfanView-64 from `irfanview.info` (NOT redistributed; EULA-friendly).
- Caches under `%TEMP%\Images-to-PDF\irfanview\`.
- Auto-deletes cache on exit (try/finally in `main`).
- SHA-256 verified by default; handles official "Click again to start Download" anti-bot page.

### DLL Relocation
- Plugins ZIP puts `PDF.dll` at zip root.
- `_relocate_plugin_dlls` moves root-level `.dll` files into `Plugins/` so IrfanView finds them.

## PERFORMANCE TARGETS (v2.0)

| Metric | Old | New | Gain |
|--------|-----|-----|------|
| IrfanView detections (80-folder batch) | 80 | 1 | 80x |
| Total time (80 folders, 30s each) | 40 min | 10 min | 3-4x |
| Memory footprint (cache) | ~30MB disk | ~1KB memory | ↓ |
| User feedback (progress) | None | Real-time grid + ETA | UX ↑↑ |

## COMMANDS

```bash
# tests (any platform with Python)
python -m unittest test_folder_to_pdf -v

# syntax check
python -m py_compile folder_to_pdf.py launcher.py test_folder_to_pdf.py

# core: drag-and-drop folder, then Enter
python folder_to_pdf.py

# portable mode (auto-downloads IrfanView cache, then runs)
python launcher.py

# force re-download latest cache
python launcher.py --update

# download/extract only, don't run
python launcher.py --download-only

# keep cache after exit (default auto-cleans)
python launcher.py --keep-cache

# purge cache now
python launcher.py --cleanup

# direct folder path (no prompt)
python folder_to_pdf.py "D:\MyFolder"

# manual run (Windows)
# double-click folder_to_pdf.py, drag a folder in, press Enter
```

## CONFIGURATION

Edit constants at top of `folder_to_pdf.py`:

```python
OUTPUT_DIR = Path(r"C:\Users\YourName\Desktop\PDF_Output")  # Output directory (MUST change)
MAX_WORKERS = 4                                             # Parallel threads (default: 4)
GRID_WIDTH = 8                                              # Grid cells per row (default: 8)
```

## NOTES FOR MAINTAINERS

- **Production:** Runs on Windows calling IrfanView exe. WSL/Linux host can only unit-test (no IrfanView, no `mbcs`, no `winreg`).
- **Anti-bot trap in launcher.py:** Official `irfanview.info` `/files/*.zip` URLs first return an HTML "Click again to start Download" page. `_fetch` re-requests with a `Referer` header to get the real ZIP.
- **DLL relocation:** Plugins ZIP puts `PDF.dll` at root; `_relocate_plugin_dlls` moves it into `Plugins/` so IrfanView finds it.
- **Unit tests:** Import the script via `importlib` from a relative path and run on Linux — keep test logic host-agnostic.
- **Blast radius:** Small (single-file; most functions have 1 caller). Verify `convert_folder`, `convert_folder_batch`, `build_multipdf_cmd`, and `resolve_irfanview` before editing — they carry the trickiest behavior.
- **Thread safety:** `resolve_irfanview()` uses `threading.Lock` to ensure cache initialization is atomic. `convert_folder_batch()` uses `ThreadPoolExecutor` to safely parallelize folder conversions.
- **No external deps:** Keep it stdlib-only for easy deployment and minimal attack surface.

## TEST COVERAGE

18 unit tests in `test_folder_to_pdf.py`:
- ✅ Natural sort logic (numeric, case-insensitive)
- ✅ Image collection (top-level only, extension filtering, natural sort)
- ✅ Command building (short list direct, long list filelist fallback)
- ✅ Subfolder detection (batch mode, natural sort)
- ✅ IrfanView override mechanism

Run:
```bash
python -m unittest test_folder_to_pdf -v
```

## RECENT CHANGES (v2.0)

- **Added** `class TUIProgressGrid` for real-time progress rendering.
- **Added** `class TaskStatus` for emoji constants.
- **Added** `convert_folder_batch()` function for parallel batch processing.
- **Added** memory caching to `resolve_irfanview()` with `threading.Lock`.
- **Modified** `convert_folder()` to dispatch single vs. batch mode cleanly.
- **Modified** `main()` to set up Windows console size for TUI.
- Maintained backward compatibility: single-folder mode unchanged, API unchanged.

## FUTURE WORK

- Color output (emoji is enough for now, but could add ANSI colors for status indicators).
- Persistent config file (instead of editing code constants).
- Logging to file (for debugging batch runs).
- Async I/O (replace ThreadPoolExecutor with asyncio for further optimization).
- Web UI (Flask/FastAPI for headless servers).
