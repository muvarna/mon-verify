from .wos import WOSClient, normalize_wos_record, wos_records_from_payload
from .scopus import ScopusClient, normalize_scopus_abstract, normalize_scopus_entry, scopus_entries_from_payload

__all__ = [
    "WOSClient",
    "ScopusClient",
    "normalize_wos_record",
    "normalize_scopus_entry",
    "normalize_scopus_abstract",
    "wos_records_from_payload",
    "scopus_entries_from_payload",
]
