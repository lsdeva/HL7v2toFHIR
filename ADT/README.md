# ADT^A01 -- Admit Notification to FHIR R4

Maps an HL7 v2 **ADT^A01** (Admit/Visit Notification) message to FHIR R4 **Patient** and **Encounter** resources, posted as a transaction Bundle to a HAPI FHIR server.

## Quick Start

```bash
cd ADT
docker compose up --build
```

> HAPI FHIR takes ~60-90 seconds on first boot. The mapper waits automatically.

```bash
docker compose down      # tear down
```

## What Happens

```
ADT^A01 Message
  |
  +---> PID segment ---> FHIR Patient
  |                        - identifier (MRN-12345)
  |                        - name (DOE, JANE M)
  |                        - birthDate, gender, address, telecom
  |
  +---> PV1 segment ---> FHIR Encounter
                           - class (inpatient)
                           - location (WARD4 401-A)
                           - participant (Dr. Robert Smith)
                           - period.start (admit time)

Both resources are wrapped in a transaction Bundle and POSTed to HAPI FHIR.
```

The mapper prints a human-readable summary, the full Bundle JSON, and the server response with created resource IDs.

## Verify

After the mapper completes:

```bash
# Retrieve the Patient by MRN
curl http://localhost:8080/fhir/Patient?identifier=MRN-12345

# Retrieve the Encounter by visit number
curl http://localhost:8080/fhir/Encounter?identifier=V0001
```

## Sample HL7 v2 Message

```
MSH|^~\&|ADT_SYSTEM|HOSPITAL_A|FHIR_GW|FHIR_DEST|20260415120000||ADT^A01^ADT_A01|MSG00001|P|2.5.1
EVN|A01|20260415120000
PID|1||MRN-12345^^^HOSPITAL_A^MR~555-44-3333^^^SSA^SS||DOE^JANE^M||19850312|F|||123 MAIN ST^^SPRINGFIELD^IL^62704^USA||217-555-0199|||S|||555-44-3333
PV1|1|I|WARD4^401^A^^^HOSPITAL_A||||1234567^SMITH^ROBERT^J^^^MD|||MED||||1||VIP|...|IP|V0001^^^HOSPITAL_A^VN|...|20260415113000
NK1|1|DOE^JOHN|SPO^Spouse|456 MAIN ST^^SPRINGFIELD^IL^62704|(217)555-0100
```

## Field-by-Field Mapping

### PID --> Patient

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| PID-3 | Patient Identifier | `Patient.identifier[]` | First repetition; component 1 = value, component 4 = system | `MRN-12345` (system: `HOSPITAL_A`) |
| PID-5 | Patient Name | `Patient.name[]` | Component 1 = family, 2 = given | `DOE, JANE M` |
| PID-7 | Date of Birth | `Patient.birthDate` | `YYYYMMDD` --> `YYYY-MM-DD` | `1985-03-12` |
| PID-8 | Administrative Sex | `Patient.gender` | `M`/`F`/`O`/`U` --> `male`/`female`/`other`/`unknown` | `female` |
| PID-11 | Address | `Patient.address[]` | Components: street, city, state, zip, country | `123 MAIN ST, SPRINGFIELD, IL 62704` |
| PID-13 | Phone (Home) | `Patient.telecom[]` | Component 1 = value; use = `home` | `217-555-0199` |

### PV1 --> Encounter

| HL7 v2 Field | Name | FHIR R4 Path | Transformation | Example |
|:---:|---|---|---|---|
| PV1-2 | Patient Class | `Encounter.class` | `I` --> `IMP`, `O` --> `AMB`, `E` --> `EMER` (v3-ActCode) | `IMP` (inpatient) |
| PV1-3 | Assigned Location | `Encounter.location[].display` | Components joined: point-of-care, room, bed | `WARD4 401 A` |
| PV1-7 | Attending Doctor | `Encounter.participant[]` | Type = `ATND`; ID^family^given --> display | `Robert J Smith, MD` |
| PV1-10 | Hospital Service | `Encounter.serviceType` | Direct mapping | `MED` |
| PV1-19 | Visit Number | `Encounter.identifier[]` | Component 1 = value | `V0001` |
| PV1-44 | Admit Date/Time | `Encounter.period.start` | `YYYYMMDDHHMMSS` --> `YYYY-MM-DDThh:mm:ss` | `2026-04-15T11:30:00` |

## FHIR Output (Transaction Bundle)

The mapper produces a Bundle of type `transaction` with two entries:

| # | Resource | Method | fullUrl |
|---|----------|--------|---------|
| 1 | Patient | POST | `urn:uuid:patient-1` |
| 2 | Encounter | POST | `urn:uuid:encounter-1` |

The Encounter's `subject.reference` points to `urn:uuid:patient-1`, which HAPI resolves to the server-assigned Patient ID during transaction processing.

## Project Structure

```
ADT/
+-- docker-compose.yml        # HAPI FHIR server + mapper service
+-- mapper/
|   +-- Dockerfile            # Python 3.11, hl7, httpx
|   +-- main.py               # Entry point: parse, map, POST, print summary
|   +-- mapper.py             # PID->Patient, PV1->Encounter, Bundle builder
+-- README.md
```

## Not Covered

This POC focuses on the core PID/PV1 mapping. Production ADT mappers would also handle:

- **NK1** --> RelatedPerson (next of kin)
- **AL1** --> AllergyIntolerance
- **DG1** --> Condition (diagnoses)
- **IN1/IN2** --> Coverage (insurance)
- **GT1** --> Account (guarantor)
- **A02-A60** event types (transfer, discharge, merge, update, etc.)
- Patient merge/link (ADT^A40)
