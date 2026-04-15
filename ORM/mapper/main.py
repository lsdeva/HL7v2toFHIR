"""Entry point: parse ORM^O01 messages, map to FHIR, and POST to HAPI FHIR server.

Demonstrates the lookup-or-create pattern:
  - Order 1: Patient does not exist yet → created, then ServiceRequest posted
  - Order 2: Same patient, different order → Patient found, only ServiceRequest posted
"""

import json
import os

from fhir_client import (
    create_service_request,
    lookup_or_create_patient,
    wait_for_fhir_server,
)
from mapper import (
    extract_obr,
    extract_orc,
    extract_pid,
    map_patient,
    map_service_request,
    parse_orm_o01,
)

# --- Order 1: CBC order for patient MARTINEZ, MARIA (MRN-77001) ---
ORM_ORDER_1 = (
    "MSH|^~\\&|ORDER_ENTRY|HOSPITAL_A|LAB_SYSTEM|HOSPITAL_A|20260415090000||ORM^O01^ORM_O01|MSG-ORD-001|P|2.5.1\r"
    "PID|1||MRN-77001^^^HOSPITAL_A^MR||MARTINEZ^MARIA^L||19920718|F|||456 ELM ST^^AUSTIN^TX^73301^USA||512-555-0142\r"
    "ORC|NW|ORD-3001||||||^^^^^R||20260415090000|||5551234^CHEN^WILLIAM^R^^^MD||||||||HOSPITAL_A^Main Campus\r"
    "OBR|1|ORD-3001||CBC^Complete Blood Count^L|R|||||||||||5551234^CHEN^WILLIAM^R^^^MD|||||||||||^^^^^R|||||||||||FATIGUE^Fatigue^ICD10\r"
)

# --- Order 2: BMP order for the SAME patient (different order, same MRN) ---
ORM_ORDER_2 = (
    "MSH|^~\\&|ORDER_ENTRY|HOSPITAL_A|LAB_SYSTEM|HOSPITAL_A|20260415091500||ORM^O01^ORM_O01|MSG-ORD-002|P|2.5.1\r"
    "PID|1||MRN-77001^^^HOSPITAL_A^MR||MARTINEZ^MARIA^L||19920718|F|||456 ELM ST^^AUSTIN^TX^73301^USA||512-555-0142\r"
    "ORC|NW|ORD-3002||||||^^^^^S||20260415091500|||5551234^CHEN^WILLIAM^R^^^MD|20260415100000|||||||HOSPITAL_A^Main Campus\r"
    "OBR|1|ORD-3002||BMP^Basic Metabolic Panel^L|S|||||||||||5551234^CHEN^WILLIAM^R^^^MD|||||||||||^^^^^S|||||||||||DIABETES^Diabetes screening^ICD10\r"
)

FHIR_SERVER_URL = os.environ.get("FHIR_SERVER_URL", "http://localhost:8080/fhir")


def print_service_request_summary(sr: dict, order_label: str) -> None:
    """Print a human-readable summary of a mapped ServiceRequest."""
    print(f"\n{'=' * 60}")
    print(f"ServiceRequest Summary — {order_label}")
    print(f"{'=' * 60}")
    print(f"  Status:    {sr.get('status', '')}")
    print(f"  Intent:    {sr.get('intent', '')}")
    print(f"  Code:      {sr.get('code', {}).get('text', '')}")
    print(f"  Subject:   {sr.get('subject', {}).get('reference', '')}")

    if sr.get("priority"):
        print(f"  Priority:  {sr['priority']}")
    if sr.get("authoredOn"):
        print(f"  Authored:  {sr['authoredOn']}")
    if sr.get("occurrenceDateTime"):
        print(f"  Scheduled: {sr['occurrenceDateTime']}")

    requester = sr.get("requester", {})
    if requester:
        print(f"  Requester: {requester.get('display', '')} (ID: {requester.get('identifier', {}).get('value', '')})")

    for ident in sr.get("identifier", []):
        ident_type = ident.get("type", {}).get("text", "")
        print(f"  {ident_type}: {ident.get('value', '')}")

    for reason in sr.get("reasonCode", []):
        print(f"  Reason:    {reason.get('text', '')}")

    print()


def process_order(raw_message: str, order_label: str) -> None:
    """Parse an ORM^O01 message, lookup-or-create the patient, and POST the ServiceRequest."""
    print(f"\n{'#' * 60}")
    print(f"# Processing {order_label}")
    print(f"{'#' * 60}")

    print(f"\nParsing ORM^O01 message...")
    msg = parse_orm_o01(raw_message)

    pid = extract_pid(msg)
    orc = extract_orc(msg)
    obr = extract_obr(msg)
    print(f"Extracted PID, ORC, OBR segments.")

    # Step 1: Map patient from PID
    patient = map_patient(pid)

    # Step 2: Lookup-or-create the Patient on the FHIR server
    patient_reference = lookup_or_create_patient(FHIR_SERVER_URL, patient)

    # Step 3: Map ORC + OBR → ServiceRequest, linked to the Patient
    service_request = map_service_request(orc, obr, patient_reference)

    print_service_request_summary(service_request, order_label)

    print("ServiceRequest JSON:")
    print(json.dumps(service_request, indent=2))

    # Step 4: POST ServiceRequest to FHIR server
    print(f"\nPOSTing ServiceRequest to {FHIR_SERVER_URL}/ServiceRequest ...")
    response = create_service_request(FHIR_SERVER_URL, service_request)
    print(f"Server response:")
    print(json.dumps(response, indent=2))


def main() -> None:
    wait_for_fhir_server(FHIR_SERVER_URL)

    # Order 1: Patient does NOT exist yet → will be created
    process_order(ORM_ORDER_1, "Order 1 — CBC (new patient)")

    # Order 2: Same patient, different order → Patient found via lookup
    process_order(ORM_ORDER_2, "Order 2 — BMP (existing patient)")

    print(f"\n{'=' * 60}")
    print("Both orders processed. The lookup-or-create pattern ensured")
    print("the Patient was created once and reused for the second order.")
    print(f"{'=' * 60}")
    print("\nDone.")


if __name__ == "__main__":
    main()
