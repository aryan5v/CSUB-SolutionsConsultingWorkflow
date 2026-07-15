"""Vendor intake backend vertical slice."""

from .repository import InMemoryVendorRepository, VendorRepository
from .service import VendorBackend, VendorBackendError

__all__ = [
    "InMemoryVendorRepository",
    "VendorBackend",
    "VendorBackendError",
    "VendorRepository",
]
