# Migrating from the earlier layout

The organized release removes duplicate Python files from the repository root and moves the application package to `src/tmhi_watchdog/`.

## Safest upgrade

1. Back up your current secret configuration if you have an old host `.env`:

   ```bash
   cp .env ~/tmhi-watchdog.env.backup
   ```

2. Replace the old project folder with the organized release or pull the updated repository.
3. Stop old containers and remove orphans:

   ```bash
   docker compose down --remove-orphans
   docker rm -f tmhi-watchdog tmhi-watchdog-local 2>/dev/null || true
   ```

4. Start the organized release once so it creates `/data/watchdog.env`:

   ```bash
   docker compose up -d --build
   ```

5. Copy any still-needed settings from `~/tmhi-watchdog.env.backup` into the generated `/data/watchdog.env`, then restart:

   ```bash
   docker compose cp tmhi-watchdog:/data/watchdog.env ./watchdog.env
   nano ./watchdog.env
   docker compose cp ./watchdog.env tmhi-watchdog:/data/watchdog.env
   docker compose restart tmhi-watchdog
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
