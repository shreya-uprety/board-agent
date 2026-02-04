# Frontend Issues Report

## Date: February 4, 2026

## Issue Summary

After updating the backend to work with **API v2.0.0 (Modular)**, we have confirmed that all data is being correctly generated and posted to the API. However, the frontend React components are only rendering **partial data**.

---

## 1. Patient Report Component - Missing Data Display

### Problem
The `PatientReport` component is only displaying:
- ✅ Patient name
- ✅ MRN
- ✅ Age/Sex

But **NOT displaying**:
- ❌ Problem List (array of conditions)
- ❌ Medication History (array of medications)
- ❌ Acute Event Summary (text)
- ❌ Causality Assessment (text)
- ❌ Management Recommendations (array)
- ❌ Diagnosis Acute Event (array)

### Data Verification
**Backend is sending complete data** - verified in `output/report_create_payload.json`:

```json
{
  "patientData": {
    "name": "David Miller",
    "mrn": "MRN0001",
    "dateOfBirth": "1982-01-21",
    "age": 44,
    "sex": "Male",
    "problemList": [
      {"name": "Acute Hepatitis", "status": "active"},
      {"name": "Jaundice", "status": "active"},
      {"name": "Fatigue", "status": "active"},
      ...
    ],
    "medicationHistory": [
      {"name": "Acetaminophen", "dose": "500mg"},
      {"name": "Prednisone", "dose": "40mg"}
    ],
    "acuteEventSummary": "David Miller presents with acute liver injury...",
    "causality": "The patient's symptoms began approximately 7 days after...",
    "managementRecommendations": [
      "Strict rest",
      "Avoid alcohol",
      "Avoid acetaminophen",
      ...
    ]
  }
}
```

**API Endpoint**: `POST /api/patient-report`
**Status**: 201 Created (successful)

### Required Frontend Fix
The `PatientReport` React component needs to be updated to render ALL fields from `patientData`:
- `patientData.problemList` - array of {name, status}
- `patientData.medicationHistory` - array of {name, dose}
- `patientData.acuteEventSummary` - string
- `patientData.causality` - string
- `patientData.managementRecommendations` - array of strings
- `patientData.diagnosisAcuteEvent` - array of strings

---

## 2. Diagnostic Report Component - Missing Data Display

### Problem
Similar issue with `DILIDiagnostic` component - only showing basic patient info, not the diagnostic details.

### Data Being Sent
```json
{
  "diagnosticData": {
    "patientInformation": {
      "name": "David Miller",
      "mrn": "MRN0001",
      "dateOfBirth": "1982-01-21",
      "age": 44,
      "sex": "Male"
    },
    "pattern": {...},
    "causality": {...},
    "severity": {...},
    "management": {...}
  }
}
```

**API Endpoint**: `POST /api/diagnostic-report`

### Required Frontend Fix
The `DILIDiagnostic` component needs to render:
- `diagnosticData.pattern` - object with diagnostic pattern information
- `diagnosticData.causality` - object with causality assessment
- `diagnosticData.severity` - object with severity grading
- `diagnosticData.management` - object with management recommendations

---

## 3. Legal Compliance Report - Missing Data Display

### Data Structure
```json
{
  "legalData": {
    "identification_verification": {...},
    "careEpisode": {...},
    "adverseEventDocumentation": {...},
    ...
  }
}
```

**API Endpoint**: `POST /api/legal-compliance`

### Required Frontend Fix
The `LegalCompliance` component needs to render all nested fields from `legalData`.

---

## 4. Schedule Endpoint Missing in API v2.0.0

### Problem
The `/api/schedule` endpoint no longer exists in API v2.0.0.

### Current Status
- ❌ Dedicated schedule endpoint missing
- ✅ Temporary workaround: Using `/api/doctor-notes` with `type: "schedule"`

### Backend Workaround Implemented
Schedules are temporarily being posted as doctor-notes:
```json
{
  "patientId": "pt-xxx",
  "note": "SCHEDULE: <scheduling context>",
  "type": "schedule"
}
```

**API Endpoint**: `POST /api/doctor-notes` (workaround)

### Required API/Frontend Fix
Need one of:
1. **Preferred**: Add dedicated schedule endpoint: `POST /api/schedule` or `POST /api/schedules`
2. **Alternative**: Create a proper Schedule component type that can be posted via `/api/components` or `/api/board-items`

### Expected Schedule Data Structure
```json
{
  "scheduleData": {
    "title": "Appointment Schedule",
    "schedulingContext": "Follow-up appointments and tests",
    "items": [...]
  },
  "patientId": "pt-xxx"
}
```

---

## 5. TODO Update Functionality - API Endpoint Missing

### Problem
The old `/api/enhanced-todo` endpoint and `/api/update-todo-status` no longer exist in API v2.0.0.

### Current Status
- ✅ TODO creation works with new `/api/todos` endpoint
- ❌ TODO status updates don't work (no update endpoint available)

### Backend Changes Made
We updated the TODO creation to use the new format:
```json
{
  "title": "Task Title",
  "todo_items": [
    {"text": "Task 1", "status": "pending"},
    {"text": "Task 2", "status": "pending"}
  ],
  "patientId": "pt-xxx"
}
```

### Required API/Frontend Fix
Need one of:
1. Add a PATCH/PUT endpoint for TODO updates: `PATCH /api/todos/{todoId}`
2. Alternative: Update entire TODO by re-POSTing with updated `todo_items`

**Note**: The backend has temporarily removed TODO animation workflows to avoid errors.

---

## Testing Instructions

### To verify backend is sending correct data:
1. Generate a patient report from the board
2. Check the file: `output/report_create_payload.json`
3. Verify all fields are present with data

### To verify API received the data:
```bash
curl https://iso-clinic-v3-481780815788.europe-west1.run.app/process/pt-dbdc623a/board | jq '.[] | select(.type=="patient-report")'
```

You should see the full `patientData` object with all nested fields.

---

## Summary for Frontend Developer

**The backend is working correctly** - all data is:
1. ✅ Generated by AI models
2. ✅ Properly structured in correct API format
3. ✅ Successfully posted to API endpoints (201 Created)
4. ✅ Stored in the API database

**The issue is in the frontend React components** - they are only accessing/rendering a subset of the data fields available in the response.

**Action Required**: Update the React components to map and display ALL fields from the API response objects:
- `PatientReport` component → render all `patientData` fields
- `DILIDiagnostic` component → render all `diagnosticData` fields  
- `LegalCompliance` component → render all `legalData` fields
- Add TODO update endpoint support

---

## Contact
Backend developer: Agent system working correctly
Frontend developer: Please review and update component rendering logic
