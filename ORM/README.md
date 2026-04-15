# HL7 v2 ORM^O01 → FHIR R4 ServiceRequest Mapper (POC)

Demonstrates parsing an HL7 v2 ORM^O01 (General Order) message and mapping it to a FHIR R4 ServiceRequest resource, with a lookup-or-create pattern for the Patient.

## How to Run

```bash
cd ORM
docker compose up --build
```

The HAPI FHIR server takes ~60-90 seconds to start. The mapper waits automatically.

To tear down:

```bash
docker compose down
```

## What to Expect

The mapper processes **two orders** for the same patient (MRN-77001, Maria Martinez):

1. **Order 1 — CBC**: Patient does not exist → Patient is **created**, then ServiceRequest is posted
2. **Order 2 — BMP**: Same MRN → Patient is **found** via lookup, only the ServiceRequest is posted

This demonstrates the lookup-or-create pattern in action.

After the run, verify:

```bash
# Patient (should be exactly 1)
curl http://localhost:8080/fhir/Patient?identifier=MRN-77001

# ServiceRequests (should be 2, both linked to the same Patient)
curl http://localhost:8080/fhir/ServiceRequest?subject.identifier=MRN-77001
```

## The Lookup-or-Create Pattern

### Why it matters

In real-world HL7 v2 integrations, **order messages (ORM) often arrive before the patient has been registered** in the target FHIR system. This happens because:

- **ADT and ORM come from different source systems.** The registration system sends ADT^A01 while the order entry system sends ORM^O01. There is no guarantee of ordering between them.
- **Network timing is unpredictable.** Even when ADT is sent first, the ORM message may arrive and be processed before the ADT message due to queue prioritization, retries, or different interface paths.
- **Some workflows skip ADT entirely.** Emergency departments, outpatient labs, and pre-admission orders may generate ORM messages before formal registration.
- **Batch vs. real-time mismatch.** ADT feeds may batch hourly while orders flow in real-time.

### How it works

This POC uses FHIR **conditional create** (`If-None-Exist` header), which is
the recommended approach over a naive search-then-create sequence:

```
1. Extract patient identifier from PID-3
2. POST /Patient with header If-None-Exist: identifier={system}|{value}
3. HAPI checks at the database level (not search index):
   - If no match → creates Patient, returns 201
   - If match found → returns existing Patient, returns 200
4. POST /ServiceRequest with subject → Patient reference
```

**Why conditional create instead of GET-then-POST?**

A naive `GET /Patient?identifier=...` followed by `POST /Patient` has two problems:
- **Search index lag**: FHIR servers like HAPI use async search indexing. A Patient
  created milliseconds ago may not appear in search results yet, causing duplicates.
- **Race conditions**: Two concurrent messages for the same patient can both pass
  the "not found" check and both create a Patient.

Conditional create solves both — HAPI evaluates `If-None-Exist` against the
database directly, not the search index, and does so atomically.

### Edge cases to consider in production

- **Patient matching**: PID-3 MRN is the simplest match key, but production systems may need to match on MPI (Master Patient Index) or use multiple identifiers (MRN + SSN + DOB).
- **Stale data**: If the patient was created from a prior ORM, it may have fewer demographics than the current message. Consider updating the Patient when a richer PID is received.
- **Multiple identifiers**: When `If-None-Exist` matches more than one existing resource, HAPI returns 412 Precondition Failed. Handle this by narrowing the match criteria or resolving duplicates.

## Field-by-Field Mapping Table

### PID → Patient (for lookup-or-create)

| HL7 v2 Field | Description        | FHIR R4 Path       | Example Value     |
|--------------|--------------------|---------------------|-------------------|
| PID-3        | Patient Identifier | Patient.identifier  | MRN-77001         |
| PID-5        | Patient Name       | Patient.name        | MARTINEZ, MARIA L |
| PID-7        | Date of Birth      | Patient.birthDate   | 1992-07-18        |
| PID-8        | Sex                | Patient.gender      | female            |

### ORC → ServiceRequest

| HL7 v2 Field | Description               | FHIR R4 Path                     | Example Value              |
|--------------|---------------------------|-----------------------------------|----------------------------|
| ORC-1        | Order Control             | ServiceRequest.intent             | NW → order                 |
| ORC-2        | Placer Order Number       | ServiceRequest.identifier (PLAC)  | ORD-3001                   |
| ORC-3        | Filler Order Number       | ServiceRequest.identifier (FILL)  | (assigned by lab)          |
| ORC-5        | Order Status              | ServiceRequest.status             | (empty) → active           |
| ORC-9        | Date/Time of Transaction  | ServiceRequest.authoredOn         | 2026-04-15T09:00:00        |
| ORC-12       | Ordering Provider         | ServiceRequest.requester          | William R Chen, MD         |
| ORC-15       | Order Effective Date      | ServiceRequest.occurrenceDateTime | 2026-04-15T10:00:00        |

### OBR → ServiceRequest

| HL7 v2 Field | Description               | FHIR R4 Path                     | Example Value              |
|--------------|---------------------------|-----------------------------------|----------------------------|
| OBR-4        | Universal Service ID      | ServiceRequest.code               | CBC (Complete Blood Count) |
| OBR-5        | Priority                  | ServiceRequest.priority           | R → routine, S → stat      |
| OBR-16       | Ordering Provider         | ServiceRequest.requester          | (fallback if ORC-12 empty) |
| OBR-31       | Reason for Study          | ServiceRequest.reasonCode         | Fatigue (ICD10)            |

## Project Structure

```
ORM/
├── docker-compose.yml       # HAPI FHIR server + mapper service
├── mapper/
│   ├── Dockerfile           # Python 3.11 with hl7, httpx
│   ├── main.py              # Entry point: two-order demo
│   ├── mapper.py            # Mapping logic (PID→Patient, ORC+OBR→ServiceRequest)
│   └── fhir_client.py       # FHIR HTTP helpers (lookup-or-create, POST)
└── README.md
```

## Tech Stack

- **Python 3.11** — mapper runtime
- **hl7** — HL7 v2 message parsing
- **httpx** — HTTP client for FHIR server
- **HAPI FHIR** (hapiproject/hapi:latest) — FHIR R4 server
