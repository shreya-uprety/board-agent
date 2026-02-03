import requests
import json

BASE_URL = "https://iso-clinic-v3-481780815788.europe-west1.run.app"

print("=" * 60)
print("FULL API TEST - Creating all report types")
print("=" * 60)

# Test 1: Patient Report
print("\n1. POST /api/patient-report")
patient_report = {
    "title": "Patient Summary Report",
    "component": "PatientReport",
    "patientData": {
        "name": "David Miller",
        "mrn": "MRN0001",
        "date_of_birth": "1982-01-21",
        "age": 44,
        "sex": "Male",
        "primaryDiagnosis": "Acute Liver Injury",
        "problem_list": [{"name": "Hepatitis", "status": "active"}],
        "allergies": [],
        "medication_history": [{"name": "Acetaminophen", "dose": "500mg"}],
        "acute_event_summary": "Patient presents with liver injury",
        "diagnosis_acute_event": ["Hepatitis", "Jaundice"],
        "causality": "Probable drug-induced",
        "management_recommendations": ["Rest", "Avoid alcohol"]
    },
    "zone": "patient-report-zone",
    "patientId": "pt-dbdc623a"
}
r = requests.post(f"{BASE_URL}/api/patient-report", json=patient_report, timeout=15)
print(f"   Status: {r.status_code}")
if r.status_code in [200, 201]:
    print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
else:
    print(f"   ❌ FAILED: {r.text[:200]}")

# Test 2: Diagnostic Report
print("\n2. POST /api/diagnostic-report")
diag_report = {
    "title": "DILI Diagnostic Panel",
    "component": "DILIDiagnostic",
    "diagnosticData": {
        "patientInformation": {
            "name": "David Miller",
            "mrn": "MRN0001"
        },
        "pattern": {
            "classification": "Hepatocellular",
            "R_ratio": 4.0,
            "keyLabs": [
                {"label": "ALT", "value": "110.0 U/L", "note": "↑↑"}
            ]
        },
        "causality": {
            "primaryDrug": "Acetaminophen",
            "rucamScore": 7
        }
    },
    "zone": "dili-analysis-zone",
    "patientId": "pt-dbdc623a"
}
r = requests.post(f"{BASE_URL}/api/diagnostic-report", json=diag_report, timeout=15)
print(f"   Status: {r.status_code}")
if r.status_code in [200, 201]:
    print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
else:
    print(f"   ❌ FAILED: {r.text[:200]}")

# Test 3: Legal Compliance Report
print("\n3. POST /api/legal-compliance")
legal_report = {
    "title": "Legal Compliance Report",
    "component": "LegalReport",
    "legalData": {
        "identification_verification": {
            "patient_name": "David Miller",
            "mrn": "MRN0001",
            "date_of_birth": "1982-01-21"
        },
        "adverseEventDocumentation": {
            "events": [{"eventType": "Hepatitis", "severity": "severe"}],
            "totalEvents": 1
        }
    },
    "zone": "medico-legal-report-zone",
    "patientId": "pt-dbdc623a"
}
r = requests.post(f"{BASE_URL}/api/legal-compliance", json=legal_report, timeout=15)
print(f"   Status: {r.status_code}")
if r.status_code in [200, 201]:
    print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
else:
    print(f"   ❌ FAILED: {r.text[:200]}")

# Test 4: Enhanced TODO (without update)
print("\n4. POST /api/enhanced-todo")
todo = {
    "title": "Report Generation Tasks",
    "description": "Generating patient reports",
    "todos": [
        {"id": "task-1", "text": "Compile data", "status": "finished", "agent": "Report Agent"},
        {"id": "task-2", "text": "Generate report", "status": "finished", "agent": "Report Agent"}
    ],
    "patientId": "pt-dbdc623a"
}
r = requests.post(f"{BASE_URL}/api/enhanced-todo", json=todo, timeout=15)
print(f"   Status: {r.status_code}")
if r.status_code in [200, 201]:
    print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
else:
    print(f"   ❌ FAILED: {r.text[:200]}")

print("\n" + "=" * 60)
print("Check board at: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/pt-dbdc623a")
print("=" * 60)
