"""Maps parsed HL7 v2 ADT^A01 segments to FHIR R4 resources."""

import hl7


def parse_adt_a01(raw: str) -> hl7.Message:
    return hl7.parse(raw)


def extract_pid(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("PID")


def extract_pv1(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("PV1")


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


def map_patient(pid: hl7.Segment) -> dict:
    """PID segment → FHIR Patient resource.

    Mapping:
      PID-3  → Patient.identifier
      PID-5  → Patient.name (family^given)
      PID-7  → Patient.birthDate
      PID-8  → Patient.gender
      PID-11 → Patient.address
      PID-13 → Patient.telecom (phone)
    """
    pid3 = _field(pid, 3)
    pid5 = _field(pid, 5)
    pid7 = _field(pid, 7)
    pid8 = _field(pid, 8)
    pid11 = _field(pid, 11)
    pid13 = _field(pid, 13)

    # PID-3: Patient ID — take first repetition, first component
    identifier_value = _component(pid3.split("~")[0], 0)
    identifier_system = _component(pid3.split("~")[0], 3) or "urn:oid:2.16.840.1.113883.19.5"

    # PID-5: Patient name — family^given^middle
    family = _component(pid5, 0)
    given = _component(pid5, 1)

    # PID-7: Date of birth — HL7 format YYYYMMDD → FHIR YYYY-MM-DD
    birth_date = None
    if len(pid7) >= 8:
        birth_date = f"{pid7[:4]}-{pid7[4:6]}-{pid7[6:8]}"

    # PID-8: Gender — M/F/O/U → male/female/other/unknown
    gender_map = {"M": "male", "F": "female", "O": "other", "U": "unknown"}
    gender = gender_map.get(pid8.upper(), "unknown")

    # PID-11: Address — street^other^city^state^zip^country
    address = {}
    if pid11:
        addr_parts = pid11.split("^")
        address = {
            "use": "home",
            "line": [p for p in [_component(pid11, 0), _component(pid11, 1)] if p],
            "city": _component(pid11, 2),
            "state": _component(pid11, 3),
            "postalCode": _component(pid11, 4),
            "country": _component(pid11, 5),
        }
        # Remove empty values
        address = {k: v for k, v in address.items() if v}

    # PID-13: Phone
    phone = _component(pid13, 0) if pid13 else None

    patient = {
        "resourceType": "Patient",
        "identifier": [
            {
                "system": identifier_system,
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
        "gender": gender,
    }

    if birth_date:
        patient["birthDate"] = birth_date
    if address:
        patient["address"] = [address]
    if phone:
        patient["telecom"] = [{"system": "phone", "value": phone, "use": "home"}]

    return patient


def map_encounter(pv1: hl7.Segment, patient_fullurl: str) -> dict:
    """PV1 segment → FHIR Encounter resource.

    Mapping:
      PV1-2  → Encounter.class
      PV1-3  → Encounter.location
      PV1-7  → Encounter.participant (attending doctor)
      PV1-10 → Encounter.serviceType
      PV1-19 → Encounter.identifier (visit number)
      PV1-44 → Encounter.period.start (admit date/time)
    """
    pv1_2 = _field(pv1, 2)
    pv1_3 = _field(pv1, 3)
    pv1_7 = _field(pv1, 7)
    pv1_10 = _field(pv1, 10)
    pv1_19 = _field(pv1, 19)
    pv1_44 = _field(pv1, 44)

    # PV1-2: Patient class — I=inpatient, O=outpatient, E=emergency
    class_map = {
        "I": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
        "O": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
        "E": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "emergency"},
    }
    enc_class = class_map.get(pv1_2.upper(), class_map["I"])

    # PV1-3: Assigned patient location — point of care^room^bed
    location = []
    if pv1_3:
        loc_display = pv1_3.replace("^", " ").strip()
        location = [{"location": {"display": loc_display}, "status": "active"}]

    # PV1-7: Attending doctor — ID^family^given
    participant = []
    if pv1_7:
        doc_family = _component(pv1_7, 1)
        doc_given = _component(pv1_7, 2)
        doc_display = f"{doc_given} {doc_family}".strip() if doc_family else _component(pv1_7, 0)
        participant = [
            {
                "type": [
                    {
                        "coding": [
                            {
                                "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                                "code": "ATND",
                                "display": "attender",
                            }
                        ]
                    }
                ],
                "individual": {"display": doc_display},
            }
        ]

    # PV1-19: Visit number
    identifier = []
    if pv1_19:
        identifier = [{"system": "urn:oid:2.16.840.1.113883.19.5.visit", "value": _component(pv1_19, 0)}]

    # PV1-44: Admit date/time — YYYYMMDDHHMMSS → FHIR instant
    period = {}
    if pv1_44 and len(pv1_44) >= 8:
        dt = f"{pv1_44[:4]}-{pv1_44[4:6]}-{pv1_44[6:8]}"
        if len(pv1_44) >= 12:
            dt += f"T{pv1_44[8:10]}:{pv1_44[10:12]}:00"
        period = {"start": dt}

    encounter = {
        "resourceType": "Encounter",
        "status": "in-progress",
        "class": enc_class,
        "subject": {"reference": patient_fullurl},
    }

    if identifier:
        encounter["identifier"] = identifier
    if location:
        encounter["location"] = location
    if participant:
        encounter["participant"] = participant
    if period:
        encounter["period"] = period
    if pv1_10:
        encounter["serviceType"] = {"coding": [{"display": pv1_10}]}

    return encounter


def build_transaction_bundle(patient: dict, encounter: dict) -> dict:
    """Wrap Patient and Encounter in a FHIR transaction Bundle."""
    patient_fullurl = "urn:uuid:patient-1"

    # Update encounter subject reference to use the fullUrl
    encounter["subject"]["reference"] = patient_fullurl

    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": patient_fullurl,
                "resource": patient,
                "request": {"method": "POST", "url": "Patient"},
            },
            {
                "fullUrl": "urn:uuid:encounter-1",
                "resource": encounter,
                "request": {"method": "POST", "url": "Encounter"},
            },
        ],
    }
