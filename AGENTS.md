# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-08
**Commit:** ef4637b
**Branch:** main

## OVERVIEW
Python CLI tool that merges an image folder into a multi-page PDF by shelling out to IrfanView's `/multipdf`. Stdlib-only. Portable mode auto-downloads IrfanView-64 into a local cache (no pre-install needed). Windows-only runtime.

## STRUCTURE
```
Images-to-PDF/
├── folder_to_pdf.py        # core app: all logic + console loop
├── launcher.py             # portable launcher: download/extract IrfanView cache
├── test_folder_to_pdf.py   # unittest suite (18 tests)
├── README.md               # usage docs (zh/en)
└── LICENSE                 # MIT
```

Single flat module — no packages, no subdirectories.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Entry point + loop | `folder_to_pdf.py:main()` | non-closing console loop; supports `--irfanview-path` |
| Portable launcher | `launcher.py:main()` | downloads IrfanView cache, then runs main script |
| Download/extract pipeline | `launcher.py:ensure_irfanview()` | handles anti-bot midpage + DLL relocation |
| Folder input prompt | `prompt_folder()` | drag-and-drop; exit on `exit/quit/q`/empty |
| Convert dispatch (single vs batch) | `convert_folder()` | auto-detects subdirs-with-images |
| One subfolder → PDF | `convert_single_folder()` | core conversion, reused by batch |
| Batch detection | `subfolders_with_images()` | returns only image-bearing subdirs, natural-sorted |
| Image gathering | `collect_images()` | top-level only, natural sort |
| Command builder | `build_multipdf_cmd()` | returns shell STRING (see pitfall) |
| IrfanView locate | `resolve_irfanview()` | override → .lnk → PATH → registry |
| PDF plugin check | `check_pdf_plugin()` | requires `Plugins/PDF.dll` |
| Natural sort key | `natural_key()` | numeric-aware; `2` before `10` |

## CODE MAP
| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `main` | func | folder_to_pdf.py:289 | - | console loop; `--irfanview-path`/folder args |
| `convert_folder` | func | folder_to_pdf.py:247 | 1 | single/batch dispatcher |
| `convert_single_folder` | func | folder_to_pdf.py:198 | 1 | per-folder conversion |
| `subfolders_with_images` | func | folder_to_pdf.py:237 | 1 | batch subdir detection |
| `collect_images` | func | folder_to_pdf.py:138 | 1 | image gather + sort |
| `build_multipdf_cmd` | func | folder_to_pdf.py:152 | 1 | shell command build |
| `resolve_irfanview` | func | folder_to_pdf.py:59 | 1 | IrfanView detection (override-aware) |
| `set_irfanview_override` | func | folder_to_pdf.py:53 | - | portable path injection |
| `check_pdf_plugin` | func | folder_to_pdf.py:127 | 1 | PDF.dll check |
| `natural_key` | func | folder_to_pdf.py:41 | 2 | natural sort key |
| `prompt_folder` | func | folder_to_pdf.py:188 | 1 | input prompt + exit |
| `ensure_irfanview` | func | launcher.py:58 | - | download/extract cached IrfanView |
| `cleanup_cache` | func | launcher.py:49 | - | purge cache dir |
| `run_main` | func | launcher.py:191 | 1 | launch folder_to_pdf with portable exe |
| `_download_verified` | func | launcher.py:111 | 1 | download + SHA-256 + midpage handling |
| `_fetch` | func | launcher.py:136 | 1 | download with UA/Referer |
| `_relocate_plugin_dlls` | func | launcher.py:175 | 1 | move root DLLs into Plugins/ |

## CONVENTIONS
- Single-file app; NO packages/subpackages. All functions top-level in `folder_to_pdf.py`.
- User-editable config is a single hardcoded constant block at top: `OUTPUT_DIR`.
- Console output is Chinese (zh-CN) — keep it localized.
- Function naming: snake_case, one responsibility per function.
- Since it's flat, "drill into a package" never applies here.

## ANTI-PATTERNS (THIS PROJECT)
- **NEVER pass a list to `subprocess.run` for the IrfanView call.** Windows `list2cmdline` escapes embedded quotes and silently breaks `/multipdf=(...)`. The command MUST be a string run with `shell=True`.
- **NEVER recurse into subfolders** in `collect_images` — it uses `folder.iterdir()` (top-level only). Recursion is handled separately via batch mode on the parent folder.
- **NEVER remove the `shell=True`** on the `subprocess.run(cmd, ...)` call.
- Do NOT introduce third-party deps (natsort, Pillow, PyPDF2) — stdlib only.
- **NEVER hardcode a stale SHA-256** in launcher.py — official downloads return varying versions; repin to the actual value. Use `--no-verify` when repinning a new version.

## UNIQUE STYLES
- Filelist fallback: `build_multipdf_cmd` switches to a `filelist=` temp file when the CLI exceeds 3800 chars. Written in ANSI (`mbcs`) encoding for Chinese-path compat (with a `LookupError` fallback to system default on non-Windows hosts for tests).
- Natural sort implemented via inline regex split (no natsort dep).
- IrfanView located by resolving desktop `.lnk` first (user's install is non-standard: `D:\电脑应用\IrfanView`).
- Portable mode downloads official IrfanView-64 from `irfanview.info` (NOT redistributed; EULA-friendly), caches under `%TEMP%\Images-to-PDF\irfanview\` and auto-deletes it on exit (try/finally in `main()`) so it never permanently occupies disk. `--keep-cache` disables the cleanup; `--cleanup` purges on demand.

## COMMANDS
```bash
# tests (any platform with Python)
python -m unittest test_folder_to_pdf -v

# syntax check
python -m py_compile folder_to_pdf.py launcher.py test_folder_to_pdf.py

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

# manual run (Windows)
# double-click folder_to_pdf.py, drop a folder in, press Enter
```

## NOTES
- Production runs on Windows calling the IrfanView exe; the WSL/Linux host can only compile-check and unit-test (no IrfanView, no `mbcs`, no `winreg`). The launcher's download/extract/relocate logic IS verifiable on Linux (~/.local/share cache).
- **Anti-bot trap in launcher.py:** the official `irfanview.info` `/files/*.zip` URLs first return an HTML "Click again to start Download" page, not the ZIP. `_fetch` re-requests with a `Referer` header to get the real file.
- **DLL relocation:** the plugins ZIP puts `PDF.dll` at the zip root; `_relocate_plugin_dlls` moves root-level `.dll` files into `Plugins/` so IrfanView finds them.
- Unit tests import the script via `importlib` from a relative path and run on Linux — keep test logic host-agnostic.
- Blast radius is small (single-file; most functions have 1 caller). Verify `convert_folder` and `build_multipdf_cmd` before editing — they carry the trickiest behavior.
