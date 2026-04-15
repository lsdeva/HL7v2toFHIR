"""FHIR server HTTP helpers — lookup-or-create pattern for Patient."""

import time
import sys

import httpx

_client = httpx.Client(timeout=10)


def wait_for_fhir_server(base_url: str, max_retries: int = 30, delay: int = 5) -> None:
    """Poll the FHIR metadata endpoint until it responds."""
    metadata_url = f"{base_url}/metadata"
    for attempt in range(1, max_retries + 1):
        try:
            resp = _client.get(metadata_url)
            if resp.status_code == 200:
                print(f"FHIR server ready after {attempt} attempt(s).")
                return
        except httpx.ConnectError:
            pass
        print(f"Waiting for FHIR server... (attempt {attempt}/{max_retries})")
        time.sleep(delay)
    print("ERROR: FHIR server did not become ready in time.")
    sys.exit(1)


def lookup_or_create_patient(base_url: str, patient: dict) -> str:
    """Create a Patient if one with the same identifier doesn't already exist.

    Uses FHIR conditional create (If-None-Exist header) which checks at the
    database level, bypassing search index lag. HAPI returns:
      - 201 Created  → new patient was created
      - 200 OK       → existing patient was found (no duplicate created)

    Returns the Patient reference string (e.g. "Patient/1000").
    """
    identifier = patient.get("identifier", [{}])[0]
    system = identifier.get("system", "")
    value = identifier.get("value", "")

    print(f"\n[Lookup-or-Create] Conditional create for Patient identifier={value} ...")

    resp = _client.post(
        f"{base_url}/Patient",
        json=patient,
        headers={
            "Content-Type": "application/fhir+json",
            "If-None-Exist": f"identifier={system}|{value}",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    patient_id = body["id"]
    ref = f"Patient/{patient_id}"

    if resp.status_code == 201:
        print(f"  Patient not found — created new: {ref}")
    else:
        print(f"  Patient already exists — reusing: {ref}")

    return ref


def create_service_request(base_url: str, service_request: dict) -> dict:
    """POST a ServiceRequest resource and return the server response body."""
    resp = _client.post(
        f"{base_url}/ServiceRequest",
        json=service_request,
        headers={"Content-Type": "application/fhir+json"},
    )
    resp.raise_for_status()
    body = resp.json()
    print(f"  Created ServiceRequest: ServiceRequest/{body['id']}")
    return body
