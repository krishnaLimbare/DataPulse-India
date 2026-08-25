# Security policy

## Reporting
Please open a private security advisory on GitHub rather than a public issue.

## What this project does to stay safe
- **No secrets in the repo.** All credentials come from environment variables
  (`DATAPULSE_*`) or GitHub Actions secrets. `.env` is git-ignored, `.env.example`
  documents the shape. `gitleaks` runs in pre-commit and in CI.
- **Least-privilege CI.** `permissions: contents: read` by default; the daily job
  gets `contents: write` solely to commit `datasets/`.
- **Redaction in logs.** `core/logging.redact()` masks any field whose name looks
  like a credential; run reports contain no request headers.
- **No untrusted code execution.** Scraped content is parsed as data only — never
  `eval`'d, never used to build file paths or shell commands.
- **Dependency hygiene.** Pinned floors in `pyproject.toml`, Dependabot on, and
  `ruff`'s `S` (bandit) rules enforced in CI.
- **Input validation.** Every dataframe passes a declared schema before it is
  written, so a compromised or changed upstream cannot silently reshape the archive.

## Threat model
The realistic risks are upstream sites serving hostile or malformed data, and
leaked API keys. Both are addressed above. This project stores no user data and
exposes no service — the dashboard is static.
