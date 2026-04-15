"""FHIR server HTTP helpers — lookup-or-create pattern for Patient."""

import json
import time
import sys

import httpx


def wait_for_fhir_server(base_url: str, max_retries: int = 30, delay: int = 5) -> None:
    """Poll the FHIR metadata endpoint until it responds."""
    metadata_url = f"{base_url}/metadata"
    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.get(metadata_url, timeout=10)
            if resp.status_code == 200:
                print(f"FHIR server ready after {attempt} attempt(s).")
                return
        except httpx.ConnectError:
            pass
        print(f"Waiting for FHIR server... (attempt {attempt}/{max_retries})")
        time.sleep(delay)
    print("ERROR: FHIR server did not become ready in time.")
    sys.exit(1)


def lookup_patient(base_url: str, identifier_value: str, identifier_system: str) -> str | None:
    """Search for an existing Patient by identifier.

    Returns the Patient resource ID (e.g. "Patient/123") if found, None otherwise.
    """
    # HAPI requires system|value for token search parameters
    search_token = f"{identifier_system}|{identifier_value}"
    resp = httpx.get(
        f"{base_url}/Patient",
        params={"identifier": search_token},
        timeout=10,
    )
    resp.raise_for_status()
    bundle = resp.json()

    entries = bundle.get("entry", [])
    if entries:
        entry = entries[0]
        resource = entry["resource"]
        patient_id = resource["id"]
        ref = f"Patient/{patient_id}"
        print(f"  Found existing patient: {ref} (identifier={identifier_value})")
        return ref

    print(f"  Patient not found for identifier={identifier_value}")
    return None


def create_patient(base_url: str, patient: dict) -> str:
    """POST a Patient resource and return its reference (e.g. "Patient/123").

    Waits briefly for the search index to catch up so subsequent lookups
    for the same identifier will find this patient.
    """
    resp = httpx.post(
        f"{base_url}/Patient",
        json=patient,
        headers={"Content-Type": "application/fhir+json"},
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    patient_id = body["id"]
    ref = f"Patient/{patient_id}"
    print(f"  Created new patient: {ref}")

    # Wait for HAPI's search index to commit the new resource
    identifier = patient.get("identifier", [{}])[0]
    system = identifier.get("system", "")
    value = identifier.get("value", "")
    if value:
        for _ in range(10):
            time.sleep(0.5)
            check = httpx.get(
                f"{base_url}/Patient",
                params={"identifier": f"{system}|{value}"},
                timeout=10,
            )
            if check.json().get("entry"):
                break

    return ref


def lookup_or_create_patient(base_url: str, patient: dict) -> str:
    """Find an existing Patient by identifier, or create one if not found.

    This is the core pattern for order messages: the patient referenced in
    PID may or may not already exist in the FHIR server. We search first,
    then create only if needed.

    Returns the Patient reference string.
    """
    identifier = patient.get("identifier", [{}])[0]
    system = identifier.get("system", "")
    value = identifier.get("value", "")

    print(f"\n[Lookup-or-Create] Searching for Patient identifier={value} ...")
    existing = lookup_patient(base_url, value, system)
    if existing:
        return existing

    print(f"  Creating patient ...")
    return create_patient(base_url, patient)


def create_service_request(base_url: str, service_request: dict) -> dict:
    """POST a ServiceRequest resource and return the server response body."""
    resp = httpx.post(
        f"{base_url}/ServiceRequest",
        json=service_request,
        headers={"Content-Type": "application/fhir+json"},
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    print(f"  Created ServiceRequest: ServiceRequest/{body['id']}")
    return body
