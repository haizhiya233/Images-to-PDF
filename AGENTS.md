# PROJECT KNOWLEDGE BASE

**Generated:** 2026-09-08
**Commit:** 0e9bafe
**Branch:** main

## OVERVIEW
Python CLI tool that merges an image folder into a multi-page PDF by shelling out to IrfanView's `/multipdf`. Windows-only (calls IrfanView 64 exe), stdlib-only, no external deps.

## STRUCTURE
```
图片转PDF/
├── folder_to_pdf.py    # single-file app: all logic + console loop
├── test_folder_to_pdf.py  # unittest suite (15 tests)
├── README.md           # usage docs (zh/en)
└── LICENSE             # MIT
```

Single flat module — no packages, no subdirectories.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Entry point + loop | `folder_to_pdf.py:main()` | non-closing console loop |
| Folder input prompt | `prompt_folder()` | drag-and-drop; exit on `exit/quit/q`/empty |
| Convert dispatch (single vs batch) | `convert_folder()` | auto-detects subdirs-with-images |
| One subfolder → PDF | `convert_single_folder()` | core conversion, reused by batch |
| Batch detection | `subfolders_with_images()` | returns only image-bearing subdirs, natural-sorted |
| Image gathering | `collect_images()` | top-level only, natural sort |
| Command builder | `build_multipdf_cmd()` | returns shell STRING (see pitfall) |
| IrfanView locate | `resolve_irfanview()` | .lnk → common paths → PATH → registry |
| PDF plugin check | `check_pdf_plugin()` | requires `Plugins/PDF.dll` |
| Natural sort key | `natural_key()` | numeric-aware; `2` before `10` |

## CODE MAP
| Symbol | Type | Location | Refs | Role |
|--------|------|----------|------|------|
| `main` | func | folder_to_pdf.py:274 | - | console loop |
| `convert_folder` | func | folder_to_pdf.py:232 | 1 | single/batch dispatcher |
| `convert_single_folder` | func | folder_to_pdf.py:183 | 1 | per-folder conversion |
| `subfolders_with_images` | func | folder_to_pdf.py:222 | 1 | batch subdir detection |
| `collect_images` | func | folder_to_pdf.py:123 | 1 | image gather + sort |
| `build_multipdf_cmd` | func | folder_to_pdf.py:137 | 1 | shell command build |
| `resolve_irfanview` | func | folder_to_pdf.py:49 | 1 | IrfanView detection |
| `check_pdf_plugin` | func | folder_to_pdf.py:112 | 1 | PDF.dll check |
| `natural_key` | func | folder_to_pdf.py:41 | 2 | natural sort key |
| `prompt_folder` | func | folder_to_pdf.py:173 | 1 | input prompt + exit |

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

## UNIQUE STYLES
- Filelist fallback: `build_multipdf_cmd` switches to a `filelist=` temp file when the CLI exceeds 3800 chars. Written in ANSI (`mbcs`) encoding for Chinese-path compat (with a `LookupError` fallback to system default on non-Windows hosts for tests).
- Natural sort implemented via inline regex split (no natsort dep).
- IrfanView located by resolving desktop `.lnk` first (user's install is non-standard: `D:\电脑应用\IrfanView`).

## COMMANDS
```bash
# tests (any platform with Python)
python -m unittest test_folder_to_pdf -v

# syntax check
python -m py_compile folder_to_pdf.py test_folder_to_pdf.py

# manual run (Windows)
# double-click folder_to_pdf.py, drop a folder in, press Enter
```

## NOTES
- Production runs on Windows calling the IrfanView exe; the WSL/Linux host can only compile-check and unit-test (no IrfanView, no `mbcs`, no `winreg`).
- Unit tests import the script via `importlib` from a relative path and run on Linux — keep test logic host-agnostic.
- Blast radius is small (single-file; most functions have 1 caller). Verify `convert_folder` and `build_multipdf_cmd` before editing — they carry the trickiest behavior.
