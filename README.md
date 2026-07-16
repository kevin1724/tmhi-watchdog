# TMHI Gateway Watchdog

A headless Python/Docker service that watches internet connectivity and asks a
locally reachable T-Mobile Home Internet gateway to reboot after a sustained
WAN outage.

It is designed for the failure mode where devices remain connected to the local
network and can still reach `192.168.12.1`, but the gateway has lost usable
cellular internet service.

## Supported gateway API

Version 0.1 supports the unified `TMI/v1` API used by these HINT Control gateway
families:

- Arcadyan KVD21
- Arcadyan TMOG4AR
- Sagemcom Fast 5688W
- Sercomm TMOG4SE

The Nokia 5G21 uses a different cookie/CGI API and is not enabled in this first
release.

## Safety behavior

The service does **not** reboot after one failed request. It:

1. Runs several independent HTTP connectivity checks.
2. Requires a configurable number of probes to succeed.
3. Requires the outage to remain continuous for a configured period.
4. Confirms the gateway local API is reachable.
5. Logs in locally and sends the reboot command.
6. Enforces post-reboot grace, cooldown, and a 24-hour reboot limit.
7. Persists reboot history in SQLite so restarting the container does not bypass
   the limit.

`DRY_RUN=true` is the default in `.env.example`.

## Start it

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
GATEWAY_PASSWORD=your-gateway-admin-password
API_TOKEN=a-long-random-string
DRY_RUN=true
```

Build and start:

```bash
docker compose up -d --build
docker compose logs -f tmhi-watchdog
```

Open the status API:

```bash
curl http://localhost:8088/api/status
```

Open the built-in dashboard:

```text
http://localhost:8088/
```

## Test before enabling real reboots

Test internet probes:

```bash
docker compose exec tmhi-watchdog python -m app.cli connectivity
```

Test local gateway reachability and authentication:

```bash
curl -X POST \
  -H "X-API-Token: YOUR_API_TOKEN" \
  http://localhost:8088/api/gateway/test
```

While `DRY_RUN=true`, the watchdog will record that it *would* reboot but will
not send the command.

After gateway authentication succeeds, edit `.env`:

```env
DRY_RUN=false
```

Then recreate the container:

```bash
docker compose up -d --force-recreate
```

## Dashboard and API

- `GET /healthz` — process health
- `GET /` — built-in browser dashboard
- `GET /api/status` — current watchdog state and latest probe results
- `GET /api/config` — non-secret effective configuration
- `GET /api/events?limit=100` — persistent event history
- `POST /api/check` — run a check without allowing an automatic reboot
- `POST /api/check/series` — run repeated checks without allowing an automatic reboot
- `POST /api/gateway/test` — test local reachability and login
- `POST /api/reboot` — manually request a reboot

POST endpoints require:

```text
X-API-Token: value-from-API_TOKEN
```

Manual reboot body:

```json
{
  "force": false
}
```

Repeated check body:

```json
{
  "count": 5,
  "interval_seconds": 10
}
```

`count` accepts 1-30. `interval_seconds` accepts 0-300.

`force: true` bypasses the cooldown and 24-hour limit. It still requires the API
token and does not bypass `DRY_RUN`.

## Status phases

Common values are:

- `online`
- `startup_grace`
- `confirming_outage`
- `outage_confirmed`
- `gateway_unreachable`
- `rebooting`
- `post_reboot_grace`
- `reboot_cooldown`
- `reboot_limit_reached`
- `dry_run_reboot`
- `reboot_failed`

## Docker networking

Normal Docker bridge networking can usually reach `192.168.12.1` through the
host's LAN route. If your Docker setup blocks that route, remove `ports:` from
Compose and add:

```yaml
network_mode: host
```

The API will then listen directly on host port `8000`.

Do not add `NET_RAW`; this project intentionally uses HTTP connectivity checks
instead of ICMP ping.

## Credentials and secrets

Passwords and tokens are never intentionally logged or stored in SQLite. The
service also supports Docker secret-style files:

```env
GATEWAY_PASSWORD_FILE=/run/secrets/gateway_password
API_TOKEN_FILE=/run/secrets/api_token
```

When a `_FILE` variable is present, it takes priority over the regular variable.

## Development tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Important limitations

- This cannot recover a gateway whose local Ethernet/Wi-Fi/API has fully frozen.
- Undocumented gateway APIs can change after firmware updates.
- A bad LAN route, DNS outage, or upstream outage can also trigger the policy.
  Tune the threshold and probe list for your environment.
- Run only one application worker; multiple workers would create multiple
  watchdog loops.
- Use only on a gateway you own or are authorized to administer.

This project is unofficial and is not affiliated with T-Mobile.
