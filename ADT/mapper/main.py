"""Entry point: parse ADT^A01 message, map to FHIR, and POST to HAPI FHIR server."""

import json
import os
import sys
import time

import httpx

from mapper import (
    build_transaction_bundle,
    extract_pid,
    extract_pv1,
    map_encounter,
    map_patient,
    parse_adt_a01,
)

# Realistic ADT^A01 message — segments separated by \r as required by HL7 v2
ADT_A01_MESSAGE = (
    "MSH|^~\\&|ADT_SYSTEM|HOSPITAL_A|FHIR_GW|FHIR_DEST|20260415120000||ADT^A01^ADT_A01|MSG00001|P|2.5.1\r"
    "EVN|A01|20260415120000\r"
    "PID|1||MRN-12345^^^HOSPITAL_A^MR~555-44-3333^^^SSA^SS||DOE^JANE^M||19850312|F|||123 MAIN ST^^SPRINGFIELD^IL^62704^USA||217-555-0199|||S|||555-44-3333\r"
    "PV1|1|I|WARD4^401^A^^^HOSPITAL_A||||1234567^SMITH^ROBERT^J^^^MD|||MED||||1||VIP|1234567^SMITH^ROBERT^J^^^MD|IP|V0001^^^HOSPITAL_A^VN||||||||||||||||||||||||20260415113000\r"
    "NK1|1|DOE^JOHN|SPO^Spouse|456 MAIN ST^^SPRINGFIELD^IL^62704|(217)555-0100\r"
)

FHIR_SERVER_URL = os.environ.get("FHIR_SERVER_URL", "http://localhost:8080/fhir")


def wait_for_fhir_server(url: str, max_retries: int = 30, delay: int = 5) -> None:
    """Poll the FHIR server metadata endpoint until it responds."""
    metadata_url = f"{url}/metadata"
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


def print_summary(patient: dict, encounter: dict) -> None:
    """Print a human-readable mapping summary."""
    print("\n" + "=" * 60)
    print("HL7 v2 ADT^A01 → FHIR R4 Mapping Summary")
    print("=" * 60)

    name = patient.get("name", [{}])[0]
    print(f"\nPatient:")
    print(f"  Name:       {name.get('family', '')}, {', '.join(name.get('given', []))}")
    print(f"  Gender:     {patient.get('gender', '')}")
    print(f"  Birth Date: {patient.get('birthDate', '')}")
    ids = patient.get("identifier", [])
    for ident in ids:
        print(f"  Identifier: {ident.get('value', '')} (system: {ident.get('system', '')})")
    addrs = patient.get("address", [])
    for addr in addrs:
        print(f"  Address:    {', '.join(addr.get('line', []))}, {addr.get('city', '')}, {addr.get('state', '')} {addr.get('postalCode', '')}")
    telecoms = patient.get("telecom", [])
    for tel in telecoms:
        print(f"  Phone:      {tel.get('value', '')}")

    print(f"\nEncounter:")
    print(f"  Status:     {encounter.get('status', '')}")
    enc_class = encounter.get("class", {})
    print(f"  Class:      {enc_class.get('display', enc_class.get('code', ''))}")
    locs = encounter.get("location", [])
    for loc in locs:
        print(f"  Location:   {loc.get('location', {}).get('display', '')}")
    parts = encounter.get("participant", [])
    for part in parts:
        print(f"  Attending:  {part.get('individual', {}).get('display', '')}")
    period = encounter.get("period", {})
    if period:
        print(f"  Admitted:   {period.get('start', '')}")
    enc_ids = encounter.get("identifier", [])
    for eid in enc_ids:
        print(f"  Visit #:    {eid.get('value', '')}")
    print()


def main() -> None:
    print("Parsing ADT^A01 HL7 v2 message...")
    msg = parse_adt_a01(ADT_A01_MESSAGE)

    pid = extract_pid(msg)
    pv1 = extract_pv1(msg)
    print(f"Extracted PID and PV1 segments.")

    patient = map_patient(pid)
    encounter = map_encounter(pv1, "urn:uuid:patient-1")
    bundle = build_transaction_bundle(patient, encounter)

    print_summary(patient, encounter)

    print("Transaction Bundle to POST:")
    print(json.dumps(bundle, indent=2))

    # Ensure FHIR server is reachable (belt-and-suspenders with docker healthcheck)
    wait_for_fhir_server(FHIR_SERVER_URL)

    print(f"\nPOSTing transaction Bundle to {FHIR_SERVER_URL}...")
    resp = httpx.post(
        FHIR_SERVER_URL,
        json=bundle,
        headers={"Content-Type": "application/fhir+json"},
        timeout=30,
    )

    print(f"Response status: {resp.status_code}")
    try:
        body = resp.json()
        print(json.dumps(body, indent=2))

        if resp.status_code in (200, 201):
            for entry in body.get("entry", []):
                loc = entry.get("response", {}).get("location", "")
                status = entry.get("response", {}).get("status", "")
                print(f"  Created: {loc} (status: {status})")
    except Exception:
        print(resp.text)

    print("\nDone.")


if __name__ == "__main__":
    main()
