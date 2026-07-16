# Contributing

Thanks for helping improve TMHI Gateway Watchdog.

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

Build the container before submitting Docker-related changes:

```bash
docker build -t tmhi-watchdog:test .
```

## Pull requests

- Keep the watchdog safe by default.
- Add or update tests when changing outage detection, reboot limits, cooldowns, authentication, or gateway requests.
- Never include gateway passwords, API tokens, bearer tokens, cookies, Wi-Fi credentials, or unsanitized logs.
- Preserve `DRY_RUN=true` as the example/default first-deployment setting.
- Explain which physical gateway model was tested, when applicable.

## Gateway support

Only add a gateway after its local API behavior is understood and the implementation can fail safely. Undocumented firmware behavior may change without notice.

This project should not include aggressive endpoint fuzzing or features intended to bypass provider or device access controls.
