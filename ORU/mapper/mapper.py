"""Maps parsed HL7 v2 ORU^R01 segments to FHIR R4 resources."""

import hl7

from terminology import LOINC_SYSTEM, lookup_loinc


def parse_oru_r01(raw: str) -> hl7.Message:
    return hl7.parse(raw)


def _field(segment: hl7.Segment, index: int) -> str:
    """Return a field value as a plain string, or empty string if missing."""
    try:
        return str(segment(index)).strip()
    except (IndexError, KeyError):
        return ""


def _component(field_val: str, index: int) -> str:
    """Extract a component from a field value split by '^'."""
    parts = field_val.split("^")
    return parts[index].strip() if index < len(parts) else ""


def extract_pid(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("PID")


def extract_obr(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("OBR")


def extract_obx_segments(msg: hl7.Message) -> list[hl7.Segment]:
    """Extract all OBX segments from the message."""
    segments = []
    for segment in msg:
        if str(segment[0][0]) == "OBX":
            segments.append(segment)
    return segments


def map_patient_reference(pid: hl7.Segment) -> dict:
    """Build a minimal FHIR Patient resource from PID for the Bundle."""
    pid3 = _field(pid, 3)
    pid5 = _field(pid, 5)

    identifier_value = _component(pid3.split("~")[0], 0)
    family = _component(pid5, 0)
    given = _component(pid5, 1)

    return {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": "urn:oid:2.16.840.1.113883.19.5",
                "value": identifier_value,
            }
        ],
        "name": [
            {
                "use": "official",
                "family": family,
                "given": [g for g in [given] if g],
            }
        ],
    }


def map_observation(obx: hl7.Segment, patient_fullurl: str, index: int) -> dict:
    """Map a single OBX segment to a FHIR Observation resource.

    Mapping:
      OBX-2  → value type dispatch (NM, ST, CWE)
      OBX-3  → Observation.code (local code → LOINC via terminology lookup)
      OBX-5  → Observation.value[x] (type depends on OBX-2)
      OBX-6  → Observation.valueQuantity.unit (for NM type)
      OBX-7  → Observation.referenceRange
      OBX-8  → Observation.interpretation
      OBX-11 → Observation.status
      OBX-14 → Observation.effectiveDateTime
    """
    obx2 = _field(obx, 2)   # Value type
    obx3 = _field(obx, 3)   # Observation identifier
    obx5 = _field(obx, 5)   # Observation value
    obx6 = _field(obx, 6)   # Units
    obx7 = _field(obx, 7)   # Reference range
    obx8 = _field(obx, 8)   # Abnormal flags
    obx11 = _field(obx, 11)  # Observation result status
    obx14 = _field(obx, 14)  # Date/time of observation

    # OBX-3: Observation identifier — local_code^text^coding_system
    local_code = _component(obx3, 0)
    local_text = _component(obx3, 1)
    local_system = _component(obx3, 2)

    # Build code with LOINC lookup
    code_coding = []
    loinc = lookup_loinc(local_code)
    if loinc:
        code_coding.append({
            "system": LOINC_SYSTEM,
            "code": loinc["code"],
            "display": loinc["display"],
        })
    # Always include the local code
    code_coding.append({
        "system": f"urn:local:{local_system}" if local_system else "urn:local:L",
        "code": local_code,
        "display": local_text or local_code,
    })

    # OBX-11: Result status → FHIR Observation.status
    status_map = {
        "F": "final",
        "P": "preliminary",
        "C": "corrected",
        "X": "cancelled",
        "I": "registered",
    }
    status = status_map.get(obx11.upper(), "final") if obx11 else "final"

    observation: dict = {
        "resourceType": "Observation",
        "status": status,
        "code": {"coding": code_coding, "text": local_text or local_code},
        "subject": {"reference": patient_fullurl},
    }

    # OBX-5: Value — dispatch by OBX-2 value type
    value_type = obx2.upper() if obx2 else ""

    if value_type == "NM" and obx5:
        # Numeric value
        try:
            numeric_val = float(obx5)
        except ValueError:
            numeric_val = 0.0
        quantity: dict = {"value": numeric_val}

        # OBX-6: Units — code^text^system (UCUM preferred)
        if obx6:
            unit_code = _component(obx6, 0)
            unit_text = _component(obx6, 1) or unit_code
            unit_system = _component(obx6, 2)
            quantity["unit"] = unit_text
            quantity["code"] = unit_code
            quantity["system"] = unit_system if unit_system else "http://unitsofmeasure.org"
        observation["valueQuantity"] = quantity

    elif value_type == "CWE" and obx5:
        # Coded with Exceptions — code^text^system
        cwe_code = _component(obx5, 0)
        cwe_text = _component(obx5, 1)
        cwe_system = _component(obx5, 2)
        observation["valueCodeableConcept"] = {
            "coding": [
                {
                    "system": cwe_system if cwe_system else "urn:local:L",
                    "code": cwe_code,
                    "display": cwe_text or cwe_code,
                }
            ],
            "text": cwe_text or cwe_code,
        }

    elif value_type == "ST" and obx5:
        # String
        observation["valueString"] = obx5

    elif obx5:
        # Fallback: treat as string
        observation["valueString"] = obx5

    # OBX-7: Reference range
    if obx7:
        ref_range: dict = {"text": obx7}
        # Try to parse "low-high" format
        if "-" in obx7:
            parts = obx7.split("-", 1)
            try:
                ref_range["low"] = {"value": float(parts[0])}
                ref_range["high"] = {"value": float(parts[1])}
            except ValueError:
                pass
        observation["referenceRange"] = [ref_range]

    # OBX-8: Abnormal flags → interpretation
    if obx8:
        interp_map = {
            "H": ("H", "High"),
            "L": ("L", "Low"),
            "HH": ("HH", "Critical high"),
            "LL": ("LL", "Critical low"),
            "N": ("N", "Normal"),
            "A": ("A", "Abnormal"),
        }
        code_display = interp_map.get(obx8.upper(), (obx8, obx8))
        observation["interpretation"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": code_display[0],
                        "display": code_display[1],
                    }
                ]
            }
        ]

    # OBX-14: Date/time of observation
    if obx14 and len(obx14) >= 8:
        dt = f"{obx14[:4]}-{obx14[4:6]}-{obx14[6:8]}"
        if len(obx14) >= 12:
            dt += f"T{obx14[8:10]}:{obx14[10:12]}:00"
        observation["effectiveDateTime"] = dt

    return observation


def map_diagnostic_report(
    obr: hl7.Segment,
    patient_fullurl: str,
    observation_fullurls: list[str],
) -> dict:
    """Map OBR segment to a FHIR DiagnosticReport linking all Observations.

    Mapping:
      OBR-4  → DiagnosticReport.code
      OBR-7  → DiagnosticReport.effectiveDateTime
      OBR-22 → DiagnosticReport.issued
      OBR-25 → DiagnosticReport.status
    """
    obr4 = _field(obr, 4)
    obr7 = _field(obr, 7)
    obr22 = _field(obr, 22)
    obr25 = _field(obr, 25)

    # OBR-4: Universal Service Identifier
    code_id = _component(obr4, 0)
    code_text = _component(obr4, 1)

    code_coding = []
    loinc = lookup_loinc(code_id)
    if loinc:
        code_coding.append({
            "system": LOINC_SYSTEM,
            "code": loinc["code"],
            "display": loinc["display"],
        })
    code_coding.append({
        "system": "urn:local:L",
        "code": code_id,
        "display": code_text or code_id,
    })

    # OBR-25: Result status → FHIR DiagnosticReport.status
    status_map = {
        "F": "final",
        "P": "preliminary",
        "C": "corrected",
        "X": "cancelled",
    }
    status = status_map.get(obr25.upper(), "final") if obr25 else "final"

    report: dict = {
        "resourceType": "DiagnosticReport",
        "status": status,
        "code": {"coding": code_coding, "text": code_text or code_id},
        "subject": {"reference": patient_fullurl},
        "result": [{"reference": url} for url in observation_fullurls],
    }

    # OBR-7: Observation date/time
    if obr7 and len(obr7) >= 8:
        dt = f"{obr7[:4]}-{obr7[4:6]}-{obr7[6:8]}"
        if len(obr7) >= 12:
            dt += f"T{obr7[8:10]}:{obr7[10:12]}:00"
        report["effectiveDateTime"] = dt

    # OBR-22: Results report/status change date
    if obr22 and len(obr22) >= 8:
        issued = f"{obr22[:4]}-{obr22[4:6]}-{obr22[6:8]}"
        if len(obr22) >= 12:
            issued += f"T{obr22[8:10]}:{obr22[10:12]}:00"
        report["issued"] = issued

    return report


def build_transaction_bundle(
    patient: dict,
    observations: list[dict],
    diagnostic_report: dict,
    patient_fullurl: str,
    observation_fullurls: list[str],
) -> dict:
    """Wrap Patient, Observations, and DiagnosticReport in a FHIR transaction Bundle."""
    entries = [
        {
            "fullUrl": patient_fullurl,
            "resource": patient,
            "request": {"method": "POST", "url": "Patient"},
        },
    ]

    for obs, fullurl in zip(observations, observation_fullurls):
        entries.append({
            "fullUrl": fullurl,
            "resource": obs,
            "request": {"method": "POST", "url": "Observation"},
        })

    entries.append({
        "fullUrl": "urn:uuid:diagnosticreport-1",
        "resource": diagnostic_report,
        "request": {"method": "POST", "url": "DiagnosticReport"},
    })

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}
