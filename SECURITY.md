# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential, or institutional-data incident. Use [GitHub private vulnerability reporting](https://github.com/aryan5v/CSUB-SolutionsConsultingWorkflow/security/advisories/new) and include affected paths, impact, reproduction steps, and any safe supporting evidence.

Do not include live secrets, Box source files, student or employee information, vendor-confidential evidence, or generated review packets in the report. Revoke or rotate exposed credentials through the owning system immediately; a Git history rewrite is not a substitute for rotation.

## Supported versions

This is a short-lived prototype. Only the current `main` branch is supported. It is not approved for production or sensitive institutional workloads.

## Security controls

- Pull requests, teammate review, required CI, dependency review, CodeQL, secret scanning, and push protection.
- SHA-pinned GitHub Actions with read-only default workflow permissions.
- Human approval and deterministic authorization for consequential workflow actions.
- Sanitized or synthetic data only until a separately reviewed data boundary is approved.
- Least-privilege AWS roles, encryption, retention, and teardown requirements documented in the PRD and infrastructure guidance.
