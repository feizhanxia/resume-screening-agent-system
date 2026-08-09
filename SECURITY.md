# Security policy

## Supported versions

Security fixes are provided for the latest GitHub Release. Pre-release builds are for evaluation
and may be unsigned.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or include real resume data, credentials, or private
paths. Use GitHub's private vulnerability reporting feature for this repository. Include a concise
impact description, affected version, reproduction using synthetic data, and suggested mitigation
when available.

API keys exposed in chat, screenshots, logs, or commits must be revoked immediately; deleting the
visible text is not sufficient.

## Product boundaries

- Resume files and model output are untrusted input.
- Cloud analysis requires explicit confirmation and sends redacted extracted text to DeepSeek.
- External school, ranking, publication, and similar facts remain uncertain until independently
  verified.
- Automated screening is decision support and requires human review.

Implementation-specific privacy guidance is maintained in [docs/SECURITY.md](docs/SECURITY.md).
