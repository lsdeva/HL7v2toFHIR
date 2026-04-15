"""Entry point: parse ORU^R01 message, map to FHIR, and POST to HAPI FHIR server."""

import json
import os
import sys
import time

import httpx

from mapper import (
    build_transaction_bundle,
    extract_obr,
    extract_obx_segments,
    extract_pid,
    map_diagnostic_report,
    map_observation,
    map_patient_reference,
    parse_oru_r01,
)
from terminology import lookup_loinc

# Realistic ORU^R01 message with 5 OBX segments covering NM, ST, and CWE value types.
# Patient: John Smith, MRN LAB-67890
# Order: CBC panel with glucose
ORU_R01_MESSAGE = (
    "MSH|^~\\&|LAB_SYSTEM|HOSPITAL_A|FHIR_GW|FHIR_DEST|20260415143000||ORU^R01^ORU_R01|MSG00042|P|2.5.1\r"
    "PID|1||LAB-67890^^^HOSPITAL_A^MR||SMITH^JOHN^A||19780622|M|||789 OAK AVE^^CHICAGO^IL^60601^USA||312-555-0188\r"
    "ORC|RE|ORD-5001|LAB-5001||CM\r"
    "OBR|1|ORD-5001|LAB-5001|CBC^Complete Blood Count^L|||20260415100000|||||||20260415110000||1234567^JONES^SARAH^M^^^MD||||||20260415140000|||F\r"
    "OBX|1|NM|GLU^Glucose^L||95|mg/dL^mg/dL^UCUM|70-100|N|||F|||20260415120000\r"
    "OBX|2|NM|WBC^White Blood Cell Count^L||11.2|10*3/uL^10*3/uL^UCUM|4.5-11.0|H|||F|||20260415120000\r"
    "OBX|3|NM|HGB^Hemoglobin^L||14.1|g/dL^g/dL^UCUM|12.0-17.5|N|||F|||20260415120000\r"
    "OBX|4|ST|INTERP^Interpretation^L||Mild leukocytosis noted. Recommend repeat in 2 weeks.||||||F|||20260415130000\r"
    "OBX|5|CWE|BLOOD_GROUP^ABO/Rh Blood Group^L||O+^O Positive^L||||||F|||20260415120000\r"
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


def print_obx_mapping_detail(obx_segments, observations):
    """Print field-level mapping detail for each OBX → Observation."""
    print("\n" + "=" * 70)
    print("OBX → FHIR Observation Field-Level Mapping Detail")
    print("=" * 70)

    for i, (obx, obs) in enumerate(zip(obx_segments, observations), 1):
        from mapper import _field, _component

        obx2 = _field(obx, 2)
        obx3 = _field(obx, 3)
        obx5 = _field(obx, 5)
        obx6 = _field(obx, 6)
        obx7 = _field(obx, 7)
        obx8 = _field(obx, 8)
        obx11 = _field(obx, 11)
        obx14 = _field(obx, 14)
        local_code = _component(obx3, 0)

        loinc = lookup_loinc(local_code)
        loinc_str = f"{loinc['code']} ({loinc['display']})" if loinc else "** NOT MAPPED **"

        print(f"\n--- OBX-{i} ---")
        print(f"  OBX-2  (Value Type):    {obx2:6s}  →  value type dispatch")
        print(f"  OBX-3  (Code):          {obx3}")
        print(f"         Local code:      {local_code}")
        print(f"         LOINC mapping:   {loinc_str}")
        print(f"  OBX-5  (Value):         {obx5}")

        # Show which value[x] was used
        if "valueQuantity" in obs:
            vq = obs["valueQuantity"]
            print(f"         → valueQuantity: {vq.get('value')} {vq.get('unit', '')}")
        elif "valueString" in obs:
            val = obs["valueString"]
            display = val if len(val) <= 50 else val[:50] + "..."
            print(f"         → valueString:   {display}")
        elif "valueCodeableConcept" in obs:
            vcc = obs["valueCodeableConcept"]
            print(f"         → valueCodeableConcept: {vcc.get('text', '')}")

        if obx6:
            print(f"  OBX-6  (Units):         {obx6}")
        if obx7:
            print(f"  OBX-7  (Ref Range):     {obx7}  →  referenceRange")
        if obx8:
            interp = obs.get("interpretation", [{}])[0].get("coding", [{}])[0]
            print(f"  OBX-8  (Abnormal Flag): {obx8}  →  interpretation: {interp.get('display', '')}")
        print(f"  OBX-11 (Status):        {obx11}  →  Observation.status: {obs['status']}")
        if obx14:
            print(f"  OBX-14 (DateTime):      {obx14}  →  effectiveDateTime: {obs.get('effectiveDateTime', '')}")


def print_summary(patient, observations, diagnostic_report):
    """Print a high-level mapping summary."""
    print("\n" + "=" * 70)
    print("HL7 v2 ORU^R01 → FHIR R4 Mapping Summary")
    print("=" * 70)

    name = patient.get("name", [{}])[0]
    print(f"\nPatient:")
    print(f"  Name:       {name.get('family', '')}, {', '.join(name.get('given', []))}")
    ids = patient.get("identifier", [])
    for ident in ids:
        print(f"  Identifier: {ident.get('value', '')} (system: {ident.get('system', '')})")

    print(f"\nDiagnosticReport:")
    print(f"  Status: {diagnostic_report.get('status', '')}")
    print(f"  Code:   {diagnostic_report.get('code', {}).get('text', '')}")
    print(f"  Date:   {diagnostic_report.get('effectiveDateTime', '')}")
    print(f"  Issued: {diagnostic_report.get('issued', '')}")
    print(f"  Results linked: {len(diagnostic_report.get('result', []))} Observations")

    print(f"\nObservations: {len(observations)} total")
    for i, obs in enumerate(observations, 1):
        code_text = obs.get("code", {}).get("text", "")
        status = obs.get("status", "")
        if "valueQuantity" in obs:
            vq = obs["valueQuantity"]
            val_str = f"{vq.get('value')} {vq.get('unit', '')}"
        elif "valueString" in obs:
            val_str = obs["valueString"][:40]
        elif "valueCodeableConcept" in obs:
            val_str = obs["valueCodeableConcept"].get("text", "")
        else:
            val_str = "(no value)"
        print(f"  {i}. [{status}] {code_text}: {val_str}")
    print()


def main() -> None:
    print("Parsing ORU^R01 HL7 v2 message...")
    msg = parse_oru_r01(ORU_R01_MESSAGE)

    pid = extract_pid(msg)
    obr = extract_obr(msg)
    obx_segments = extract_obx_segments(msg)
    print(f"Extracted PID, OBR, and {len(obx_segments)} OBX segment(s).")

    # Map Patient
    patient_fullurl = "urn:uuid:patient-1"
    patient = map_patient_reference(pid)

    # Map each OBX to an Observation
    observation_fullurls = [f"urn:uuid:observation-{i+1}" for i in range(len(obx_segments))]
    observations = []
    for i, obx in enumerate(obx_segments):
        obs = map_observation(obx, patient_fullurl, i)
        observations.append(obs)

    # Map DiagnosticReport linking all Observations
    diagnostic_report = map_diagnostic_report(obr, patient_fullurl, observation_fullurls)

    # Print detailed OBX-level mapping
    print_obx_mapping_detail(obx_segments, observations)

    # Print high-level summary
    print_summary(patient, observations, diagnostic_report)

    # Build transaction Bundle
    bundle = build_transaction_bundle(
        patient, observations, diagnostic_report,
        patient_fullurl, observation_fullurls,
    )

    print("Transaction Bundle to POST:")
    print(json.dumps(bundle, indent=2))

    # Ensure FHIR server is reachable
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
