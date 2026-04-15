# HL7 v2 ORU^R01 → FHIR R4 Mapper (POC)

Demonstrates parsing an HL7 v2 ORU^R01 (Unsolicited Observation Result) message and mapping it to FHIR R4 Observation and DiagnosticReport resources, then POSTing them as a transaction Bundle to a HAPI FHIR server.

## How to Run

```bash
cd ORU
docker compose up --build
```

The HAPI FHIR server takes ~60-90 seconds to start. The mapper service waits for it automatically.

To tear down:

```bash
docker compose down
```

## What to Expect

1. HAPI FHIR server starts on **port 8080**
2. The mapper service:
   - Parses a hardcoded ORU^R01 message containing 5 OBX segments (3 NM, 1 ST, 1 CWE)
   - Maps each OBX to a FHIR Observation (with LOINC code lookup)
   - Creates a DiagnosticReport linking all Observations
   - Prints field-level mapping detail for every OBX → Observation
   - POSTs the transaction Bundle and prints the server response

After the run, verify resources:

```bash
curl http://localhost:8080/fhir/Patient?identifier=LAB-67890
curl http://localhost:8080/fhir/Observation?subject.identifier=LAB-67890
curl http://localhost:8080/fhir/DiagnosticReport?subject.identifier=LAB-67890
```

## Field-by-Field Mapping Table

### PID → Patient (minimal)

| HL7 v2 Field | Description        | FHIR R4 Path       | Example Value      |
|--------------|--------------------|---------------------|--------------------|
| PID-3        | Patient Identifier | Patient.identifier  | LAB-67890          |
| PID-5        | Patient Name       | Patient.name        | SMITH, JOHN A      |

### OBR → DiagnosticReport

| HL7 v2 Field | Description              | FHIR R4 Path                       | Example Value              |
|--------------|--------------------------|-------------------------------------|----------------------------|
| OBR-4        | Universal Service ID     | DiagnosticReport.code               | CBC (Complete Blood Count) |
| OBR-7        | Observation Date/Time    | DiagnosticReport.effectiveDateTime  | 2026-04-15T10:00:00        |
| OBR-22       | Results Report Date      | DiagnosticReport.issued             | 2026-04-15T14:00:00        |
| OBR-25       | Result Status            | DiagnosticReport.status             | final                      |

### OBX → Observation (per segment)

| HL7 v2 Field | Description            | FHIR R4 Path                  | Notes                                      |
|--------------|------------------------|-------------------------------|--------------------------------------------|
| OBX-2        | Value Type             | (dispatch logic)              | NM→valueQuantity, ST→valueString, CWE→valueCodeableConcept |
| OBX-3        | Observation Identifier | Observation.code              | Local code mapped to LOINC via terminology.py |
| OBX-5        | Observation Value      | Observation.value[x]          | Type determined by OBX-2                   |
| OBX-6        | Units                  | valueQuantity.unit/code       | Only for NM type; UCUM preferred           |
| OBX-7        | Reference Range        | Observation.referenceRange    | Parsed as low-high when possible           |
| OBX-8        | Abnormal Flags         | Observation.interpretation    | H→High, L→Low, N→Normal, etc.             |
| OBX-11       | Result Status          | Observation.status            | F→final, P→preliminary, C→corrected        |
| OBX-14       | Date/Time of Obs       | Observation.effectiveDateTime | YYYYMMDDHHMMSS → FHIR dateTime            |

### Sample OBX Segments in This POC

| # | Code        | Type | Value                            | Flag | LOINC   |
|---|-------------|------|----------------------------------|------|---------|
| 1 | GLU         | NM   | 95 mg/dL                         | N    | 2345-7  |
| 2 | WBC         | NM   | 11.2 10*3/uL                     | H    | 6690-2  |
| 3 | HGB         | NM   | 14.1 g/dL                        | N    | 718-7   |
| 4 | INTERP      | ST   | Mild leukocytosis noted...       | —    | 18630-4 |
| 5 | BLOOD_GROUP | CWE  | O+ (O Positive)                  | —    | 882-1   |

## Gotchas

### Repeating OBX Segments

HL7 v2 ORU messages can contain any number of OBX segments under a single OBR. Each OBX becomes a separate FHIR Observation. The `hl7` Python library does not group OBX segments by OBR — this POC iterates all segments with `segment[0][0] == "OBX"` and treats them as a flat list. In multi-OBR messages (e.g., panels with sub-panels), you would need to group OBX segments by their preceding OBR and create a DiagnosticReport per group.

The OBX Set ID (OBX-1) is meant to be a sequential counter within its group, but in practice it is often non-unique or restarted across OBR groups. Do not rely on OBX-1 as a globally unique identifier.

### Value Type Handling (OBX-2)

The OBX-2 field determines how OBX-5 should be interpreted and which FHIR `value[x]` type to use:

| OBX-2 | FHIR value[x]          | Notes |
|-------|------------------------|-------|
| NM    | valueQuantity          | Numeric. OBX-6 provides units (UCUM). Watch for non-numeric "NM" values like `>100` or `<0.01` — this POC will default them to 0.0. Production code should use valueString or comparator. |
| ST    | valueString            | Free text. Can be multi-line in the HL7 message via repetition (~) or escape sequences. |
| CWE   | valueCodeableConcept   | Coded entry. Components: code^display^system. May include alternate coding in components 4-6. |
| CE    | valueCodeableConcept   | Older version of CWE (HL7 v2.3). Same mapping applies. |
| TX    | valueString            | Like ST but for longer text blocks. |
| FT    | valueString            | Formatted text with HL7 escape sequences. Strip formatting for FHIR. |
| SN    | valueQuantity or valueRange | Structured numeric (comparator^value^separator^value2). Needs special parsing. |

This POC handles NM, ST, and CWE. Unrecognized types fall back to valueString.

### Missing LOINC Codes

When a local code has no LOINC mapping in `terminology.py`, the Observation is still created with the local code only. The output marks these as `** NOT MAPPED **` in the field-level detail.

In production:
- Use a terminology server (e.g., FHIR ConceptMap or `$translate` operation) for dynamic lookups
- Log unmapped codes for review by a terminology specialist
- Consider whether an Observation without a standard code is useful downstream — some FHIR consumers will ignore results they can't interpret
- The FHIR spec does not require LOINC, but US Core profiles mandate it for lab results (must-support on code.coding with LOINC system)

## Project Structure

```
ORU/
├── docker-compose.yml       # HAPI FHIR server + mapper service
├── mapper/
│   ├── Dockerfile           # Python 3.11 with hl7, httpx
│   ├── main.py              # Entry point: parse, map, POST
│   ├── mapper.py            # Mapping logic (OBX→Observation, OBR→DiagnosticReport)
│   └── terminology.py       # Local code → LOINC lookup dictionary
└── README.md
```

## Tech Stack

- **Python 3.11** — mapper runtime
- **hl7** — HL7 v2 message parsing
- **httpx** — HTTP client for FHIR server
- **HAPI FHIR** (hapiproject/hapi:latest) — FHIR R4 server
