# Security policy

## Reporting a vulnerability

Please do not publish credentials, bearer tokens, cookies, Wi-Fi passwords, public IP addresses, or a working exploit in a public issue.

For ordinary bugs that do not expose sensitive information, use the GitHub bug-report template with sanitized logs.

For a security-sensitive issue, contact the repository owner privately through the contact method listed on their GitHub profile. Include only the minimum information required to reproduce the issue and redact secrets.

## Deployment guidance

- Keep the service on a trusted LAN.
- Do not expose the API directly to the public internet.
- Use a long, random `API_TOKEN`.
- Keep gateway credentials in `.env` or Docker secrets and never commit them.
- Run one watchdog instance per gateway.
- Test with `DRY_RUN=true` before enabling real reboots.
