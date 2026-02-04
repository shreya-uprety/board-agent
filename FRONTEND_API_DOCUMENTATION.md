# Board Agents API Documentation

**Deployed Base URL:** `https://chat-agent-481780815788.europe-west1.run.app`

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Patient Management](#patient-management)
4. [Chat Endpoints](#chat-endpoints)
5. [Report Generation](#report-generation)
6. [Canvas Operations](#canvas-operations)
7. [WebSocket Endpoints](#websocket-endpoints)
8. [Voice API](#voice-api)
9. [Response Format](#response-format)
10. [Error Handling](#error-handling)

---

## Overview

The Board Agents API provides AI-powered clinical assistance with canvas board operations. It supports:
- Real-time chat and voice communication
- Patient report generation
- Board item management (focus, TODO, schedules, lab results)
- Clinical decision support

**API Version:** v2.0.0 (Modular)  
**Board URL:** https://iso-clinic-v3-481780815788.europe-west1.run.app

---

## Authentication

Currently no authentication is required for API access. All requests use:
```
Content-Type: application/json
```

---

## Patient Management

### Get Current Patient

```
GET /patient/current
```

**Response:**
```json
{
  "patient_id": "pt-dbdc623a"
}
```

### Switch Patient

```
POST /patient/switch
```

**Request Body:**
```json
{
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "patient_id": "pt-dbdc623a"
}
```

---

## Chat Endpoints

### Send Chat Message

```
POST /send-chat
```

Processes chat messages and returns AI-generated responses with board operation capabilities.

**Request Body:**
```json
[
  {
    "role": "user",
    "parts": [{"text": "Generate a patient report for David Miller"}],
    "patient_id": "pt-dbdc623a"
  }
]
```

**Response:**
```json
{
  "response": "I'll generate a comprehensive patient report...",
  "status": "success"
}
```

**Features:**
- Natural language understanding
- Board operation execution (focus, TODO, reports)
- Context-aware responses
- 300-second cache for performance

---

## Report Generation

### Generate DILI Diagnosis

```
POST /generate_diagnosis
```

Generates a Drug-Induced Liver Injury (DILI) diagnostic assessment.

**Request Body:**
```json
{
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "done",
  "data": {
    "diagnosis": "...",
    "severity": "moderate",
    "recommendations": ["..."]
  }
}
```

**Workflow:**
- Creates TODO with 3 tasks (Loading data → Generating diagnosis → Posting to board)
- Animates task status updates
- Posts result to board as diagnosis item

### Generate Patient Report

```
POST /generate_report
```

Generates a comprehensive patient summary report.

**Request Body:**
```json
{
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "done",
  "data": {
    "name": "David Miller",
    "mrn": "MRN0001",
    "age_sex": "44-year-old Male",
    "one_sentence_impression": "...",
    "differential_diagnoses": ["..."],
    "clinical_summary": "...",
    "recommendations": ["..."]
  }
}
```

**Workflow:**
- Creates TODO with 3 tasks
- Loads EHR data
- Generates structured report
- Posts to board

### Generate Legal Report

```
POST /generate_legal
```

Generates a legal compliance report.

**Request Body:**
```json
{
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "done",
  "data": {
    "compliance_status": "...",
    "documentation": "...",
    "recommendations": ["..."]
  }
}
```

---

## Canvas Operations

### Focus on Board Item

```
POST /api/canvas/focus
```

Focuses the canvas view on a specific board item.

**Request Body (Option 1 - Direct ID):**
```json
{
  "object_id": "item-1234567890",
  "patient_id": "pt-dbdc623a"
}
```

**Request Body (Option 2 - Query):**
```json
{
  "query": "latest lab results",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "object_id": "item-1234567890",
  "data": {...}
}
```

### Create TODO

```
POST /api/canvas/create-todo
```

Creates a TODO item on the board.

**Request Body:**
```json
{
  "query": "Order comprehensive LFT panel for David Miller",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "item-1770187553787",
    "title": "Clinical Action Items",
    "todoData": {
      "todos": [
        {"text": "Order comprehensive LFT panel", "status": "todo"}
      ]
    }
  }
}
```

**TODO Format Note:**
- API expects `todo_items` array in payload
- Response preserves only `text` and `status` fields
- Task updates use **index-based approach** (0, 1, 2...)

**Update TODO Task:**
```
POST /api/todos/update-status
```

```json
{
  "id": "item-1770187553787",
  "index": 0,
  "status": "executing",
  "patientId": "pt-dbdc623a"
}
```

Status values: `"todo"`, `"executing"`, `"finished"`

### Create Schedule

```
POST /api/canvas/create-schedule
```

Creates a scheduling item with AI-generated structured context.

**Request Body:**
```json
{
  "schedulingContext": "Schedule follow-up for elevated LFTs",
  "context": "Patient has abnormal liver function tests",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "item-1770187567890",
    "schedulingContext": {
      "nextAvailableSlot": "2026-02-10T14:00:00Z",
      "outstandingInvestigations": ["LFT repeat", "Hepatitis panel"],
      "bookingAction": "Schedule within 1 week"
    }
  }
}
```

### Send Notification

```
POST /api/canvas/send-notification
```

Sends a notification to the board.

**Request Body:**
```json
{
  "message": "Lab results critical - immediate review required",
  "type": "urgent",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "item-1770187567891",
    "message": "Lab results critical - immediate review required"
  }
}
```

### Create Lab Results

```
POST /api/canvas/create-lab-results
```

Posts lab results to the board. API sends each lab result individually.

**Request Body:**
```json
{
  "labResults": [
    {
      "name": "ALT",
      "value": 110,
      "unit": "U/L",
      "range": "7-56",
      "status": "high",
      "trend": "increasing"
    },
    {
      "name": "INR",
      "value": 1.2,
      "unit": "",
      "range": "0.8-1.2",
      "status": "normal",
      "trend": "stable"
    }
  ],
  "date": "2026-02-04",
  "source": "Lab Analysis Agent",
  "patient_id": "pt-dbdc623a"
}
```

**Lab Result Format:**
- `parameter`: Lab test name (string)
- `value`: Test value as **string** (e.g., "110")
- `unit`: Unit of measurement (use "-" for dimensionless like INR)
- `status`: "optimal", "warning", or "critical" (auto-mapped from high/low/normal)
- `range`: Object with `{min, max, warningMin, warningMax}`
- `trend`: "stable", "increasing", or "decreasing"

**Response:**
```json
{
  "status": "success",
  "data": {
    "results": [
      {"id": "item-1770187567892", "parameter": "ALT"},
      {"id": "item-1770187567893", "parameter": "INR"}
    ]
  }
}
```

### Send to EASL

```
POST /api/canvas/send-to-easl
```

Sends a clinical question to the EASL guidelines system.

**Request Body:**
```json
{
  "question": "What is the recommended treatment for DILI?",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "answer": "...",
    "guidelines": ["..."]
  }
}
```

### Prepare EASL Query

```
POST /api/canvas/prepare-easl-query
```

Generates context and refines a clinical question for EASL.

**Request Body:**
```json
{
  "question": "Treatment options for elevated liver enzymes",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "refined_question": "...",
    "context": "...",
    "patient_summary": "..."
  }
}
```

### Create Agent Result

```
POST /api/canvas/create-agent-result
```

Posts an agent analysis result to the board.

**Request Body:**
```json
{
  "title": "Clinical Analysis Result",
  "content": "Analysis shows...",
  "agentName": "Diagnostic Agent",
  "patient_id": "pt-dbdc623a"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "id": "item-1770187567894"
  }
}
```

### Get Board Items

```
GET /api/canvas/board-items/{patient_id}
```

Retrieves all board items for a patient.

**Example:**
```
GET /api/canvas/board-items/pt-dbdc623a
```

**Response:**
```json
{
  "status": "success",
  "patient_id": "pt-dbdc623a",
  "count": 26,
  "items": [
    {
      "id": "item-1234567890",
      "type": "lab-results",
      "content": {...}
    }
  ]
}
```

**Performance:**
- 300-second cache TTL
- Memory + file caching
- Returns cached data when available

---

## WebSocket Endpoints

### Chat WebSocket

```
ws://chat-agent-481780815788.europe-west1.run.app/ws/chat/{patient_id}
```

Real-time bidirectional chat with RAG and tool execution.

**Client → Server:**
```json
{
  "type": "message",
  "content": "Generate a patient report"
}
```

**Server → Client:**
```json
{
  "type": "response",
  "content": "I'll generate a comprehensive patient report..."
}
```

### Voice WebSocket (Simple)

```
ws://chat-agent-481780815788.europe-west1.run.app/ws/voice/{patient_id}
```

Real-time voice communication using Gemini Live API.

**Audio Format:** 16-bit PCM, 24kHz sample rate  
**Protocol:** Binary audio frames

---

## Voice API

### Two-Phase Voice Connection

#### Phase 1: Start Voice Session

```
POST /api/voice/start/{patient_id}
```

Initiates background connection to Gemini Live API.

**Response:**
```json
{
  "session_id": "voice-session-abc123",
  "patient_id": "pt-dbdc623a",
  "status": "connecting",
  "poll_url": "/api/voice/status/voice-session-abc123",
  "websocket_url": "/ws/voice-session/voice-session-abc123",
  "message": "Connection started. Poll status endpoint until ready, then connect to WebSocket."
}
```

#### Phase 2: Check Session Status

```
GET /api/voice/status/{session_id}
```

Polls connection status.

**Response (Connecting):**
```json
{
  "status": "connecting",
  "session_id": "voice-session-abc123",
  "elapsed_seconds": 2.5
}
```

**Response (Ready):**
```json
{
  "status": "ready",
  "session_id": "voice-session-abc123",
  "patient_id": "pt-dbdc623a",
  "websocket_url": "/ws/voice-session/voice-session-abc123"
}
```

#### Phase 3: Connect WebSocket

```
ws://chat-agent-481780815788.europe-west1.run.app/ws/voice-session/{session_id}
```

Connects to pre-established voice session.

#### Close Voice Session

```
DELETE /api/voice/session/{session_id}
```

**Response:**
```json
{
  "status": "closed",
  "session_id": "voice-session-abc123"
}
```

---

## Response Format

### Success Response

```json
{
  "status": "success",
  "data": {...}
}
```

### Error Response

```json
{
  "status": "error",
  "message": "Error description",
  "code": 400
}
```

---

## Error Handling

### HTTP Status Codes

- `200` - Success
- `201` - Created
- `400` - Bad Request (missing parameters)
- `404` - Not Found (invalid session/item ID)
- `500` - Internal Server Error
- `503` - Service Unavailable

### Common Errors

**Missing Patient ID:**
```json
{
  "detail": "Missing patient_id"
}
```

**Invalid Session:**
```json
{
  "error": "Session not found"
}
```

**TODO Update Failed:**
```json
{
  "error": "Task with id 'task-xyz' not found"
}
```
**Solution:** Use index-based updates (0, 1, 2) instead of task_id

---

## Integration Examples

### JavaScript Fetch (Chat)

```javascript
const response = await fetch('https://chat-agent-481780815788.europe-west1.run.app/send-chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify([
    {
      role: 'user',
      parts: [{ text: 'Generate a patient report' }],
      patient_id: 'pt-dbdc623a'
    }
  ])
});

const data = await response.json();
console.log(data.response);
```

### JavaScript WebSocket (Chat)

```javascript
const ws = new WebSocket('ws://chat-agent-481780815788.europe-west1.run.app/ws/chat/pt-dbdc623a');

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'message',
    content: 'Generate a patient report'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Response:', data.content);
};
```

### cURL Examples

**Generate Report:**
```bash
curl -X POST https://chat-agent-481780815788.europe-west1.run.app/generate_report \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "pt-dbdc623a"}'
```

**Create Lab Results:**
```bash
curl -X POST https://chat-agent-481780815788.europe-west1.run.app/api/canvas/create-lab-results \
  -H "Content-Type: application/json" \
  -d '{
    "patient_id": "pt-dbdc623a",
    "labResults": [
      {
        "name": "ALT",
        "value": 110,
        "unit": "U/L",
        "range": "7-56",
        "status": "high",
        "trend": "increasing"
      }
    ],
    "date": "2026-02-04"
  }'
```

**Update TODO:**
```bash
curl -X POST https://chat-agent-481780815788.europe-west1.run.app/api/todos/update-status \
  -H "Content-Type: application/json" \
  -d '{
    "id": "item-1770187553787",
    "index": 0,
    "status": "finished",
    "patientId": "pt-dbdc623a"
  }'
```

---

## Notes

1. **Cache Strategy:** 300-second TTL for board items and patient data
2. **TODO Workflow:** Uses index-based task updates (0, 1, 2) - API doesn't preserve custom task IDs
3. **Lab Results:** 
   - Value must be string type
   - Use "-" for dimensionless units (e.g., INR)
   - Range must be object with min/max/warningMin/warningMax
   - Status: optimal/warning/critical
4. **AI Generation:** Schedule and TODO creation use AI for structured data
5. **WebSocket:** Supports both text chat and voice communication
6. **Voice API:** Two-phase connection for faster initial response

---

## Support

For issues or questions about the API:
- Check the `/health` endpoint for service status
- Review error messages in response bodies
- Ensure patient_id is included in all requests

**Health Check:**
```
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "board-agents",
  "port": "8080"
}
```
