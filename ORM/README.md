# ORM^O01 -- General Order to FHIR R4

Maps an HL7 v2 **ORM^O01** (General Order) message to a FHIR R4 **ServiceRequest**, with a **conditional create** pattern that ensures the referenced Patient exists without creating duplicates.

## Quick Start

```bash
cd ORM
docker compose up --build
```

> HAPI FHIR takes ~60-90 seconds on first boot. The mapper waits automatically.

```bash
docker compose down      # tear down
```

## What Happens

The mapper processes **two orders** for the same patient to demonstrate the conditional create pattern:

```
Order 1: CBC for Maria Martinez (MRN-77001)
  |
  +---> PID ---> POST Patient with If-None-Exist header
  |              Result: 201 Created (patient is new)
  |              --> Patient/1000
  |
  +---> ORC + OBR ---> FHIR ServiceRequest
                        - code: Complete Blood Count
                        - priority: routine
                        - requester: Dr. William Chen
                        - subject: Patient/1000
                        --> ServiceRequest/1001

Order 2: BMP for the SAME patient (MRN-77001)
  |
  +---> PID ---> POST Patient with If-None-Exist header
  |              Result: 200 OK (patient already exists)
  |              --> Patient/1000 (reused, no duplicate)
  |
  +---> ORC + OBR ---> FHIR ServiceRequest
                        - code: Basic Metabolic Panel
                        - priority: stat
                        - requester: Dr. William Chen
                        - subject: Patient/1000
                        --> ServiceRequest/1002
```

**Result: 1 Patient, 2 ServiceRequests.** The Patient is created once and reused.

## Verify

After the mapper completes:

```bash
# Patient (should be exactly 1)
curl http://localhost:8080/fhir/Patient?identifier=MRN-77001

# ServiceRequests (should be 2, both linked to the same Patient)
curl http://localhost:8080/fhir/ServiceRequest?subject.identifier=MRN-77001
```

## The Conditional Create Pattern

### The problem

In real-world HL7 v2 integrations, **order messages often arrive before the patient has been registered** in the target FHIR system:

- **ADT and ORM originate from different systems.** Registration sends ADT^A01; order entry sends ORM^O01. There is no guaranteed ordering.
- **Network timing is unpredictable.** Even when ADT is sent first, the ORM may arrive first due to queue prioritization, retries, or different interface paths.
- **Some workflows skip ADT entirely.** Emergency departments, outpatient labs, and pre-admission orders may generate orders before formal registration.
- **Batch vs. real-time mismatch.** ADT feeds may batch hourly while orders flow in real-time.

A naive `GET /Patient?identifier=...` then `POST /Patient` approach has two critical flaws:

1. **Search index lag** -- FHIR servers like HAPI use async search indexing. A Patient created milliseconds ago may not appear in search results, causing duplicates.
2. **Race conditions** -- Two concurrent messages for the same patient can both observe "not found" and both create a Patient.

### The solution: FHIR conditional create

This POC uses the `If-None-Exist` header on a `POST /Patient` request:

```http
POST /Patient
Content-Type: application/fhir+json
If-None-Exist: identifier=urn:oid:HOSPITAL_A|MRN-77001

{ "resourceType": "Patient", "identifier": [...], ... }
```

HAPI evaluates the `If-None-Exist` criteria **at the database level** (not the search index) and **atomically**:

| Matches found | HTTP response | Behavior |
|:---:|:---:|---|
| 0 | `201 Created` | New Patient created and returned |
| 1 | `200 OK` | Existing Patient returned, no duplicate created |
| 2+ | `412 Precondition Failed` | Ambiguous match -- resolve duplicates first |

This eliminates both the search index lag and race condition problems.

### Production considerations

- **Patient matching**: PID-3 MRN is the simplest match key. Production systems may need MPI (Master Patient Index) lookups or multi-identifier matching (MRN + SSN + DOB).
- **Stale demographics**: If the Patient was created from a prior order with minimal PID data, a subsequent message with richer demographics should update the Patient (conditional update or PATCH).
- **Multiple identifier systems**: When a patient has identifiers from multiple facilities, the `If-None-Exist` criteria must match on the correct system.

## Sample HL7 v2 Messages

**Order 1 -- CBC (routine)**
```
MSH|^~\&|ORDER_ENTRY|HOSPITAL_A|LAB_SYSTEM|HOSPITAL_A|20260415090000||ORM^O01^ORM_O01|MSG-ORD-001|P|2.5.1
PID|1||MRN-77001^^^HOSPITAL_A^MR||MARTINEZ^MARIA^L||19920718|F|||456 ELM ST^^AUSTIN^TX^73301^USA||512-555-0142
ORC|NW|ORD-3001||||||^^^^^R||20260415090000|||5551234^CHEN^WILLIAM^R^^^MD
OBR|1|ORD-3001||CBC^Complete Blood Count^L|R|||...|||FATIGUE^Fatigue^ICD10
```

**Order 2 -- BMP (stat, same patient)**
```
MSH|^~\&|ORDER_ENTRY|HOSPITAL_A|LAB_SYSTEM|HOSPITAL_A|20260415091500||ORM^O01^ORM_O01|MSG-ORD-002|P|2.5.1
PID|1||MRN-77001^^^HOSPITAL_A^MR||MARTINEZ^MARIA^L||19920718|F|||...
ORC|NW|ORD-3002||||||^^^^^S||20260415091500|||5551234^CHEN^WILLIAM^R^^^MD|20260415100000
OBR|1|ORD-3002||BMP^Basic Metabolic Panel^L|S|||...|||DIABETES^Diabetes screening^ICD10
```

## Field-by-Field Mapping

### PID --> Patient (for conditional create)

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| PID-3 | Patient Identifier | `Patient.identifier[]` | Component 1 = value, 4 = authority --> system | `MRN-77001` |
| PID-5 | Patient Name | `Patient.name[]` | Component 1 = family, 2 = given | `MARTINEZ, MARIA L` |
| PID-7 | Date of Birth | `Patient.birthDate` | `YYYYMMDD` --> `YYYY-MM-DD` | `1992-07-18` |
| PID-8 | Administrative Sex | `Patient.gender` | `M`/`F` --> `male`/`female` | `female` |

### ORC --> ServiceRequest

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| ORC-1 | Order Control | `ServiceRequest.intent` | `NW` --> `order`, `CA` --> `revoked` | `order` |
| ORC-2 | Placer Order # | `ServiceRequest.identifier[]` | Type = `PLAC` | `ORD-3001` |
| ORC-3 | Filler Order # | `ServiceRequest.identifier[]` | Type = `FILL` | _(assigned by lab)_ |
| ORC-5 | Order Status | `ServiceRequest.status` | `A`/`IP`/`SC` --> `active`, `CM` --> `completed`, `CA` --> `revoked` | `active` |
| ORC-9 | Transaction Date | `ServiceRequest.authoredOn` | `YYYYMMDDHHMMSS` --> ISO 8601 | `2026-04-15T09:00:00` |
| ORC-12 | Ordering Provider | `ServiceRequest.requester` | ID^family^given --> display | `WILLIAM CHEN` |
| ORC-15 | Effective Date | `ServiceRequest.occurrenceDateTime` | `YYYYMMDDHHMMSS` --> ISO 8601 | `2026-04-15T10:00:00` |

### OBR --> ServiceRequest

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| OBR-4 | Universal Service ID | `ServiceRequest.code` | Component 1 = code, 2 = display | `CBC` (Complete Blood Count) |
| OBR-5 | Priority | `ServiceRequest.priority` | `R` --> `routine`, `S` --> `stat`, `A` --> `asap` | `routine` |
| OBR-16 | Ordering Provider | `ServiceRequest.requester` | Fallback if ORC-12 is empty | _(same as ORC-12)_ |
| OBR-31 | Reason for Study | `ServiceRequest.reasonCode` | Code + display text | `Fatigue` (ICD10) |

## Project Structure

```
ORM/
+-- docker-compose.yml         # HAPI FHIR server + mapper service
+-- mapper/
|   +-- Dockerfile             # Python 3.11, hl7, httpx
|   +-- main.py                # Entry point: two-order demo
|   +-- mapper.py              # PID->Patient, ORC+OBR->ServiceRequest
|   +-- fhir_client.py         # Conditional create, FHIR HTTP helpers
+-- README.md
```

## Not Covered

- **Order updates** (ORC-1 = `XO`) and **cancellations** (ORC-1 = `CA`) -- would require conditional update on existing ServiceRequest
- **Order groups** (ORC/OBR repeating pairs) -- multiple orders in a single ORM message
- **Specimen mapping** (SPM segment) --> FHIR Specimen resource
- **Order responses** (ORR^O02) -- acknowledgement back to the placer
- **Pharmacy orders** (RXO/RXE segments) --> MedicationRequest
