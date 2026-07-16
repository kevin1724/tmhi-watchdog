# Migrating from the earlier layout

The organized release removes duplicate Python files from the repository root and moves the application package to `src/tmhi_watchdog/`.

## Safest upgrade

1. Back up your current secret configuration:

   ```bash
   cp .env ~/tmhi-watchdog.env.backup
   ```

2. Replace the old project folder with the organized release or pull the updated repository.
3. Restore `.env`:

   ```bash
   cp ~/tmhi-watchdog.env.backup .env
   ```

4. Stop old containers and remove orphans:

   ```bash
   docker compose down --remove-orphans
   docker rm -f tmhi-watchdog tmhi-watchdog-local 2>/dev/null || true
   ```

5. Start the organized release:

   ```bash
   docker compose up -d --build
   ```

The default deployment now uses a Docker named volume rather than `./data`. Old event history from a bind-mounted `./data/watchdog.db` is not copied automatically. The watchdog can safely start with a new event database, or advanced users can copy the database into the named volume before starting.

Diagnostic commands changed from:

```bash
python -m app.cli gateway-test
```

to:

```bash
python -m tmhi_watchdog.cli gateway-test
```
