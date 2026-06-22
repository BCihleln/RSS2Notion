# Goal: migrate-value-injection

## Tasks
1. Move this file to `.agents/plans/1_processing/migrate-value-injection.md` before starting work.
2. Modify `rss2notion/utils/config.py`:
   - Add `subscription_fetch_status: str = "Active"` (maps to `SUBSCRIPTION_FETCH_STATUS` env var, defaults to `"Active"`).
   - Add `subscription_status_update: str = "Active"` (maps to `SUBSCRIPTION_STATUS_UPDATE` env var, defaults to `"Active"`).
3. Modify `rss2notion/notion/subscription.py`:
   - In `get_avaliable_subscriptions`, load `config = Config.from_env()`.
   - Update the `filter` logic: always keep `is_empty: True`, and if `config.subscription_fetch_status` is truthy, append `{"property": SubscriptionFields.STATUS, "select": {"equals": config.subscription_fetch_status}}` to the `or` conditions.
4. Modify `rss2notion/sync.py`:
   - In `fetch_success`, update `update_subscription_status` call to use `status=config.subscription_status_update if config.subscription_status_update else None`.
5. Follow DRY and KISS.
6. When finished, commit the changes with a semantic commit message (e.g., `feat: inject subscription status config via env vars`).
