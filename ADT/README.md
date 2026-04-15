# HL7 v2 ADT^A01 → FHIR R4 Mapper (POC)

Demonstrates parsing an HL7 v2 ADT^A01 (Admit) message and mapping it to FHIR R4 Patient and Encounter resources, then POSTing them as a transaction Bundle to a HAPI FHIR server.

## How to Run

```bash
cd ADT
docker compose up --build
```

The HAPI FHIR server takes ~60-90 seconds to start. The mapper service waits for it automatically.

To tear down:

```bash
docker compose down
```

## What to Expect

1. HAPI FHIR server starts on **port 8080** (accessible at `http://localhost:8080/fhir/metadata`)
2. The mapper service:
   - Parses a hardcoded realistic ADT^A01 message
   - Extracts PID and PV1 segments
   - Maps them to FHIR R4 Patient and Encounter resources
   - Prints a mapping summary and the transaction Bundle JSON
   - POSTs the Bundle to the HAPI FHIR server
   - Prints the server response with created resource IDs

After the run, you can verify the resources:

```bash
curl http://localhost:8080/fhir/Patient?identifier=MRN-12345
curl http://localhost:8080/fhir/Encounter?identifier=V0001
```

## Field-by-Field Mapping Table

### PID → Patient

| HL7 v2 Field | Description          | FHIR R4 Path            | Example Value                   |
|--------------|----------------------|--------------------------|---------------------------------|
| PID-3        | Patient Identifier   | Patient.identifier       | MRN-12345 (system: HOSPITAL_A)  |
| PID-5        | Patient Name         | Patient.name             | DOE, JANE M                     |
| PID-7        | Date of Birth        | Patient.birthDate        | 1985-03-12                      |
| PID-8        | Sex                  | Patient.gender           | female                          |
| PID-11       | Patient Address      | Patient.address          | 123 MAIN ST, SPRINGFIELD, IL    |
| PID-13       | Phone Number – Home  | Patient.telecom          | 217-555-0199                    |

### PV1 → Encounter

| HL7 v2 Field | Description          | FHIR R4 Path                | Example Value                   |
|--------------|----------------------|------------------------------|---------------------------------|
| PV1-2        | Patient Class        | Encounter.class              | IMP (inpatient)                 |
| PV1-3        | Assigned Location    | Encounter.location.display   | WARD4 401 A                     |
| PV1-7        | Attending Doctor     | Encounter.participant        | Robert J Smith, MD              |
| PV1-10       | Hospital Service     | Encounter.serviceType        | MED                             |
| PV1-19       | Visit Number         | Encounter.identifier         | V0001                           |
| PV1-44       | Admit Date/Time      | Encounter.period.start       | 2026-04-15T11:30:00             |

## Project Structure

```
ADT/
├── docker-compose.yml      # HAPI FHIR server + mapper service
├── mapper/
│   ├── Dockerfile          # Python 3.11 with hl7, httpx
│   ├── main.py             # Entry point: parse, map, POST
│   └── mapper.py           # Mapping logic (PID→Patient, PV1→Encounter)
└── README.md
```

## Tech Stack

- **Python 3.11** — mapper runtime
- **hl7** — HL7 v2 message parsing
- **httpx** — HTTP client for FHIR server
- **HAPI FHIR** (hapiproject/hapi:latest) — FHIR R4 server
