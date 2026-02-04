import requests
import json
import asyncio
import sys
sys.path.insert(0, '.')

BASE_URL = "https://iso-clinic-v3-481780815788.europe-west1.run.app"

print("=" * 60)
print("TESTING FIXED API PAYLOADS")
print("=" * 60)

# Load the actual LLM-generated data
print("\n1. Testing Patient Report with LLM data...")
try:
    with open("output/generate_patient_report.json", "r") as f:
        patient_report_llm = json.load(f)
    
    # Transform like create_report does
    patient_data = patient_report_llm.get('props', {}).get('patientData', {})
    api_payload = {
        'title': patient_report_llm.get('title', 'Patient Summary Report'),
        'component': 'PatientReport',
        'patientData': {
            'name': patient_data.get('name', 'Unknown'),
            'mrn': patient_data.get('mrn', 'Unknown'),
            'dateOfBirth': patient_data.get('date_of_birth', ''),
            'age': patient_data.get('age', ''),
            'sex': patient_data.get('sex', ''),
            'primaryDiagnosis': patient_data.get('primaryDiagnosis', ''),
            'problemList': patient_data.get('problem_list', []),
            'allergies': patient_data.get('allergies', []),
            'medicationHistory': patient_data.get('medication_history', []),
            'acuteEventSummary': patient_data.get('acute_event_summary', ''),
            'diagnosisAcuteEvent': patient_data.get('diagnosis_acute_event', []),
            'causality': patient_data.get('causality', ''),
            'managementRecommendations': patient_data.get('management_recommendations', [])
        },
        'zone': "patient-report-zone",
        'patientId': "pt-dbdc623a"
    }
    
    r = requests.post(f"{BASE_URL}/api/patient-report", json=api_payload, timeout=15)
    print(f"   Status: {r.status_code}")
    if r.status_code in [200, 201]:
        print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
    else:
        print(f"   ❌ FAILED: {r.text[:300]}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n2. Testing Diagnostic Report with LLM data + EHR patient info...")
try:
    with open("output/generate_dili_diagnosis.json", "r") as f:
        diag_llm = json.load(f)
    with open("output/ehr_data.json", "r") as f:
        ehr_data = json.load(f)
    
    # Get patient info from EHR
    patient = ehr_data[0].get('patientData', {}).get('patient', {})
    props = diag_llm.get('props', {})
    
    api_payload = {
        'title': diag_llm.get('title', 'DILI Diagnostic Panel'),
        'component': 'DILIDiagnostic',
        'diagnosticData': {
            'patientInformation': {
                'name': patient.get('name', 'Unknown'),
                'mrn': patient.get('identifiers', {}).get('mrn', 'Unknown'),
                'dateOfBirth': patient.get('date_of_birth', ''),
                'age': patient.get('age', ''),
                'sex': patient.get('sex', '')
            },
            'pattern': props.get('pattern', {}),
            'causality': props.get('causality', {}),
            'severity': props.get('severity', {}),
            'management': props.get('management', {})
        },
        'zone': "dili-analysis-zone",
        'patientId': "pt-dbdc623a"
    }
    
    r = requests.post(f"{BASE_URL}/api/diagnostic-report", json=api_payload, timeout=15)
    print(f"   Status: {r.status_code}")
    if r.status_code in [200, 201]:
        print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
    else:
        print(f"   ❌ FAILED: {r.text[:300]}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n3. Testing Legal Report with LLM data...")
try:
    with open("output/generate_legal_report.json", "r") as f:
        legal_llm = json.load(f)
    
    props = legal_llm.get('props', {})
    patient_info = props.get('patientInfo', {})
    
    api_payload = {
        'title': legal_llm.get('title', 'Legal Compliance Report'),
        'component': 'LegalReport',
        'legalData': {
            'identification_verification': {
                'patient_name': patient_info.get('name', 'Unknown'),
                'mrn': patient_info.get('mrn', 'Unknown'),
                'date_of_birth': patient_info.get('dateOfBirth', ''),
                'patient_id': patient_info.get('patientId', '')
            },
            'careEpisode': patient_info.get('careEpisode', {}),
            'adverseEventDocumentation': props.get('adverseEventDocumentation', {}),
            'regulatoryCompliance': props.get('regulatoryCompliance', {}),
            'consentDocumentation': props.get('consentDocumentation', {}),
            'careStandardsCompliance': props.get('careStandardsCompliance', {}),
            'riskManagement': props.get('riskManagement', {}),
            'recommendations': props.get('recommendations', {})
        },
        'zone': "medico-legal-report-zone",
        'patientId': "pt-dbdc623a"
    }
    
    r = requests.post(f"{BASE_URL}/api/legal-compliance", json=api_payload, timeout=15)
    print(f"   Status: {r.status_code}")
    if r.status_code in [200, 201]:
        print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
    else:
        print(f"   ❌ FAILED: {r.text[:300]}")
except Exception as e:
    print(f"   ❌ Error: {e}")

print("\n4. Testing Schedule...")
schedule_payload = {
    'schedulingContext': 'Follow-up appointment for liver function monitoring',
    'patientId': 'pt-dbdc623a'
}
r = requests.post(f"{BASE_URL}/api/schedule", json=schedule_payload, timeout=15)
print(f"   Status: {r.status_code}")
if r.status_code in [200, 201]:
    print(f"   ✅ SUCCESS - ID: {r.json().get('id')}")
else:
    print(f"   ❌ FAILED: {r.text[:300]}")

print("\n" + "=" * 60)
print("Check board at: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/pt-dbdc623a")
print("=" * 60)
