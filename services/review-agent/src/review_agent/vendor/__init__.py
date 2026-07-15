"""Vendor evidence-portal capability.

Mint a case-scoped upload link, notify the vendor and committee, run best-effort
official-vendor research, land dropped evidence in a bucket, and compute the gap
against CSUB's deterministic required-evidence set. Every AWS/external boundary
stays behind a small interface with a local fake.
"""
