# API Endpoints - Modular Server (server-redis.js)

## Overview
This document lists all available endpoints in the modular server architecture (`api/server-redis.js`).

## Core API

### Root & Health
- `GET /api` - Root API endpoint with server info and available endpoints
- `GET /api/health` - Health check endpoint

---

## Server-Sent Events (SSE)

### Real-time Updates
- `GET /api/events` - SSE endpoint for real-time updates (focus events, new items, notifications, etc.)

---

## Board Items Management
**Base Route:** `/api/board-items`

### CRUD Operations
- `GET /api/board-items` - Get all board items
- `GET /api/board-items/patient/:patientId` - Get board items for specific patient
- `GET /api/board-items/:itemId` - Get specific board item by ID (supports `?patientId=` query param)
- `PUT /api/board-items/:id` - Update board item (supports `?patientId=` query param)
- `DELETE /api/board-items/:id` - Delete board item
- `POST /api/board-items/batch-delete` - Delete multiple items at once

---

## Zone Management
**Base Route:** `/api/zone-positions`

### Zone Position Sync
- `GET /api/zone-positions` - Get current zone positions (static + dynamic merged)
- `POST /api/zone-positions` - Sync dynamic zone positions from frontend (global)
- `GET /api/zone-positions/:patientId` - Get zone positions for specific patient
- `POST /api/zone-positions/:patientId` - Sync zone positions for specific patient

---

## Specialized Board Items (Patient-Scoped)

### Todo Items
**Base Route:** `/api/todos`
- `POST /api/todos` - Create TODO board item
- `POST /api/todos/enhanced` - Create enhanced todo with agent delegation
- `POST /api/todos/update-status` - Update task or subtask status

### Agent Results
**Base Route:** `/api/agents`
- `POST /api/agents` - Create agent result item

### Lab Results
**Base Route:** `/api/lab-results`
- `POST /api/lab-results` - Create lab result board item

### EHR Data
**Base Route:** `/api/ehr-data`
- `POST /api/ehr-data` - Create EHR data item in Retrieved Data Zone

### Dashboard Components
**Base Route:** `/api/components`
- `POST /api/components` - Create dashboard component
- `POST /api/components/schedule` - Create scheduling panel item

### Reports
- `POST /api/patient-report` - Create patient report
- `POST /api/diagnostic-report` - Create diagnostic report
- `POST /api/legal-compliance` - Create legal compliance report

### Doctor Notes
**Base Route:** `/api/doctor-notes`
- `POST /api/doctor-notes` - Create doctor's note

### Images
**Base Route:** `/api/images`
- `POST /api/images` - Create image board item (supports base64 or URL)

---

## Canvas Interactions

### Focus & Notifications
**Base Route:** `/api/focus`
- `POST /api/focus` - Focus on specific canvas item (with sub-element support)
- `POST /api/focus/notification` - Show notification to all connected clients

---

## EASL Integration
**Base Route:** `/api/easl`

### EASL Chat Operations
- `POST /api/easl/send` - Send query to EASL iframe via SSE
- `POST /api/easl/response` - Receive complete response from EASL chat app
- `GET /api/easl/history` - Get EASL conversation history (supports `?patientId=` and `?limit=` query params)
- `POST /api/easl/reset` - Reset EASL conversation history

---

## Redis Management
**Base Route:** `/api/redis`

### Redis Operations
- `GET /api/redis/info` - Get Redis connection info and stats
- `POST /api/redis/clear` - Clear all Redis data
- `POST /api/redis/reload-board-items` - Force reload from static file (clears Redis cache)

---

## Selection Management
**Base Route:** `/api/selected-item`

### Item Selection
- `GET /api/selected-item` - Get currently selected/active item (supports `?patientId=` query param)
- `POST /api/selected-item` - Update currently selected item

---

## Cache & Cleanup Operations
**Base Route:** `/api`

### Cleanup Endpoints
- `POST /api/reset-cache` - Force reload data from file
- `DELETE /api/task-zone` - Clear all API items from Task Management Zone
- `DELETE /api/dynamic-items` - Delete all dynamically added items (keeps only static data)

---

## Patient-Specific Board Management
**Base Routes:** `/process` and `/data`

### Patient Board Operations
- `GET /process/:patientId/board` - Get patient-specific board items (raw unpositioned data)
  - Checks Redis cache → External API → Local fallback files
  - Returns raw board items without frontend transformations
  
- `POST /process/:patientId/board` - Save transformed board items with positions
  - Saves frontend-transformed items to Redis
  - TTL: 24 hours
  
- `DELETE /process/:patientId/cache` - Clear Redis cache for specific patient
  - Clears: `board-items:*`, `board-items-raw:*`, `zone-config:*`, `zone-positions:*`
  
- `GET /data/:patientId/zone-config` - Get patient-specific zone configuration
  - Checks Redis → Patient-specific file → Default config

---

## Frontend Routing
- `GET *` - Catch-all route serving React app (must be last)

---

## Summary

**Total Endpoints:** 47 endpoints organized across 19 route modules

### Route Modules:
1. **boardItems.js** - Board item CRUD operations (7 endpoints)
2. **zones.js** - Zone position management (4 endpoints)
3. **todos.js** - Todo creation and status updates (3 endpoints)
4. **agents.js** - Agent result items (1 endpoint)
5. **labResults.js** - Lab result items (1 endpoint)
6. **ehrData.js** - EHR data items (1 endpoint)
7. **components.js** - Dashboard components (2 endpoints)
8. **patientReport.js** - Patient reports (1 endpoint)
9. **diagnosticReport.js** - Diagnostic reports (1 endpoint)
10. **legalCompliance.js** - Legal compliance reports (1 endpoint)
11. **doctorNotes.js** - Doctor's notes (1 endpoint)
12. **images.js** - Image board items (1 endpoint)
13. **focus.js** - Focus and notifications (2 endpoints)
14. **easl.js** - EASL integration (4 endpoints)
15. **redis.js** - Redis management (3 endpoints)
16. **selection.js** - Item selection (2 endpoints)
17. **cleanup.js** - Cache and cleanup (3 endpoints)
18. **patients.js** - Patient-specific boards (4 endpoints)
19. **server-redis.js** - Core routes (3 endpoints: root, health, SSE, catch-all)

### Key Features:
- ✅ Patient-scoped operations (all item creation endpoints support `patientId`)
- ✅ Redis caching with fallback to static files
- ✅ Real-time updates via SSE
- ✅ Zone-based auto-positioning
- ✅ External API integration for patient data
- ✅ Comprehensive cleanup and cache management
- ✅ EASL chat integration with conversation history

---

## Request/Response Examples

### Create a Todo Item
```bash
POST /api/todos
Content-Type: application/json

{
  "title": "Review Lab Results",
  "description": "Check patient's latest blood work",
  "todo_items": ["Review CBC", "Check liver function", "Assess kidney function"],
  "patientId": "PT-12345"
}
```

### Get Patient Board
```bash
GET /process/PT-12345/board
```

### Focus on Item
```bash
POST /api/focus
Content-Type: application/json

{
  "itemId": "item-123456",
  "subElement": "lab-result-section",
  "focusOptions": {
    "zoom": 1.5,
    "highlight": true,
    "duration": 1500
  }
}
```

### Send Notification
```bash
POST /api/focus/notification
Content-Type: application/json

{
  "message": "New lab results available",
  "type": "info"
}
```

---

## Architecture Benefits

### Modular Design
- Each route module handles a specific domain
- Easy to maintain and extend
- Clear separation of concerns

### Shared Services
- `storage.js` - Board item persistence
- `sse.js` - Server-sent events
- `zones.js` - Zone configuration
- `positioning.js` - Item positioning logic
- `redis.js` - Redis connection management

### Patient-Scoped Data
- All endpoints support patient-specific operations
- Automatic uppercase normalization of patient IDs
- Separate Redis caching per patient
- Fallback to global board when patient data unavailable
