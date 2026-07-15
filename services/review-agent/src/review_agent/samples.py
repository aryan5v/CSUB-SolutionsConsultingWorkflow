"""Synthetic, sanitized sample data for the local slice and the demo.

None of this is institutional data. It exists so the vertical slice runs and
tests are deterministic. Real approved-software rows and cases arrive via the
Box ingestion pipeline and are never committed to Git.
"""

from __future__ import annotations

from .contracts.case import CaseIntake, DataClassification, Requester
from .contracts.software import ApprovedSoftwareRecord
from .ingestion.software_workbook import RowsWorkbookReader

SAMPLE_WORKBOOK_HEADERS = [
    "Product Name",
    "Vendor",
    "Short Name",
    "Audience",
    "Department",
    "Assignment",
    "Support",
    "Location",
    "Licensing",
]

SAMPLE_WORKBOOK_ROWS = [
    {
        "Product Name": "Zoom Workplace",
        "Vendor": "Zoom",
        "Short Name": "Zoom",
        "Audience": "All",
        "Department": "IT",
        "Assignment": "Enterprise",
        "Support": "Vendor",
        "Location": "Cloud",
        "Licensing": "Site",
    },
    {
        "Product Name": "Adobe Acrobat Pro",
        "Vendor": "Adobe",
        "Short Name": "Acrobat",
        "Audience": "Staff",
        "Department": "Various",
        "Assignment": "Named",
        "Support": "Vendor",
        "Location": "Desktop",
        "Licensing": "Named-user",
    },
]


def sample_workbook_reader() -> RowsWorkbookReader:
    return RowsWorkbookReader(SAMPLE_WORKBOOK_HEADERS, list(SAMPLE_WORKBOOK_ROWS))


def sample_records() -> list[ApprovedSoftwareRecord]:
    from .ingestion.software_workbook import normalize_workbook

    return normalize_workbook(
        sample_workbook_reader(), source_id="src:approved-software-export"
    ).records


def _requester() -> Requester:
    return Requester(name="Sample Requester", email="requester@example.edu", department="Library")


def low_risk_case() -> CaseIntake:
    """Benign product, public data, small audience -> low-risk summary path."""
    return CaseIntake(
        product_name="Sticky Notes Widget",
        vendor_name="Widgetworks",
        requester=_requester(),
        use_case="Personal desktop sticky notes for one office.",
        expected_users=5,
        platform=["windows"],
        data_classification=DataClassification.PUBLIC,
        estimated_cost_usd=0.0,
    )


def medium_risk_case() -> CaseIntake:
    """AI feature + SSO -> deterministic MEDIUM route and editable packet."""
    return CaseIntake(
        product_name="TutorAI Assistant",
        vendor_name="TutorAI",
        requester=_requester(),
        use_case="AI tutoring assistant for a pilot course.",
        expected_users=120,
        platform=["web"],
        data_classification=DataClassification.INTERNAL,
        estimated_cost_usd=8_000.0,
        integrations=["Canvas"],
        uses_sso=True,
        uses_ai=True,
        official_domain="tutorai.example.com",
        classroom_or_public_use=True,
    )


def escalation_case() -> CaseIntake:
    """Unknown data classification + disputed cost band -> safe escalation."""
    return CaseIntake(
        product_name="MysteryVault",
        vendor_name="Unknown Vendor",
        requester=_requester(),
        use_case="Stores unspecified institutional data.",
        expected_users=300,
        platform=["web"],
        data_classification=DataClassification.UNKNOWN,
        estimated_cost_usd=30_000.0,  # inside the disputed 25k-50k band
    )
