"""Maps parsed HL7 v2 ORM^O01 segments to FHIR R4 resources."""

import hl7


def parse_orm_o01(raw: str) -> hl7.Message:
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


def extract_orc(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("ORC")


def extract_obr(msg: hl7.Message) -> hl7.Segment:
    return msg.segment("OBR")


def map_patient(pid: hl7.Segment) -> dict:
    """PID segment → minimal FHIR Patient for lookup-or-create.

    Mapping:
      PID-3  → Patient.identifier
      PID-5  → Patient.name
      PID-7  → Patient.birthDate
      PID-8  → Patient.gender
    """
    pid3 = _field(pid, 3)
    pid5 = _field(pid, 5)
    pid7 = _field(pid, 7)
    pid8 = _field(pid, 8)

    identifier_value = _component(pid3.split("~")[0], 0)
    identifier_authority = _component(pid3.split("~")[0], 3)
    identifier_system = f"urn:oid:{identifier_authority}" if identifier_authority else "urn:oid:2.16.840.1.113883.19.5"

    family = _component(pid5, 0)
    given = _component(pid5, 1)

    gender_map = {"M": "male", "F": "female", "O": "other", "U": "unknown"}
    gender = gender_map.get(pid8.upper(), "unknown") if pid8 else "unknown"

    patient: dict = {
        "resourceType": "Patient",
        "identifier": [{"system": identifier_system, "value": identifier_value}],
        "name": [{"use": "official", "family": family, "given": [g for g in [given] if g]}],
        "gender": gender,
    }

    if len(pid7) >= 8:
        patient["birthDate"] = f"{pid7[:4]}-{pid7[4:6]}-{pid7[6:8]}"

    return patient


def map_service_request(orc: hl7.Segment, obr: hl7.Segment, patient_reference: str) -> dict:
    """ORC + OBR segments → FHIR ServiceRequest.

    Mapping:
      ORC-1  → intent (NW=order, CA=revoked, etc.)
      ORC-2  → ServiceRequest.identifier (placer order number)
      ORC-3  → ServiceRequest.identifier (filler order number)
      ORC-5  → ServiceRequest.status
      ORC-7  → ServiceRequest.occurrence (quantity/timing)
      ORC-9  → ServiceRequest.authoredOn
      ORC-12 → ServiceRequest.requester
      ORC-15 → ServiceRequest.occurrenceDateTime (effective date)
      OBR-4  → ServiceRequest.code
      OBR-5  → ServiceRequest.priority
      OBR-16 → ServiceRequest.requester (ordering provider, fallback)
      OBR-31 → ServiceRequest.reasonCode
    """
    # --- ORC fields ---
    orc1 = _field(orc, 1)   # Order control
    orc2 = _field(orc, 2)   # Placer order number
    orc3 = _field(orc, 3)   # Filler order number
    orc5 = _field(orc, 5)   # Order status
    orc9 = _field(orc, 9)   # Date/time of transaction
    orc12 = _field(orc, 12)  # Ordering provider
    orc15 = _field(orc, 15)  # Order effective date/time

    # --- OBR fields ---
    obr4 = _field(obr, 4)   # Universal service identifier
    obr5 = _field(obr, 5)   # Priority
    obr16 = _field(obr, 16)  # Ordering provider (fallback)
    obr31 = _field(obr, 31)  # Reason for study

    # ORC-1: Order control → intent
    intent_map = {
        "NW": "order",       # New order
        "CA": "revoked",     # Cancel
        "XO": "order",       # Change order
        "SC": "order",       # Status change
        "RE": "order",       # Refill
    }
    intent = intent_map.get(orc1.upper(), "order")

    # ORC-5: Order status → ServiceRequest.status
    status_map = {
        "A": "active",       # Accepted
        "CA": "revoked",     # Cancelled
        "CM": "completed",   # Completed
        "DC": "revoked",     # Discontinued
        "HD": "on-hold",     # Hold
        "IP": "active",      # In-progress
        "SC": "active",      # Scheduled
        "": "active",        # Default
    }
    status = status_map.get(orc5.upper(), "active") if orc5 else "active"

    # Identifiers: placer and filler order numbers
    identifiers = []
    if orc2:
        identifiers.append({
            "type": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "PLAC"}],
                "text": "Placer Order Number",
            },
            "system": "urn:oid:2.16.840.1.113883.19.5.placer",
            "value": _component(orc2, 0),
        })
    if orc3:
        identifiers.append({
            "type": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203", "code": "FILL"}],
                "text": "Filler Order Number",
            },
            "system": "urn:oid:2.16.840.1.113883.19.5.filler",
            "value": _component(orc3, 0),
        })

    # OBR-4: Service code
    code_id = _component(obr4, 0)
    code_text = _component(obr4, 1)
    code_system = _component(obr4, 2)
    code: dict = {
        "coding": [{
            "system": f"urn:local:{code_system}" if code_system else "urn:local:L",
            "code": code_id,
            "display": code_text or code_id,
        }],
        "text": code_text or code_id,
    }

    # Requester: ORC-12 preferred, OBR-16 as fallback
    requester_field = orc12 or obr16
    requester = None
    if requester_field:
        req_id = _component(requester_field, 0)
        req_family = _component(requester_field, 1)
        req_given = _component(requester_field, 2)
        display = f"{req_given} {req_family}".strip() if req_family else req_id
        requester = {"display": display, "identifier": {"value": req_id}}

    # ORC-9: Date/time of transaction → authoredOn
    authored_on = None
    if orc9 and len(orc9) >= 8:
        authored_on = f"{orc9[:4]}-{orc9[4:6]}-{orc9[6:8]}"
        if len(orc9) >= 12:
            authored_on += f"T{orc9[8:10]}:{orc9[10:12]}:00"

    # ORC-15: Order effective date → occurrenceDateTime
    occurrence = None
    if orc15 and len(orc15) >= 8:
        occurrence = f"{orc15[:4]}-{orc15[4:6]}-{orc15[6:8]}"
        if len(orc15) >= 12:
            occurrence += f"T{orc15[8:10]}:{orc15[10:12]}:00"

    # OBR-5: Priority
    priority_map = {"S": "stat", "R": "routine", "A": "asap", "T": "routine"}
    priority = priority_map.get(obr5.upper(), "routine") if obr5 else None

    # OBR-31: Reason for study
    reason_code = []
    if obr31:
        reason_id = _component(obr31, 0)
        reason_text = _component(obr31, 1)
        reason_code = [{
            "coding": [{"code": reason_id, "display": reason_text or reason_id}],
            "text": reason_text or reason_id,
        }]

    service_request: dict = {
        "resourceType": "ServiceRequest",
        "status": status,
        "intent": intent,
        "code": code,
        "subject": {"reference": patient_reference},
    }

    if identifiers:
        service_request["identifier"] = identifiers
    if requester:
        service_request["requester"] = requester
    if authored_on:
        service_request["authoredOn"] = authored_on
    if occurrence:
        service_request["occurrenceDateTime"] = occurrence
    if priority:
        service_request["priority"] = priority
    if reason_code:
        service_request["reasonCode"] = reason_code

    return service_request
