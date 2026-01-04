# Repository Guidelines

## Project Structure & Module Organization

- `SimBriefPyDownloader.py` is the main Tkinter application and the primary place for feature work.
- `simbrief.png` is used as the app icon and should stay alongside the script.
- `build/` and `dist/` are build artifacts (e.g., binary outputs); avoid manual edits.
- `*.spec` files are packaging metadata (e.g., PyInstaller).

## Build, Test, and Development Commands

- `python3 SimBriefPyDownloader.py` launches the app locally.
- If using PyInstaller, keep the spec files up to date; build commands should follow the spec in `SimBriefPyDownloader.spec`.

## Coding Style & Naming Conventions

- Python style is straightforward and manual; keep 4-space indentation.
- Match existing naming: `SimBriefPyDownloader` for classes, `snake_case` for functions, and `UPPER_SNAKE` for constants (e.g., `SIMBRIEF_API_URL`).
- Keep UI text consistent and avoid introducing new localization without agreement.

## Testing Guidelines

- There is no automated test suite currently.
- Manual checks: launch the UI, enter a SimBrief ID, select formats, download a plan, and verify saved files and progress log output.

## Commit & Pull Request Guidelines

- Commit history mixes conventional prefixes (`fix:`, `fet(ui):`) and plain sentences. Prefer short, imperative commits with optional `type(scope):` when possible.
- PRs should include a short description, manual test steps, and screenshots for UI changes.

## Security & Configuration Tips

- User configuration is stored at `~/.simbrief_downloader_config.json`. Do not commit personal IDs or local paths.
