# Changelog

## Unreleased

- Add a dedicated fast JD-compilation path with three bounded attempts, a 60-second deadline,
  concise model output, and an explicit editable local-draft fallback.
- Reuse the most recent successful JD result from privacy-conscious local settings without storing
  the original JD text.

## 0.1.0-beta.4

- Deduplicate identical candidate files before extraction and model analysis while preserving every
  original path in the inventory and copied package.
- Classify candidate materials from bounded previews; analyze resumes in full and cap publications
  and supplementary materials before sending text to DeepSeek.
- Disable thinking mode for structured calls, retry empty/malformed JSON, preserve failed candidates
  as review results, and record privacy-safe diagnostics.
- Display the actual configured Worker count, persist runtime settings, and report partially
  successful runs accurately.
- Serialize native PDFium access to prevent intermittent page failures and process crashes while
  retaining parallel DOCX/image extraction and model analysis.

## 0.1.0 - public beta

- Native Windows desktop workflow for directory scanning, dynamic criteria, eight-worker processing,
  evidence review, Excel export, and candidate-package copying.
- Apple Silicon macOS Beta packaging with DMG/APP assets, offline OCR smoke testing, checksums,
  dependency inventory, bundled license texts, and GitHub Release automation.
- Incremental SQLite cache and explicit terminal states for unreadable, encrypted, empty, and
  inventory-only materials.
- Offline PDF/DOCX/image extraction with bundled OCR fallback.
- Security hardening for spreadsheet formula injection, symlink/junction escapes, model evidence
  verification, complete chunked model input, cloud-processing consent, rich-text escaping, and
  document resource limits.
- MIT project license, third-party notices, public CI, and GitHub Release packaging.

The first public binaries are an unsigned beta. Verify the published SHA-256 file before use.
