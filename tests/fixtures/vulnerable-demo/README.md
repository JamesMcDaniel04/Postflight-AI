# vulnerable-demo (intentional)

These files are committed deliberately so the dogfood run of the Postlight
Action against this repo always has findings to report.

- `requirements.txt` pins ancient versions of `requests` and `django` known to
  contain dozens of CVEs. osv-scanner will flag these.
- `private.key` is a fake RSA private key block (the base64 body is the literal
  string `fakekeydatafakekeyda...`, not a real key). gitleaks will flag the
  PEM header pattern regardless of body validity.

Do not "fix" these by upgrading or removing — they exist to keep the demo
verdict stuck on `HOLD`.
