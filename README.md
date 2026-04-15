# HL7 v2 to FHIR R4 Mapping POCs

A collection of proof-of-concept mappers that convert HL7 v2 messages to FHIR R4 resources using Python. Each POC is self-contained with its own Docker Compose stack, a HAPI FHIR server, and a Python mapper service.

## Message Types

| POC | HL7 v2 Trigger | FHIR R4 Resources | Key Concept |
|-----|---------------|--------------------|--------------------|
| [ADT](ADT/) | ADT^A01 (Admit) | Patient, Encounter | Transaction Bundle |
| [ORU](ORU/) | ORU^R01 (Lab Result) | Patient, Observation (x5), DiagnosticReport | OBX value type dispatch, LOINC terminology mapping |
| [ORM](ORM/) | ORM^O01 (Order) | Patient, ServiceRequest (x2) | Conditional create (lookup-or-create pattern) |

## Quick Start

Each POC runs independently. Pick one and start it:

```bash
cd ADT   # or ORU, or ORM
docker compose up --build
```

> HAPI FHIR takes ~60-90 seconds to start on first boot. The mapper service waits automatically.

To stop and clean up:

```bash
docker compose down
```

> Only one POC can run at a time since they all bind to port 8080.

## Architecture

All three POCs share the same two-service architecture:

```
                    HL7 v2 Message (hardcoded)
                              |
                              v
                   +---------------------+
                   |   Python Mapper     |
                   |   (hl7 + httpx)     |
                   |                     |
                   |  1. Parse message   |
                   |  2. Extract segments|
                   |  3. Map to FHIR R4  |
                   |  4. POST to HAPI    |
                   +---------------------+
                              |
                     HTTP POST (JSON)
                              |
                              v
                   +---------------------+
                   |   HAPI FHIR Server  |
                   |   (hapiproject/hapi)|
                   |                     |
                   |   Port 8080         |
                   |   FHIR R4           |
                   |   H2 in-memory DB   |
                   +---------------------+
```

## HL7 v2 to FHIR Mapping Overview

### What is HL7 v2?

HL7 v2 is the most widely deployed healthcare messaging standard in the world. Messages are pipe-delimited text with a fixed segment structure. Each segment type (MSH, PID, PV1, OBR, OBX, ORC) carries specific clinical or administrative data. Despite being decades old, the majority of hospital interfaces still run on v2.

### What is FHIR R4?

FHIR (Fast Healthcare Interoperability Resources) R4 is the modern RESTful API standard for healthcare data exchange. Resources are JSON objects with well-defined schemas, strong typing, and terminology bindings. R4 is the current normative release.

### Why map between them?

Most healthcare organizations need both: v2 for existing interfaces and FHIR for modern APIs, patient portals, and regulatory requirements (e.g., US Core, USCDI). Mapping v2 messages to FHIR resources is a core integration pattern.

### Common mapping patterns

| HL7 v2 Segment | FHIR R4 Resource | Notes |
|----------------|------------------|-------|
| PID | Patient | Demographics, identifiers, contact info |
| PV1 | Encounter | Visit type, location, attending provider |
| ORC | ServiceRequest | Order control, placer/filler numbers |
| OBR | ServiceRequest / DiagnosticReport | Order detail or report header |
| OBX | Observation | Individual result values |
| NK1 | RelatedPerson | Next of kin (not mapped in these POCs) |
| AL1 | AllergyIntolerance | Allergies (not mapped in these POCs) |
| DG1 | Condition | Diagnoses (not mapped in these POCs) |
| IN1 | Coverage | Insurance (not mapped in these POCs) |

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.11 | Mapper service |
| HL7 parsing | [`hl7`](https://pypi.org/project/hl7/) | Parse pipe-delimited v2 messages |
| HTTP client | [`httpx`](https://pypi.org/project/httpx/) | POST FHIR resources to server |
| FHIR server | [HAPI FHIR](https://hapifhir.io/) (`hapiproject/hapi:latest`) | Validate and persist FHIR R4 resources |
| Container | Docker Compose | Orchestrate services |

## Project Structure

```
HL7v2toFHIR/
|
+-- ADT/                          # Admit/Discharge/Transfer
|   +-- docker-compose.yml
|   +-- mapper/
|   |   +-- Dockerfile
|   |   +-- main.py               # Entry point
|   |   +-- mapper.py             # PID->Patient, PV1->Encounter
|   +-- README.md
|
+-- ORU/                          # Unsolicited Observation Result
|   +-- docker-compose.yml
|   +-- mapper/
|   |   +-- Dockerfile
|   |   +-- main.py               # Entry point
|   |   +-- mapper.py             # OBX->Observation, OBR->DiagnosticReport
|   |   +-- terminology.py        # Local code -> LOINC lookup
|   +-- README.md
|
+-- ORM/                          # General Order
|   +-- docker-compose.yml
|   +-- mapper/
|   |   +-- Dockerfile
|   |   +-- main.py               # Entry point (two-order demo)
|   |   +-- mapper.py             # ORC+OBR->ServiceRequest
|   |   +-- fhir_client.py        # Conditional create, FHIR HTTP helpers
|   +-- README.md
|
+-- README.md                     # This file
```

## Prerequisites

- Docker and Docker Compose
- ~2 GB free RAM (HAPI FHIR runs on JVM)
- Port 8080 available

## Further Reading

- [HL7 v2 Specification](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185) -- Message structure reference
- [FHIR R4 Specification](https://hl7.org/fhir/R4/) -- Resource definitions and API
- [v2-to-FHIR Implementation Guide](https://build.fhir.org/ig/HL7/v2-to-fhir/) -- Official HL7 mapping guidance
- [HAPI FHIR Documentation](https://hapifhir.io/hapi-fhir/docs/) -- Server configuration and API
- [US Core Implementation Guide](https://www.hl7.org/fhir/us/core/) -- US-specific FHIR profiles and terminology requirements
