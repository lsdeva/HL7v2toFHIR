"""Hardcoded local-code-to-LOINC mapping for lab observations."""

# Maps local OBX-3 codes to LOINC codes and display names.
# In production this would come from a terminology service or concept map.
LOCAL_TO_LOINC: dict[str, dict[str, str]] = {
    "GLU": {
        "code": "2345-7",
        "display": "Glucose [Mass/volume] in Serum or Plasma",
    },
    "WBC": {
        "code": "6690-2",
        "display": "Leukocytes [#/volume] in Blood by Automated count",
    },
    "HGB": {
        "code": "718-7",
        "display": "Hemoglobin [Mass/volume] in Blood",
    },
    "PLT": {
        "code": "777-3",
        "display": "Platelets [#/volume] in Blood by Automated count",
    },
    "INTERP": {
        "code": "18630-4",
        "display": "Hematology studies (set)",
    },
    "BLOOD_GROUP": {
        "code": "882-1",
        "display": "ABO and Rh group [Type] in Blood",
    },
}

LOINC_SYSTEM = "http://loinc.org"


def lookup_loinc(local_code: str) -> dict[str, str] | None:
    """Look up a LOINC code for a local code. Returns None if not mapped."""
    return LOCAL_TO_LOINC.get(local_code.upper())
