# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-25  
**Commit:** 59ba91b  
**Branch:** main

## OVERVIEW

Stdlib-only Windows CLI that merges image folders into multi-page PDFs by shelling out to
IrfanView 64's `/multipdf`. No third-party Python deps. `launcher.py` is an optional
portable wrapper that downloads IrfanView to a throwaway `%TEMP%` cache.

## STRUCTURE

```
Images-to-PDF/
├── folder_to_pdf.py        # core app: TUI + parallel batch + caching
├── launcher.py             # portable launcher: download/extract IrfanView cache
├── test_folder_to_pdf.py   # unittest suite (29 tests)
├── README.md               # comprehensive usage docs (zh/en)
├── AGENTS.md               # this file
└── LICENSE                 # MIT
```

Single flat module — no packages, no subdirectories.

## CODE MAP

### folder_to_pdf.py (Main Module)

| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `main` | func | :438 | 1 | console loop (non-closing); argparse `--irfanview-path`/folder |
| `convert_folder` | func | :381 | 1 | dispatcher: subdirs-with-images → batch, else single PDF; **applies compression INI** |
| `convert_folder_batch` | func | :345 | 1 | ThreadPoolExecutor(MAX_WORKERS), live TUI grid |
| `convert_single_folder` | func | :265 | 1 | per-folder conversion via `executor.submit`; silent (no console output) |
| `subfolders_with_images` | func | :294 | 2 | image-bearing subdirs, natural-sorted |
| `prompt_folder` | func | :255 | 1 | drag-and-drop prompt; exits on `exit`/`quit`/`q`/empty |
| `build_multipdf_cmd` | func | :228 | 2 | **shell STRING** + `/ini=`; filelist fallback >3800 chars |
| `collect_images` | func | :214 | 2 | image gather, top-level only, natural sort |
| `apply_pdf_compression` | func | :192 | 1 | atomically writes tool-owned `i_viewNN.ini` (`[PDF]` Compr* keys) |
| `check_pdf_plugin` | func | :181 | 1 | requires `Plugins/PDF.dll` |
| `ini_encoding` | func | :88 | 2 | `mbcs` on Windows, else system default; shared by INI + filelist writers |
| `resolve_irfanview` | func | :98 | 1 | 5-strategy detection; cached to `_irfanview_cache` |
| `set_irfanview_override` | func | :74 | 1 | portable path injection; sets `_irfanview_override` |
| `natural_key` | func | :80 | 2 | numeric-aware sort key (`2` before `10`) |
| **class TaskStatus** | enum-like | :68 | - | status emoji constants (⏳/✅/❌) |
| **class TUIProgressGrid** | class | :304 | 1 | renders progress, percentage, ETA, emoji grid |

### launcher.py (Portable Mode)

| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `DEFAULT_VERSION` | const | :26 | IrfanView version string, part of the download URL |
| `IVIEW_URL` / `PLUGINS_URL` | const | :27 / :28 | official `irfanview.info` ZIP templates |
| `VERSION_SHA256` | const | :30 | `{version: (main_zip_sha, plugins_zip_sha)}`; unknown version **must** require `--no-verify` |
| `SCRIPT_DIR` / `EXE_NAME` | const | :37 / :38 | script dir; `i_view64.exe` |
| `cache_dir` | func | :41 | `%TEMP%\Images-to-PDF\irfanview`, fallback `~/.local/share/...` when no `%TEMP%` |
| `cleanup_cache` | func | :53 | idempotent `rmtree` of cache root |
| `ensure_irfanview` | func | :62 | returns exe path; download → verify → extract → relocate DLLs; falls back to stale cache if download fails |
| `_download_verified` | func | :123 | fetch, detect anti-bot interstitial, SHA-256 check, write |
| `_fetch` | func | :148 | urllib GET with UA + optional `Referer` |
| `_extract_download_url` | func | :158 | pulls the real href out of the interstitial page |
| `_sha256` | func | :168 | file digest helper |
| `_extract_zip` | func | :176 | zip-slip guard: every member must `.relative_to(dest_dir.resolve())` |
| `_relocate_plugin_dlls` | func | :190 | moves root-level DLLs (incl. `PDF.dll`) into `Plugins/` |
| `run_main` | func | :206 | `subprocess.call([sys.executable, folder_to_pdf.py, --irfanview-path, exe])` |
| `main` | func | :217 | argparse; `try/finally` guarantees cache cleanup unless `--keep-cache` |

## CONVENTIONS

- Single-file app; NO packages/subpackages. All functions top-level in `folder_to_pdf.py`.
- User-editable config block at top: `OUTPUT_DIR`, `MAX_WORKERS`, `GRID_WIDTH`, `PDF_COMPRESSION`, `PDF_INI_DIR`.
- **No third-party deps — stdlib only** (no Pillow/pypdf/typer/rich). Tests use `unittest`, not pytest.
- Console output is Chinese (zh-CN) — keep it localized.
- snake_case, one responsibility per function.
- Global state: `_irfanview_cache`, `_irfanview_lock` (thread-safe), `_irfanview_override`.

## PDF OUTPUT SIZE (the `/ini=` mechanism)

IrfanView's PDF plugin defaults to `ComprColor=1` = **Flate / zlib lossless**: it decodes
each JPEG to raw RGB (72.9 MB for a 3976x6114 page) and re-compresses to ~17 MB. On
manga/screentone content that is a **4x–17x bloat with zero quality gain** — lossless LZ
cannot compress dithered line art the way lossy DCT can.

The plugin has **no CLI switch** for this, but reads it from an INI: section `[PDF]`, keys
`ComprColor` / `ComprGray` / `ComprBW`. It also honours `/ini="Folder"` to relocate INI
read/write, which **takes precedence** over the INI beside the exe and needs no admin rights.
`apply_pdf_compression()` writes that INI; `build_multipdf_cmd()` injects `/ini=` into both
the direct and the filelist branch (and counts it in the 3800-char budget).

| `PDF_COMPRESSION` | Plugin setting | Measured vs source |
|---|---|---|
| 1 | Flate lossless (plugin default) | 4.63x |
| **2 (default)** | **JPEG q95** | **1.14x** |
| 3 | JPEG q80 | 0.89x |
| 4 | JPEG q65 | 0.79x |
| 5 | JPEG q40 | 0.44x |

Measured on 1988x3057 q80 comic pages (1.10 MB source): Flate → 5.07 MB, q95 → 1.25 MB.
Real case: 158 MB of JPEGs had been producing 2.6 GB of PDFs.

**These values are undocumented by IrfanView** — determined empirically by running the real
plugin and parsing output `/Filter`. Section/key names were recovered by disassembling
`PDF.dll` (x64 `lea rcx, [0x22b126]` → `"PDF"`, then the three `Compr*` keys). Verified:
`/ini=` works before *or* after `/multipdf=`; paths with spaces are fine; the plugin does
**not** write the INI back during `/multipdf`, so N concurrent IrfanView processes sharing
one INI is safe — hence one call before the thread pool, not per folder. Rewritten every
run because the launcher wipes its cache on exit.

**Not implemented — lossless passthrough:** embedding the original JPEG bytes as
`/DCTDecode` gives exactly 1.00x at zero quality loss (prototype verified), but needs a
custom PDF writer for every non-JPEG format the tool accepts (multi-frame TIFF, animated
GIF, CMYK/16-bit PNG). Poor trade against q95's 1.14x.

## ANTI-PATTERNS (THIS PROJECT)

- **NEVER pass a list to `subprocess.run` for the IrfanView call.** Windows `list2cmdline` escapes embedded quotes and silently breaks `/multipdf=(...)`. The command MUST be a string run with `shell=True`.
- **NEVER recurse into subfolders** in `collect_images` — it uses `folder.iterdir()` (top-level only). Recursion is handled separately via batch mode on the parent folder.
- **NEVER remove the `shell=True`** on the `subprocess.run(cmd, ...)` call.
- **NEVER drop the `/ini=` argument** in `build_multipdf_cmd()`. Without it IrfanView falls back to the plugin default (Flate lossless) and output PDFs balloon 4-17x. If output size suddenly explodes, check this first.
- **NEVER rename the generated INI to anything but `i_view64.ini` / `i_view32.ini`.** IrfanView matches the filename to the exe bitness; IrfanView's own docs state the name must not be changed.
- **NEVER remove the `_irfanview_lock`** in `resolve_irfanview()` — multiple threads may call it during batch; lock ensures first caller initializes cache, others wait.
- Do NOT introduce third-party deps (natsort, Pillow, PyPDF2, tqdm) — stdlib only.
- **NEVER reuse a SHA-256 for another IrfanView version** — add the version to `VERSION_SHA256`, or require explicit `--no-verify`.

## UNIQUE STYLES

- **IrfanView path cached in memory** (`_irfanview_cache` + `Lock`), detected once per process — unlike the launcher's `%TEMP%` cache, leaves no disk residue.
- **Batch = `ThreadPoolExecutor` + `as_completed()`**; each completion mutates `grid.results[idx]` and re-renders percentage/ETA/emoji. Completion order, not submission order.
- **Natural sort** without natsort: `re.split(r"(\d+)", name)`, digits cast to `int`, alpha lowercased.
- **IrfanView detection order** (first hit wins): desktop `.lnk` target → `Program Files` 64/32 → `PATH` → `HKCU\Software\IrfanView` registry. The `.lnk` path is first because installs often live outside `Program Files`.
- **Filelist fallback** when the command exceeds 3800 chars: temp `.txt` in `mbcs` (Chinese paths), deleted after `subprocess.run`.
- **Console output is Chinese**, including error text and the compression level line.

## COMMANDS

```bash
python -m unittest test_folder_to_pdf -v          # 29 tests, runs on Linux+Windows
python -m py_compile folder_to_pdf.py launcher.py test_folder_to_pdf.py

python folder_to_pdf.py                          # interactive: drag folder, Enter
python folder_to_pdf.py "D:\MyFolder"            # non-interactive
python folder_to_pdf.py --irfanview-path <exe>   # force a specific IrfanView

python launcher.py                               # portable: fetch IrfanView, then run
python launcher.py --update                      # force re-download
python launcher.py --download-only               # populate cache, don't run
python launcher.py --keep-cache                  # skip exit-time cleanup
python launcher.py --cleanup                     # purge cache and exit
python launcher.py --no-verify                   # skip SHA-256 (unknown version)
```

## CONFIGURATION

Constants at top of `folder_to_pdf.py`:

```python
OUTPUT_DIR = Path(r"C:\Users\YourName\Desktop\PDF_Output")  # MUST change
MAX_WORKERS = 16                                            # batch threads
GRID_WIDTH = 8                                              # TUI cells per row
PDF_COMPRESSION = 2                                         # 1=Flate 2=q95 3=q80 4=q65 5=q40
PDF_INI_DIR = Path(__file__).parent / ".irfanview_ini"      # tool-owned IrfanView INI dir
```

`.irfanview_ini/` is created at runtime and is **not** in `.gitignore` (no .gitignore exists).

## NOTES FOR MAINTAINERS

- **Production is Windows-only.** WSL/Linux can only run the unit tests — no IrfanView, no `mbcs`, no `winreg`, no PowerShell `.lnk` resolution.
- **Anti-bot trap:** official `irfanview.info` `/files/*.zip` URLs return an HTML "Click again to start Download" page first. `_download_verified` detects it and re-fetches the real href with a `Referer` header. Do not "simplify" this away.
- **Stale-cache fallback:** if download fails but a previous cache exists, `ensure_irfanview` uses it rather than failing outright.
- **DLL relocation:** the plugins ZIP puts `PDF.dll` at its root; `_relocate_plugin_dlls` moves root-level DLLs into `Plugins/` or IrfanView will not find them.
- **zip-slip guard:** `_extract_zip` validates every member against `dest_dir.resolve()` before `extractall`. Keep the `relative_to` check.
- **Tests import via `importlib`** from a relative path so they run on Linux; keep test logic host-agnostic and patch module globals (`OUTPUT_DIR`, `PDF_INI_DIR`, `PDF_COMPRESSION`) with save/restore rather than writing into the repo.
- **LSP caveat:** an LSP reports false "instance variable not initialized" / "cannot assign to ModuleType" errors on this codebase — that is the established `setUp` + `importlib` pattern, not a real defect.

## TEST COVERAGE

29 tests, `test_folder_to_pdf.py`:
- Natural sort (numeric, case-insensitive)
- Image collection (top-level only, extension filter, natural sort)
- Command building — short direct **and** long filelist fallback, both carrying `/ini=`
- Subfolder detection for batch mode
- IrfanView override mechanism
- Failed conversion cannot be mistaken for a stale PDF
- ZIP path traversal rejection; unknown launcher version requires `--no-verify`
- `ini_encoding()` returns a codec Python can resolve
- `apply_pdf_compression()` — INI name follows exe bitness (`i_view64`/`i_view32`), contains `[PDF]` + all three `Compr*` keys, creates its dir, leaves no `.tmp` residue

**Untested by design:** anything requiring the real IrfanView binary. The `/ini=` mechanism
was verified manually end-to-end (real `cmd.exe` + real plugin, exe-adjacent INI deliberately
set to Flate to prove `/ini` precedence).
