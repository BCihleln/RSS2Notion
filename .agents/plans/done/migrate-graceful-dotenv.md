# Goal: migrate-graceful-dotenv

## Tasks
1. Move this file to `.agents/plans/1_processing/migrate-graceful-dotenv.md` before starting work.
2. Modify the following files to load `dotenv` gracefully using a `try-except ImportError` block:
   - `rss2notion/__main__.py`
   - `tests/test_rsshub.py`
   - `tools/get_error_feeds.py`
   - `tools/opml.py`
   If `ImportError` occurs, simply `pass`.
3. Follow DRY and KISS.
4. When finished, commit the changes with a semantic commit message (e.g., `refactor: graceful dotenv loading for production`).
