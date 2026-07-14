# Cross-service tests

Keep contract, integration, end-to-end, gold-case, adversarial, authorization, retrieval-isolation, workflow-resume, and mock-write-back tests here. Workspace-local unit tests stay next to their owning code.

Tests use sanitized fixtures only. An independent verifier owns cross-service acceptance evidence and must not weaken assertions to accommodate an implementation.
