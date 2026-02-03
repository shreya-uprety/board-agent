"""
Gemini Voice Session Manager

Manages background connection to Gemini Live API so users don't have to wait.
Uses a two-phase connection:
1. Start session (returns immediately with session ID)
2. Poll for status or connect when ready

This solves the ~85 second connection delay by doing the connection in background.
"""

import asyncio
import logging
import os
import sys
import time
import uuid
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Apply Windows compatibility fix
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Monkey patch websockets for longer timeout
from contextlib import asynccontextmanager
from websockets.asyncio.client import connect as original_ws_connect

@asynccontextmanager
async def patched_ws_connect(*args, **kwargs):
    if 'open_timeout' not in kwargs:
        kwargs['open_timeout'] = 120
    async with original_ws_connect(*args, **kwargs) as ws:
        yield ws

import google.genai.live
google.genai.live.ws_connect = patched_ws_connect

from google import genai
import canvas_ops

logger = logging.getLogger("voice-session-manager")

MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

def get_voice_tool_declarations():
    """Get the tool declarations for voice mode - same as chat agent"""
    return [
        {
            "name": "get_patient_data",
            "description": """MANDATORY: Call this tool to get patient information. Returns a JSON object with:
- name, age, gender, date_of_birth, mrn (patient demographics)
- current_medications: Array of medication strings with name, dose, indication, start/end dates
- recent_labs: Array of lab results with biomarker name, value, unit, reference range, date, abnormal flag
- risk_events: Array of risk assessments with date, riskScore (0-10), contributing factors
- key_events: Array of clinical events with date, event name, clinical note
- adverse_events: Array of adverse events with event, date, severity, causality
- problem_list: Array of diagnoses and conditions
- allergies: Patient allergies
- clinical_notes: Recent clinical encounter notes
- medical_history: Patient medical history summary

Use this for ANY question about: patient name, age, medications, labs, test results, diagnoses, history, problems, allergies, risk, events.""",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "focus_board_item",
            "description": "Focus on a specific board item (e.g., medication timeline, lab results, encounter notes)",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what to focus on"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "create_task",
            "description": "Create a TODO task for the patient",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Description of the task to create"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "send_to_easl",
            "description": "Send a clinical question to EASL for analysis",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Clinical question to analyze"
                    }
                },
                "required": ["question"]
            }
        },
        {
            "name": "generate_dili_diagnosis",
            "description": "Generate a DILI (Drug-Induced Liver Injury) diagnosis report for the patient. Creates a comprehensive diagnostic assessment including RUCAM score, causality assessment, and recommendations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "generate_patient_report",
            "description": "Generate a comprehensive patient summary report including demographics, medical history, current medications, lab results, and clinical assessment.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "generate_legal_report",
            "description": "Generate a legal compliance report documenting the patient's care, adverse events, and regulatory reporting requirements.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "create_schedule",
            "description": "Create a scheduling panel on the board for patient follow-up appointments",
            "parameters": {
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Description of what scheduling is needed, e.g., 'Follow-up for liver function tests in 2 weeks'"
                    }
                },
                "required": ["context"]
            }
        },
        {
            "name": "send_notification",
            "description": "Send a notification alert to the care team about the patient",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The notification message to send, e.g., 'Critical lab values require immediate review'"
                    }
                },
                "required": ["message"]
            }
        },
        {
            "name": "create_lab_results",
            "description": "Create and display lab results on the patient's board. Use when the user says things like 'add labs', 'create lab results', 'add ALT 110', 'post these lab values'. Creates a lab panel showing the values.",
            "parameters": {
                "type": "object",
                "properties": {
                    "labs": {
                        "type": "array",
                        "description": "Array of lab results. Each should have: name (string like 'ALT', 'AST', 'Bilirubin'), value (number), unit (string like 'U/L', 'mg/dL'), range (string like '7-56'), status ('high', 'low', or 'normal')",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Lab test name like ALT, AST, Bilirubin, INR, Albumin"},
                                "value": {"type": "number", "description": "Numeric value of the lab result"},
                                "unit": {"type": "string", "description": "Unit like U/L, mg/dL, g/dL"},
                                "range": {"type": "string", "description": "Normal range like 7-56, 0.2-1.2"},
                                "status": {"type": "string", "description": "Status: high, low, or normal"}
                            },
                            "required": ["name", "value"]
                        }
                    },
                    "source": {
                        "type": "string",
                        "description": "Source of the lab results, defaults to 'Voice Agent'"
                    }
                },
                "required": ["labs"]
            }
        },
        {
            "name": "create_agent_result",
            "description": "Create and display a clinical analysis card on the board. Use when user says 'create analysis', 'add findings', 'display assessment', 'post a summary'. Shows formatted text on the board.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title for the analysis card, e.g., 'Lab Analysis', 'Clinical Assessment', 'Liver Function Summary'"
                    },
                    "content": {
                        "type": "string",
                        "description": "The analysis content. Can include findings, assessments, recommendations. Will be displayed on the board."
                    }
                },
                "required": ["title", "content"]
            }
        }
    ]

def get_voice_system_instruction(patient_id: str, patient_summary: str = "") -> str:
    """Get system instruction for voice mode"""
    try:
        with open("system_prompts/chat_model_system.md", "r", encoding="utf-8") as f:
            base_prompt = f.read()
    except:
        base_prompt = "You are MedForce Agent, a clinical AI assistant."
    
    context_section = ""
    if patient_summary:
        context_section = f"\n\n--- CURRENT PATIENT CONTEXT ---\n{patient_summary}\n"
    
    return f"""{base_prompt}

--- PATIENT-SPECIFIC INFO ---
Current Patient ID: {patient_id}
Board URL: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/{patient_id}{context_section}

CRITICAL VOICE MODE INSTRUCTIONS:

1. SPEAKING STYLE:
   - Speak at a SLOW, MEASURED PACE - take your time
   - Pause briefly between sentences for clarity
   - Use a calm, professional tone
   - Keep responses to 2-4 sentences when possible

2. TOOL USAGE (MANDATORY):
   - ALWAYS call get_patient_data FIRST when asked about patient information
   - This includes: name, age, medications, labs, diagnoses, allergies, history
   - NEVER say "I don't have access" - USE THE TOOLS
   - Patient ID for ALL tool calls: {patient_id}

3. AVAILABLE TOOLS:
   - get_patient_data: Get demographics, medications, labs, diagnoses, history
   - focus_board_item: Navigate to specific board items 
   - create_task: Create TODO tasks
   - send_to_easl: Get clinical analysis from EASL guidelines
   - generate_dili_diagnosis: Create DILI diagnosis report
   - generate_patient_report: Create patient summary
   - generate_legal_report: Create compliance report
   - create_schedule: Schedule follow-up appointments
   - send_notification: Alert care team
   - create_lab_results: Add lab values to board
   - create_agent_result: Add analysis cards to board

4. INTERACTION FLOW:
   - Greet briefly when session starts
   - Listen carefully to questions
   - Use tools to get accurate data
   - Respond with the information requested
   - Offer to help with related actions
"""

class SessionStatus(Enum):
    PENDING = "pending"  # Session created, connection not started
    CONNECTING = "connecting"  # Connection in progress
    READY = "ready"  # Connected and ready for use
    IN_USE = "in_use"  # Currently being used
    ERROR = "error"  # Failed to connect
    CLOSED = "closed"  # Session closed

@dataclass
class VoiceSession:
    """Represents a voice session with Gemini Live"""
    session_id: str
    patient_id: str
    status: SessionStatus = SessionStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    connected_at: Optional[datetime] = None
    error_message: Optional[str] = None
    connection_time_seconds: Optional[float] = None
    
    # These are set when connected
    gemini_session: Any = None
    client: Any = None
    audio_in_queue: Optional[asyncio.Queue] = None
    out_queue: Optional[asyncio.Queue] = None
    
    # Connection task
    _connect_task: Optional[asyncio.Task] = None

class VoiceSessionManager:
    """
    Manages voice sessions with background connection to Gemini.
    
    Usage:
    1. manager.create_session(patient_id) - Returns session_id immediately
    2. manager.get_status(session_id) - Check if ready
    3. manager.get_session(session_id) - Get the ready session
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self.sessions: Dict[str, VoiceSession] = {}
        self._client = None
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        
    def _get_client(self):
        """Get or create the Gemini client"""
        if self._client is None:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY required")
            self._client = genai.Client(api_key=api_key)
        return self._client
    
    def _create_brief_summary(self, context_data) -> str:
        """Create a brief summary of patient data for system instruction (max 1000 chars)."""
        if not context_data or not isinstance(context_data, list):
            return "No patient data available."
        
        try:
            summary_parts = []
            
            for item in context_data:
                if not isinstance(item, dict):
                    continue
                    
                # Find Sidebar with patient info
                if item.get("componentType") == "Sidebar" and "patientData" in item:
                    patient_data = item["patientData"]
                    
                    # Get demographics
                    if "patient" in patient_data:
                        p = patient_data["patient"]
                        name = p.get("name", "Unknown")
                        age = p.get("age", "?")
                        sex = p.get("sex", p.get("gender", "?"))
                        summary_parts.append(f"Patient: {name}, {age}yo {sex}")
                    
                    # Get primary diagnosis
                    if "description" in patient_data:
                        desc = patient_data["description"][:300]
                        summary_parts.append(f"Summary: {desc}")
                    
                    # Get problem list (first 5)
                    if "problem_list" in patient_data:
                        problems = patient_data["problem_list"][:5]
                        if problems:
                            problem_names = []
                            for p in problems:
                                if isinstance(p, dict):
                                    problem_names.append(p.get("name", str(p)))
                                else:
                                    problem_names.append(str(p)[:50])
                            if problem_names:
                                summary_parts.append(f"Key Problems: {', '.join(problem_names)}")
                    break
            
            return "\n".join(summary_parts) if summary_parts else "Patient data loaded."
        except Exception as e:
            logger.error(f"Error creating summary: {e}")
            return "Patient data available via tools."
    
    async def create_session(self, patient_id: str) -> str:
        """
        Create a new voice session and start connecting in background.
        Returns session_id immediately.
        """
        session_id = str(uuid.uuid4())[:8]  # Short ID for convenience
        
        session = VoiceSession(
            session_id=session_id,
            patient_id=patient_id
        )
        
        async with self._lock:
            self.sessions[session_id] = session
        
        # Start connection in background
        session._connect_task = asyncio.create_task(
            self._connect_session(session_id)
        )
        
        logger.info(f"📝 Created session {session_id} for patient {patient_id}")
        return session_id
    
    async def _connect_session(self, session_id: str):
        """Background task to connect to Gemini"""
        session = self.sessions.get(session_id)
        if not session:
            return
        
        session.status = SessionStatus.CONNECTING
        start_time = time.time()
        
        try:
            client = self._get_client()
            
            # Load patient context for system instruction
            logger.info(f"📋 [{session_id}] Loading patient context...")
            try:
                context_data = canvas_ops.get_board_items()
                patient_summary = self._create_brief_summary(context_data)
            except Exception as e:
                logger.warning(f"⚠️ [{session_id}] Could not load patient context: {e}")
                patient_summary = ""
            
            # Full config with system instruction and tools
            system_instruction = get_voice_system_instruction(session.patient_id, patient_summary)
            tool_declarations = get_voice_tool_declarations()
            
            config = {
                "response_modalities": ["AUDIO"],
                "system_instruction": system_instruction,
                "tools": [{"function_declarations": tool_declarations}],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            "voice_name": "Charon"
                        }
                    },
                    "language_code": "en-US"
                },
                "realtime_input_config": {
                    "automatic_activity_detection": {
                        "disabled": False,
                        "start_of_speech_sensitivity": "START_SENSITIVITY_LOW",
                        "end_of_speech_sensitivity": "END_SENSITIVITY_HIGH",
                        "prefix_padding_ms": 150,
                        "silence_duration_ms": 700
                    }
                }
            }
            
            logger.info(f"🔌 [{session_id}] Connecting to Gemini Live API...")
            logger.info(f"   Tools: {len(tool_declarations)} declared")
            logger.info(f"   System instruction: {len(system_instruction)} chars")
            
            # Connect and enter the context
            # Note: We manually manage the context because we need the session to stay open
            session.client = client
            
            # This is tricky - we need to keep the connection alive
            # We'll store the context manager and session
            connection = client.aio.live.connect(model=MODEL, config=config)
            session.gemini_session = await connection.__aenter__()
            
            # Store the context manager for cleanup
            session._connection_cm = connection
            
            elapsed = time.time() - start_time
            session.connection_time_seconds = elapsed
            session.connected_at = datetime.now()
            session.status = SessionStatus.READY
            session.audio_in_queue = asyncio.Queue()
            session.out_queue = asyncio.Queue(maxsize=10)
            
            logger.info(f"✅ [{session_id}] Connected in {elapsed:.2f}s")
            
        except Exception as e:
            elapsed = time.time() - start_time
            session.status = SessionStatus.ERROR
            session.error_message = str(e)
            session.connection_time_seconds = elapsed
            logger.error(f"❌ [{session_id}] Failed after {elapsed:.2f}s: {e}")
    
    def get_status(self, session_id: str) -> dict:
        """Get the status of a session"""
        session = self.sessions.get(session_id)
        if not session:
            return {"status": "not_found", "session_id": session_id}
        
        return {
            "session_id": session_id,
            "patient_id": session.patient_id,
            "status": session.status.value,
            "created_at": session.created_at.isoformat(),
            "connected_at": session.connected_at.isoformat() if session.connected_at else None,
            "connection_time_seconds": session.connection_time_seconds,
            "error_message": session.error_message
        }
    
    async def get_session(self, session_id: str) -> Optional[VoiceSession]:
        """Get a ready session"""
        session = self.sessions.get(session_id)
        if session and session.status == SessionStatus.READY:
            session.status = SessionStatus.IN_USE
            return session
        return None
    
    async def release_session(self, session_id: str):
        """Release a session back to ready state"""
        session = self.sessions.get(session_id)
        if session and session.status == SessionStatus.IN_USE:
            session.status = SessionStatus.READY
    
    async def close_session(self, session_id: str):
        """Close and cleanup a session"""
        session = self.sessions.get(session_id)
        if not session:
            return
        
        session.status = SessionStatus.CLOSED
        
        # Cancel connection task if still running
        if session._connect_task and not session._connect_task.done():
            session._connect_task.cancel()
            try:
                await session._connect_task
            except asyncio.CancelledError:
                pass
        
        # Close Gemini session
        if session.gemini_session and hasattr(session, '_connection_cm'):
            try:
                await session._connection_cm.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing session {session_id}: {e}")
        
        # Remove from sessions
        async with self._lock:
            self.sessions.pop(session_id, None)
        
        logger.info(f"🧹 [{session_id}] Session closed")
    
    async def cleanup_old_sessions(self, max_age_seconds: int = 300):
        """Cleanup sessions older than max_age"""
        now = datetime.now()
        to_remove = []
        
        async with self._lock:
            for session_id, session in self.sessions.items():
                age = (now - session.created_at).total_seconds()
                if age > max_age_seconds and session.status in [
                    SessionStatus.READY, 
                    SessionStatus.ERROR,
                    SessionStatus.CLOSED
                ]:
                    to_remove.append(session_id)
        
        for session_id in to_remove:
            await self.close_session(session_id)
    
    def start_cleanup_task(self):
        """Start background cleanup task"""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(60)  # Check every minute
                await self.cleanup_old_sessions()
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("🔄 Session cleanup task started")
    
    def stop_cleanup_task(self):
        """Stop background cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

# Global instance
voice_session_manager = VoiceSessionManager()
