# Goal: migrate-pyproject

## Tasks
1. Move this file to `.agents/plans/1_processing/migrate-pyproject.md` before starting work.
2. Modify `pyproject.toml`:
   - Keep `tzdata>=2024.1` but add marker: `"tzdata>=2024.1 ; sys_platform == 'win32'"`
   - Remove `python-dotenv` from the main `dependencies` list.
   - Ensure `[dependency-groups]` exists with `dev` group containing `python-dotenv>=1.0` and `pytest>=8.0`.
3. Follow DRY and KISS.
4. When finished, commit the changes with a semantic commit message (e.g., `chore: update pyproject dependencies`).
