# Goal: migrate-docs-and-actions

## Tasks
1. Move this file to `.agents/plans/1_processing/migrate-docs-and-actions.md` before starting work.
2. Modify `.github/workflows/sync.yml`:
   - Change `uv sync` to `uv sync --no-dev`.
   - Change `uv run python -m rss2notion` to `uv run --no-dev python -m rss2notion`.
3. Modify `AGENTS.md`:
   - Document `uv sync` vs `uv sync --no-dev`.
   - Document the new environment variables (`SUBSCRIPTION_FETCH_STATUS`, `SUBSCRIPTION_STATUS_UPDATE`).
   - Remove the complicated rebase steps from the Feature Commit workflow section, recommending standard main branch / feature branch development.
4. Follow DRY and KISS.
5. When finished, commit the changes with a semantic commit message (e.g., `docs: update CI commands and developer workflow`).
