# ORU^R01 -- Lab Results to FHIR R4

Maps an HL7 v2 **ORU^R01** (Unsolicited Observation Result) message to FHIR R4 **Observation** and **DiagnosticReport** resources, posted as a transaction Bundle to a HAPI FHIR server.

## Quick Start

```bash
cd ORU
docker compose up --build
```

> HAPI FHIR takes ~60-90 seconds on first boot. The mapper waits automatically.

```bash
docker compose down      # tear down
```

## What Happens

```
ORU^R01 Message (CBC Panel + Blood Group)
  |
  +---> PID ---> FHIR Patient (minimal: identifier + name)
  |
  +---> OBR ---> FHIR DiagnosticReport
  |                - code: Complete Blood Count
  |                - status: final
  |                - links to all 5 Observations below
  |
  +---> OBX 1 (NM)  ---> Observation: Glucose       95 mg/dL     [Normal]    LOINC 2345-7
  +---> OBX 2 (NM)  ---> Observation: WBC           11.2 10*3/uL [HIGH]      LOINC 6690-2
  +---> OBX 3 (NM)  ---> Observation: Hemoglobin    14.1 g/dL    [Normal]    LOINC 718-7
  +---> OBX 4 (ST)  ---> Observation: Interpretation "Mild leukocytosis..."  LOINC 18630-4
  +---> OBX 5 (CWE) ---> Observation: Blood Group   O Positive               LOINC 882-1

All 7 resources are wrapped in a transaction Bundle and POSTed to HAPI FHIR.
```

The mapper prints field-level mapping detail for every OBX, a summary, the full Bundle JSON, and the server response.

## Verify

After the mapper completes:

```bash
# Patient
curl http://localhost:8080/fhir/Patient?identifier=LAB-67890

# All 5 Observations for this patient
curl http://localhost:8080/fhir/Observation?subject.identifier=LAB-67890

# DiagnosticReport linking the Observations
curl http://localhost:8080/fhir/DiagnosticReport?subject.identifier=LAB-67890
```

## Sample HL7 v2 Message

```
MSH|^~\&|LAB_SYSTEM|HOSPITAL_A|FHIR_GW|FHIR_DEST|20260415143000||ORU^R01^ORU_R01|MSG00042|P|2.5.1
PID|1||LAB-67890^^^HOSPITAL_A^MR||SMITH^JOHN^A||19780622|M|||...
ORC|RE|ORD-5001|LAB-5001||CM
OBR|1|ORD-5001|LAB-5001|CBC^Complete Blood Count^L|R|||...|||F
OBX|1|NM|GLU^Glucose^L||95|mg/dL^mg/dL^UCUM|70-100|N|||F|||20260415120000
OBX|2|NM|WBC^White Blood Cell Count^L||11.2|10*3/uL^10*3/uL^UCUM|4.5-11.0|H|||F|||20260415120000
OBX|3|NM|HGB^Hemoglobin^L||14.1|g/dL^g/dL^UCUM|12.0-17.5|N|||F|||20260415120000
OBX|4|ST|INTERP^Interpretation^L||Mild leukocytosis noted. Recommend repeat in 2 weeks.||||||F|||20260415130000
OBX|5|CWE|BLOOD_GROUP^ABO/Rh Blood Group^L||O+^O Positive^L||||||F|||20260415120000
```

## Field-by-Field Mapping

### OBR --> DiagnosticReport

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| OBR-4 | Universal Service ID | `DiagnosticReport.code` | Local code + LOINC lookup | `CBC` |
| OBR-7 | Observation Date/Time | `DiagnosticReport.effectiveDateTime` | `YYYYMMDDHHMMSS` --> ISO 8601 | `2026-04-15T10:00:00` |
| OBR-22 | Results Report Date | `DiagnosticReport.issued` | `YYYYMMDDHHMMSS` --> ISO 8601 | `2026-04-15T14:00:00` |
| OBR-25 | Result Status | `DiagnosticReport.status` | `F` --> `final`, `P` --> `preliminary` | `final` |

### OBX --> Observation (one per segment)

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| OBX-2 | Value Type | _(dispatch)_ | Determines which `value[x]` to use (see table below) | `NM` |
| OBX-3 | Observation ID | `Observation.code` | Local code --> LOINC via `terminology.py` | `GLU` --> LOINC `2345-7` |
| OBX-5 | Value | `Observation.value[x]` | Type depends on OBX-2 | `95` |
| OBX-6 | Units | `valueQuantity.unit` | UCUM preferred | `mg/dL` |
| OBX-7 | Reference Range | `Observation.referenceRange` | Parse `low-high` into `.low` / `.high` | `70-100` |
| OBX-8 | Abnormal Flag | `Observation.interpretation` | `H` --> High, `L` --> Low, `N` --> Normal | `N` |
| OBX-11 | Result Status | `Observation.status` | `F` --> `final`, `P` --> `preliminary`, `C` --> `corrected` | `final` |
| OBX-14 | Date/Time | `Observation.effectiveDateTime` | `YYYYMMDDHHMMSS` --> ISO 8601 | `2026-04-15T12:00:00` |

### OBX-2 Value Type Dispatch

| OBX-2 | FHIR `value[x]` | Description |
|:---:|---|---|
| **NM** | `valueQuantity` | Numeric result. OBX-6 provides UCUM units. |
| **ST** | `valueString` | Free-text string (e.g., interpretive comments). |
| **CWE** | `valueCodeableConcept` | Coded value with display text (e.g., blood type). |
| CE | `valueCodeableConcept` | Older coded entry (v2.3). Same mapping as CWE. |
| TX | `valueString` | Text block. |
| FT | `valueString` | Formatted text (strip HL7 escape sequences). |
| SN | `valueQuantity` or `valueRange` | Structured numeric with comparator. Needs special parsing. |

This POC implements **NM**, **ST**, and **CWE**. Unrecognized types fall back to `valueString`.

### Terminology Mapping (terminology.py)

Local lab codes are mapped to LOINC using a hardcoded dictionary:

| Local Code | LOINC Code | LOINC Display |
|:---:|:---:|---|
| GLU | 2345-7 | Glucose [Mass/volume] in Serum or Plasma |
| WBC | 6690-2 | Leukocytes [#/volume] in Blood by Automated count |
| HGB | 718-7 | Hemoglobin [Mass/volume] in Blood |
| PLT | 777-3 | Platelets [#/volume] in Blood by Automated count |
| INTERP | 18630-4 | Hematology studies (set) |
| BLOOD_GROUP | 882-1 | ABO and Rh group [Type] in Blood |

Unmapped codes are flagged as `** NOT MAPPED **` in the output. The Observation is still created with the local code only.

## FHIR Output (Transaction Bundle)

| # | Resource | Method | fullUrl |
|---|----------|--------|---------|
| 1 | Patient | POST | `urn:uuid:patient-1` |
| 2 | Observation (Glucose) | POST | `urn:uuid:observation-1` |
| 3 | Observation (WBC) | POST | `urn:uuid:observation-2` |
| 4 | Observation (HGB) | POST | `urn:uuid:observation-3` |
| 5 | Observation (Interp) | POST | `urn:uuid:observation-4` |
| 6 | Observation (Blood Group) | POST | `urn:uuid:observation-5` |
| 7 | DiagnosticReport | POST | `urn:uuid:diagnosticreport-1` |

## Gotchas

### Repeating OBX Segments

HL7 v2 ORU messages can contain any number of OBX segments under a single OBR. Each OBX becomes a separate FHIR Observation. This POC iterates all OBX segments as a flat list. In multi-OBR messages (e.g., panels with sub-panels), you would need to group OBX segments by their preceding OBR and create a DiagnosticReport per group.

The OBX Set ID (OBX-1) is a sequential counter within its group, but in practice it is often non-unique or restarted across OBR groups. Do not rely on it as a globally unique identifier.

### Non-Numeric "NM" Values

Some labs send values like `>100`, `<0.01`, or `TNTC` in OBX-5 with OBX-2 = `NM`. This POC defaults non-parseable NM values to `0.0`. Production code should:

- Parse comparators (`>`, `<`, `>=`, `<=`) into `valueQuantity.comparator`
- Fall back to `valueString` for truly non-numeric values

### Missing LOINC Codes

When a local code has no LOINC mapping, the Observation is created with the local code only. In production:

- Use a terminology server (FHIR `$translate` or ConceptMap) for dynamic lookups
- Log unmapped codes for review by a terminology specialist
- US Core profiles **require** LOINC for lab results (`must-support` on `code.coding` with LOINC system)

## Project Structure

```
ORU/
+-- docker-compose.yml         # HAPI FHIR server + mapper service
+-- mapper/
|   +-- Dockerfile             # Python 3.11, hl7, httpx
|   +-- main.py                # Entry point: parse, map, POST, print detail
|   +-- mapper.py              # OBX->Observation, OBR->DiagnosticReport
|   +-- terminology.py         # Local code -> LOINC lookup dictionary
+-- README.md
```

## Not Covered

- Multi-OBR messages (panel grouping)
- OBX with sub-IDs (OBX-4) for multi-part results
- Micro/culture results (OBX with organism + sensitivity panels)
- Attachment results (OBX-2 = ED, RP for embedded data or reference pointers)
- Result amendments and corrections (ORU with OBX-11 = C and prior references)
