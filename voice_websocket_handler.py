"""
Voice WebSocket Handler for Gemini Live API Integration
Handles real-time bidirectional voice communication
"""

import asyncio
import os
import sys
import traceback
import logging
import json
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
import side_agent
import canvas_ops

# CRITICAL FIX for Windows: Use SelectorEventLoop instead of ProactorEventLoop
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    logging.info("Windows: Using SelectorEventLoop for WebSocket compatibility")

# CRITICAL FIX: Monkey patch websockets to increase open_timeout from 10s to 120s
# This fixes timeout issues with Gemini Live API on Windows
from contextlib import asynccontextmanager
from websockets.asyncio.client import connect as original_ws_connect

@asynccontextmanager
async def patched_ws_connect(*args, **kwargs):
    """Patched version that adds longer timeout for Gemini Live API"""
    if 'open_timeout' not in kwargs:
        kwargs['open_timeout'] = 120  # 2 minutes instead of default 10 seconds
        print(f"🔧 [VOICE HANDLER PATCH] Setting open_timeout=120s")
    
    async with original_ws_connect(*args, **kwargs) as ws:
        yield ws

# Apply the patch to google.genai.live module
import google.genai.live
google.genai.live.ws_connect = patched_ws_connect

logger = logging.getLogger("voice-websocket")

# Gemini Live configuration - API Key model (Vertex AI model not supported via API key)
# Use latest supported model for API key authentication
MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"

class VoiceWebSocketHandler:
    """Handles real-time voice communication with Gemini Live API"""
    
    def __init__(self, websocket: WebSocket, patient_id: str):
        self.websocket = websocket
        self.patient_id = patient_id
        self.audio_in_queue = None
        self.out_queue = None
        self.session = None
        self.context_data = None
        self.patient_summary = None  # Brief patient summary for system instruction
        self.client = None  # Lazy initialization - only create when needed
    
    def _get_client(self):
        """Lazy initialization of Gemini client - only when needed"""
        if self.client is None:
            # Use API Key authentication (not Vertex AI)
            # The Live API model is available via API key, not Vertex AI
            api_key = os.getenv("GOOGLE_API_KEY")
            
            if not api_key:
                raise ValueError("GOOGLE_API_KEY is required for Gemini Live API")
            
            try:
                logger.info(f"🔧 Initializing Gemini client...")
                logger.info(f"   Model: {MODEL}")
                logger.info(f"   Authentication: API Key")
                
                self.client = genai.Client(api_key=api_key)
                
                logger.info(f"✅ Gemini client initialized successfully")
            except Exception as e:
                logger.error(f"❌ Failed to initialize Gemini client: {e}")
                raise
        return self.client
    
    async def get_system_instruction_with_context(self):
        """Get system instruction - SHORT to avoid context window issues"""
        try:
            # Load the system prompt from file - use chat_model_system for brevity
            with open("system_prompts/chat_model_system.md", "r", encoding="utf-8") as f:
                base_prompt = f.read()
            
            # Load patient context using canvas_ops but DON'T put in system instruction
            # It's too large and causes context window errors
            if not self.context_data:
                self.context_data = canvas_ops.get_board_items()
            
            # Keep system instruction SHORT - patient data will be accessed via tools
            full_instruction = f"""{base_prompt}

--- PATIENT-SPECIFIC CONTEXT ---
Current Patient ID: {self.patient_id}
Board URL: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/{self.patient_id}

CRITICAL INSTRUCTIONS FOR VOICE MODE:
- Keep responses VERY SHORT - 1-2 sentences maximum
- Be conversational and natural for voice interaction
- MANDATORY: For ANY question about patient data, you MUST call get_patient_data tool FIRST
- Questions requiring get_patient_data: name, age, gender, medications, labs, diagnosis, history, allergies, problems, encounters
- NEVER respond "I don't have access to patient data" - ALWAYS use get_patient_data tool
- After receiving tool data, answer concisely using that information
- Patient ID is always: {self.patient_id}
- Other tools: focus_board_item (navigate UI), create_task (add TODO), send_to_easl (clinical analysis)
"""
            
            logger.info(f"✅ Voice system instruction ready (context loaded separately)")
            return full_instruction
            
        except Exception as e:
            logger.error(f"Failed to load system prompt: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to basic prompt
            return f"""You are MedForce Agent — a real-time conversational AI assistant.
Keep responses VERY SHORT - 1-2 sentences maximum for voice interaction.
Current Patient ID: {self.patient_id}
Board URL: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/{self.patient_id}
Assist the clinician with patient care. Use tools to access data and perform actions.
"""
    
    def _create_brief_summary(self) -> str:
        """Create a brief summary of patient data for system instruction (max 500 chars)."""
        if not self.context_data or not isinstance(self.context_data, list):
            return "No patient data available."
        
        try:
            summary_parts = []
            
            # Find Sidebar with patient info
            for item in self.context_data:
                if item.get("componentType") == "Sidebar" and "patientData" in item:
                    patient_data = item["patientData"]
                    
                    # Get demographics
                    if "patient" in patient_data:
                        p = patient_data["patient"]
                        name = p.get("name", "Unknown")
                        age = p.get("age", "?")
                        sex = p.get("sex", "?")
                        summary_parts.append(f"Patient: {name}, {age}yo {sex}")
                    
                    # Get primary diagnosis
                    if "description" in patient_data:
                        desc = patient_data["description"][:150]
                        summary_parts.append(f"Summary: {desc}")
                    
                    # Get problem list (first 3)
                    if "problem_list" in patient_data:
                        problems = patient_data["problem_list"][:3]
                        if problems:
                            problem_names = [p.get("name", "") for p in problems]
                            summary_parts.append(f"Key Problems: {', '.join(problem_names)}")
                    
                    break
            
            return "\n".join(summary_parts) if summary_parts else "Patient data loaded."
        except Exception as e:
            logger.error(f"Error creating summary: {e}")
            return "Patient data available via tools."
    
    def get_system_instruction(self):
        """Get system instruction for this patient (sync wrapper) - SHORT version"""
        try:
            # Load the system prompt from file - use chat_model_system for brevity
            with open("system_prompts/chat_model_system.md", "r", encoding="utf-8") as f:
                base_prompt = f.read()
            
            # Add patient-specific context - KEEP SHORT but include summary
            context_section = ""
            if self.patient_summary:
                context_section = f"\n\n--- CURRENT PATIENT CONTEXT ---\n{self.patient_summary}\n"
            
            return f"""{base_prompt}

--- PATIENT-SPECIFIC INFO ---
Current Patient ID: {self.patient_id}
Board URL: https://iso-clinic-v3-481780815788.europe-west1.run.app/board/{self.patient_id}{context_section}

CRITICAL INSTRUCTIONS FOR VOICE MODE:
- Keep responses VERY SHORT - 1-2 sentences maximum
- Be conversational and natural for voice interaction
- You have access to the patient's data shown above - use it to answer questions directly
- For detailed or updated information, call get_patient_data tool
- Use focus_board_item to navigate the board
- Use create_task to add TODOs
- Use create_lab_results to add lab values to the board (e.g., "Add ALT 110, AST 150 to the board")
- Use create_agent_result to add clinical analysis to the board (e.g., "Create analysis showing liver injury")
- Always use patient_id: {self.patient_id} when calling tools
"""
        except Exception as e:
            logger.error(f"Failed to load system prompt: {e}")
            # Fallback to basic prompt
            return f"""You are MedForce Agent — a real-time conversational AI assistant.
Keep responses VERY SHORT - 1-2 sentences maximum for voice interaction.
Current Patient ID: {self.patient_id}
Use tools to access data and perform actions.
"""
    
    def get_config(self):
        """Get Gemini Live API configuration with tool declarations"""
        # Define tool declarations for voice mode actions
        tool_declarations = [
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
        
        return {
            "response_modalities": ["AUDIO"],
            "system_instruction": self.get_system_instruction(),
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
    
    async def send_status_to_ui(self, status_type: str, message: str, **kwargs):
        """Send status/notification to UI via WebSocket (like chat agent does)"""
        try:
            payload = {
                "type": "status",
                "status": status_type,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
            logger.info(f"📤 Sending status to UI: {status_type} - {message}")
            await self.websocket.send_json(payload)
            logger.info(f"✅ Status sent successfully")
        except Exception as e:
            logger.error(f"❌ Failed to send status to UI: {e}")
    
    async def send_tool_notification(self, tool_name: str, status: str, result: str = None):
        """Send tool execution notification to UI (like chat agent does)"""
        try:
            payload = {
                "type": "tool_call",
                "tool": tool_name,
                "status": status,  # "executing", "completed", "failed"
                "result": result,
                "timestamp": datetime.now().isoformat()
            }
            await self.websocket.send_json(payload)
            logger.info(f"📤 Sent tool notification to UI: {tool_name} - {status}")
        except Exception as e:
            logger.error(f"Failed to send tool notification: {e}")
    
    async def handle_tool_call(self, tool_call):
        """Handle tool calls from Gemini using side_agent and canvas_ops"""
        try:
            logger.info("🔧 Tool call detected")
            function_responses = []
            
            for fc in tool_call.function_calls:
                function_name = fc.name
                arguments = dict(fc.args)
                
                logger.info(f"  📋 Executing: {function_name}")
                
                # Notify UI that tool is executing
                await self.send_tool_notification(function_name, "executing")
                
                result = ""
                try:
                    if function_name == "get_patient_data":
                        # Load full context if not already loaded
                        if not self.context_data:
                            self.context_data = canvas_ops.get_board_items()
                        
                        logger.info(f"📊 Context data type: {type(self.context_data)}, length: {len(self.context_data) if isinstance(self.context_data, (list, dict)) else 'N/A'}")
                        
                        # Search for "pulmonary" and related medical terms across all data
                        search_terms = ["pulmonary", "respiratory", "lung", "copd", "pneumonia", "dyspnea", "asthma", "bronchitis"]
                        full_data_str = json.dumps(self.context_data).lower()
                        found_terms = [term for term in search_terms if term in full_data_str]
                        
                        if found_terms:
                            logger.info(f"🔍 FOUND medical terms in board data: {found_terms}")
                        else:
                            logger.info(f"🔍 WARNING: None of these terms found in board: {search_terms}")
                        
                        pulmonary_locations = []
                        
                        # Extract ESSENTIAL data only - full dump exceeds 32k context window
                        # We need structured info that's useful but concise
                        summary = {"patient_id": self.patient_id}
                        
                        if isinstance(self.context_data, list):
                            logger.info(f"📋 Processing {len(self.context_data)} board items")
                            for idx, item in enumerate(self.context_data):
                                if not isinstance(item, dict):
                                    continue
                                
                                # Check if this item contains pulmonary or respiratory info
                                item_str = json.dumps(item).lower()
                                found_in_item = [term for term in search_terms if term in item_str]
                                if found_in_item:
                                    comp_type_for_log = item.get('componentType', 'unknown')
                                    logger.info(f"🔍 Item {idx} ({comp_type_for_log}) contains: {found_in_item}")
                                    pulmonary_locations.append(f"Item {idx}: {comp_type_for_log} - {found_in_item}")
                                
                                comp_type = item.get("componentType")
                                item_type = item.get("type")
                                
                                # Log ALL items to find patient profile
                                logger.info(f"  Item {idx}: componentType={comp_type}, type={item_type}, keys={list(item.keys())}")
                                
                                # Extract patient data from 'patient' field (SingleEncounterDocument)
                                if "patient" in item and isinstance(item["patient"], dict):
                                    patient = item["patient"]
                                    if "name" not in summary:
                                        logger.info(f"✅ Found patient field in item {idx}, patient keys: {list(patient.keys())}")
                                        if patient.get("name"):
                                            summary["name"] = patient.get("name")
                                            # Handle different field names
                                            summary["age"] = patient.get("age") or patient.get("age_at_first_encounter")
                                            summary["gender"] = patient.get("gender") or patient.get("sex")
                                            summary["mrn"] = patient.get("mrn") or patient.get("id")
                                            summary["date_of_birth"] = patient.get("date_of_birth") or patient.get("dateOfBirth")
                                            logger.info(f"   Patient: {summary.get('name')}, {summary.get('age')}yo, {summary.get('gender')}")
                                        if patient.get("medicalHistory"):
                                            history = patient.get("medicalHistory")
                                            logger.info(f"📋 Found medicalHistory in item {idx}, type: {type(history)}")
                                            summary["medical_history"] = str(history)[:2000]  # Increased to capture more
                                        if patient.get("medical_history"):
                                            history = patient.get("medical_history")
                                            logger.info(f"📋 Found medical_history in item {idx}, type: {type(history)}")
                                            summary["medical_history"] = str(history)[:2000]
                                
                                # Extract encounter data with clinical notes
                                if "encounter" in item and isinstance(item["encounter"], dict):
                                    encounter = item["encounter"]
                                    # Check for pulmonary in encounter
                                    encounter_str = json.dumps(encounter)
                                    if "pulmonary" in encounter_str.lower():
                                        logger.info(f"🔍 Found 'pulmonary' in encounter at item {idx}!")
                                    
                                    if "clinical_notes" not in summary:
                                        summary["clinical_notes"] = []
                                    if "rawText" in encounter:
                                        summary["clinical_notes"].append({
                                            "date": encounter.get("date"),
                                            "text": encounter.get("rawText")[:1500]  # Increased to 1500
                                        })
                                    if "assessment" in encounter:
                                        if "assessment" not in summary:
                                            summary["assessment"] = encounter["assessment"]
                                    # Extract history of present illness, review of systems, etc
                                    if "history_of_present_illness" in encounter:
                                        if "hpi" not in summary:
                                            summary["hpi"] = []
                                        summary["hpi"].append(encounter["history_of_present_illness"][:1000])
                                    if "review_of_systems" in encounter:
                                        if "review_of_systems" not in summary:
                                            summary["review_of_systems"] = []
                                        ros = encounter["review_of_systems"]
                                        if isinstance(ros, dict):
                                            summary["review_of_systems"].append(ros)
                                        else:
                                            summary["review_of_systems"].append(str(ros)[:1000])
                                
                                # Extract raw clinical note
                                if comp_type == "RawClinicalNote":
                                    # Check for pulmonary in raw text
                                    raw_text = item.get("rawText", "")
                                    if "pulmonary" in raw_text.lower():
                                        logger.info(f"🔍 Found 'pulmonary' in RawClinicalNote at item {idx}!")
                                    
                                    if "recent_clinical_notes" not in summary:
                                        summary["recent_clinical_notes"] = []
                                    note = {
                                        "date": item.get("date"),
                                        "visitType": item.get("visitType"),
                                        "provider": item.get("provider"),
                                        "text": raw_text[:1500] if raw_text else ""  # Increased to 1500 to capture more
                                    }
                                    summary["recent_clinical_notes"].append(note)
                                    logger.info(f"📋 Added clinical note from {item.get('date')}, text length: {len(raw_text)}")
                                
                                # Extract patient data from 'patientData' field (Sidebar, DifferentialDiagnosis)
                                if "patientData" in item and isinstance(item["patientData"], dict):
                                    patient_data = item["patientData"]
                                    logger.info(f"📋 patientData keys in item {idx}: {list(patient_data.keys())}")
                                    
                                    # Check if there's a nested 'patient' object inside patientData (Sidebar)
                                    if "patient" in patient_data and isinstance(patient_data["patient"], dict):
                                        nested_patient = patient_data["patient"]
                                        if "name" not in summary and nested_patient.get("name"):
                                            logger.info(f"✅ Found nested patient in patientData in item {idx}, keys: {list(nested_patient.keys())}")
                                            summary["name"] = nested_patient.get("name")
                                            summary["age"] = nested_patient.get("age") or nested_patient.get("age_at_first_encounter")
                                            summary["gender"] = nested_patient.get("gender") or nested_patient.get("sex")
                                            summary["mrn"] = nested_patient.get("mrn") or nested_patient.get("id")
                                            summary["date_of_birth"] = nested_patient.get("date_of_birth")
                                            summary["identifiers"] = nested_patient.get("identifiers")
                                            logger.info(f"   Patient: {summary.get('name')}, {summary.get('age')}yo, {summary.get('gender')}, DOB: {summary.get('date_of_birth')}")
                                    
                                    # Extract additional clinical data from Sidebar
                                    if "problem_list" in patient_data:
                                        problems = patient_data["problem_list"]
                                        logger.info(f"📋 Found problem_list in item {idx}: {problems}")
                                        if isinstance(problems, list):
                                            summary["problem_list"] = [str(p)[:300] for p in problems[:30]]  # Increased limits
                                        elif isinstance(problems, dict):
                                            summary["problem_list"] = problems
                                        else:
                                            summary["problem_list"] = str(problems)[:1000]
                                    if "allergies" in patient_data:
                                        logger.info(f"📋 Found allergies in item {idx}: {patient_data['allergies']}")
                                        summary["allergies"] = patient_data["allergies"]
                                    if "medication_timeline" in patient_data:
                                        # This might be large, so summarize
                                        med_timeline = patient_data["medication_timeline"]
                                        if isinstance(med_timeline, list):
                                            summary["medication_count"] = len(med_timeline)
                                        else:
                                            summary["medication_timeline_info"] = str(med_timeline)[:300]
                                    if "riskLevel" in patient_data:
                                        summary["risk_level"] = patient_data["riskLevel"]
                                    if "description" in patient_data:
                                        desc = patient_data["description"]
                                        logger.info(f"📋 Found clinical description in item {idx}, length: {len(str(desc))}")
                                        summary["clinical_summary"] = str(desc)[:2000]  # Increased to capture more info
                                    
                                    # Also check for direct fields in patientData
                                    if "name" not in summary and patient_data.get("name"):
                                        logger.info(f"✅ Found name in patientData in item {idx}")
                                        summary["name"] = patient_data.get("name")
                                        summary["age"] = patient_data.get("age") or patient_data.get("age_at_first_encounter")
                                        summary["gender"] = patient_data.get("gender") or patient_data.get("sex")
                                        summary["mrn"] = patient_data.get("mrn") or patient_data.get("id")
                                        summary["date_of_birth"] = patient_data.get("date_of_birth")
                                        logger.info(f"   Patient: {summary.get('name')}, {summary.get('age')}yo, {summary.get('gender')}")
                                
                                # Patient profile - check multiple possible field names
                                if "patientProfile" in item:
                                    profile = item["patientProfile"]
                                    logger.info(f"✅ Found patientProfile in item {idx}: {profile}")
                                    summary["name"] = profile.get("name")
                                    summary["age"] = profile.get("age")
                                    summary["gender"] = profile.get("gender")
                                    summary["mrn"] = profile.get("mrn")
                                
                                # Check for direct patient fields
                                if "name" in item and "age" in item and "name" not in summary:
                                    logger.info(f"✅ Found direct patient fields in item {idx}")
                                    summary["name"] = item.get("name")
                                    summary["age"] = item.get("age")
                                    summary["gender"] = item.get("gender")
                                    summary["mrn"] = item.get("mrn")
                                
                                # Patient context - check multiple field names
                                if "patientContext" in item:
                                    ctx = item["patientContext"]
                                    logger.info(f"✅ Found patientContext in item {idx}")
                                    summary["chief_complaint"] = ctx.get("chiefComplaint")
                                    summary["history"] = ctx.get("presentingHistory", ctx.get("history", ""))[:500]
                                
                                # Risk analysis
                                if "riskAnalysis" in item:
                                    risk = item["riskAnalysis"]
                                    logger.info(f"✅ Found riskAnalysis in item {idx}")
                                    summary["risk_score"] = risk.get("riskScore")
                                    summary["risk_factors"] = risk.get("riskFactors", [])[:5]
                                
                                # Encounters - check both structures
                                if "encounters" in item and isinstance(item["encounters"], list):
                                    if "recent_encounters" not in summary:
                                        summary["recent_encounters"] = []
                                    for enc in item["encounters"][:5]:
                                        if isinstance(enc, dict):
                                            enc_data = {
                                                "date": enc.get("date"),
                                                "visitType": enc.get("visitType"),
                                                "provider": enc.get("provider")
                                            }
                                            # Add assessment if available
                                            if "assessment" in enc:
                                                enc_data["assessment"] = enc["assessment"]
                                            summary["recent_encounters"].append(enc_data)
                                    logger.info(f"✅ Found {len(item['encounters'])} encounters in item {idx}")
                                
                                # ==========================================
                                # MEDICATIONS - MedicationTrack has data.medications
                                # ==========================================
                                if comp_type == "MedicationTrack" and "data" in item:
                                    med_data = item["data"]
                                    meds_list = []
                                    # data can be dict with medications key or direct array
                                    if isinstance(med_data, dict) and "medications" in med_data:
                                        meds_list = med_data["medications"]
                                    elif isinstance(med_data, list):
                                        meds_list = med_data
                                    
                                    if meds_list:
                                        meds = []
                                        for med in meds_list[:15]:
                                            if isinstance(med, dict):
                                                name = med.get('name', 'Unknown')
                                                dose = med.get('dose', '')
                                                freq = med.get('frequency', '')
                                                start = med.get('startDate', '')
                                                end = med.get('endDate', 'ongoing')
                                                indication = med.get('indication', '')
                                                med_str = f"{name} {dose}"
                                                if freq:
                                                    med_str += f" {freq}"
                                                if indication:
                                                    med_str += f" (for {indication})"
                                                if start:
                                                    med_str += f" [started {start}"
                                                    if end and end != 'ongoing':
                                                        med_str += f", ended {end}]"
                                                    else:
                                                        med_str += ", ongoing]"
                                                meds.append(med_str)
                                        if meds:
                                            logger.info(f"✅ Found {len(meds)} medications in MedicationTrack (item {idx})")
                                            logger.info(f"   Sample meds: {meds[:3]}")
                                            summary["current_medications"] = meds
                                
                                # Also check for direct medications array (legacy format)
                                elif "medications" in item and isinstance(item["medications"], list):
                                    meds = []
                                    for med in item["medications"][:15]:
                                        if isinstance(med, dict):
                                            med_str = f"{med.get('name')} {med.get('dose')} {med.get('frequency')}"
                                            if med.get("indication"):
                                                med_str += f" (for {med.get('indication')})"
                                            meds.append(med_str)
                                    if meds:
                                        logger.info(f"✅ Found {len(meds)} medications (direct) in item {idx}")
                                        summary["current_medications"] = meds
                                
                                # ==========================================
                                # LABS - LabTrack can have data array or labs array
                                # ==========================================
                                if comp_type == "LabTrack":
                                    # Try both possible keys: 'data' or 'labs'
                                    lab_data = item.get("data") or item.get("labs", [])
                                    if isinstance(lab_data, list) and lab_data:
                                        labs = []
                                        for biomarker in lab_data[:20]:
                                            if isinstance(biomarker, dict):
                                                # Try multiple field names for biomarker name
                                                name = biomarker.get('biomarker') or biomarker.get('name') or biomarker.get('parameter') or 'Unknown'
                                                unit = biomarker.get('unit', '')
                                                ref_range = biomarker.get('referenceRange', {})
                                                if isinstance(ref_range, dict):
                                                    ref_min = ref_range.get('min')
                                                    ref_max = ref_range.get('max')
                                                else:
                                                    ref_min = ref_max = None
                                                values = biomarker.get('values', [])
                                                
                                                # Get most recent value
                                                value = None
                                                date = ''
                                                if values and isinstance(values, list):
                                                    latest = values[-1] if values else {}
                                                    if isinstance(latest, dict):
                                                        value = latest.get('value')
                                                        date = latest.get('t', '')[:10] if latest.get('t') else ''
                                                    else:
                                                        value = latest  # Direct value
                                                
                                                # Skip if no name or value
                                                if name == 'Unknown' and value is None:
                                                    continue
                                                    
                                                # Check if abnormal
                                                abnormal = False
                                                if value is not None:
                                                    if ref_min is not None and value < ref_min:
                                                        abnormal = True
                                                    if ref_max is not None and value > ref_max:
                                                        abnormal = True
                                                
                                                lab_str = f"{name}: {value} {unit}".strip()
                                                if ref_min is not None or ref_max is not None:
                                                    lab_str += f" (ref: {ref_min}-{ref_max})"
                                                if date:
                                                    lab_str += f" [{date}]"
                                                if abnormal:
                                                    lab_str += " [ABNORMAL]"
                                                labs.append(lab_str)
                                        
                                        if labs:
                                            logger.info(f"✅ Found {len(labs)} lab values in LabTrack (item {idx})")
                                            logger.info(f"   Sample labs: {labs[:3]}")
                                            summary["recent_labs"] = labs
                                
                                # Also check for direct labs array (legacy format)
                                elif "labs" in item and isinstance(item["labs"], list):
                                    labs = []
                                    for lab in item["labs"][:15]:
                                        if isinstance(lab, dict):
                                            # Try multiple possible field names for lab name
                                            lab_name = lab.get('name') or lab.get('biomarker') or lab.get('parameter') or lab.get('test') or 'Unknown'
                                            lab_value = lab.get('value')
                                            lab_unit = lab.get('unit', '')
                                            
                                            # Handle nested values array (like LabTrack format)
                                            if lab_value is None and 'values' in lab:
                                                values = lab.get('values', [])
                                                if values and isinstance(values, list):
                                                    latest = values[-1] if values else {}
                                                    lab_value = latest.get('value') if isinstance(latest, dict) else latest
                                            
                                            # Get reference range
                                            ref_range = lab.get('referenceRange', {})
                                            if isinstance(ref_range, dict):
                                                ref_min = ref_range.get('min')
                                                ref_max = ref_range.get('max')
                                                range_str = f"{ref_min}-{ref_max}" if ref_min is not None else ""
                                            else:
                                                range_str = str(ref_range) if ref_range else ""
                                            
                                            # Skip if no valid name or value
                                            if lab_name == 'Unknown' and lab_value is None:
                                                continue
                                                
                                            lab_str = f"{lab_name}: {lab_value} {lab_unit}"
                                            if range_str:
                                                lab_str += f" (ref: {range_str})"
                                            if lab.get("date"):
                                                lab_str += f" ({lab.get('date')})"
                                            if lab.get("flag") or lab.get("abnormal") or lab.get("status") == "abnormal":
                                                lab_str += " [ABNORMAL]"
                                            labs.append(lab_str)
                                    if labs:
                                        logger.info(f"✅ Found {len(labs)} labs (direct) in item {idx}")
                                        summary["recent_labs"] = labs
                                
                                # ==========================================
                                # RISK EVENTS - RiskTrack has risks directly
                                # ==========================================
                                if comp_type == "RiskTrack" and "risks" in item and isinstance(item["risks"], list):
                                    risks = []
                                    for risk in item["risks"][:10]:
                                        if isinstance(risk, dict):
                                            risk_entry = {
                                                "date": risk.get("t", "")[:10] if risk.get("t") else risk.get("date"),
                                                "riskScore": risk.get("riskScore"),
                                                "factors": risk.get("factors", [])
                                            }
                                            risks.append(risk_entry)
                                    if risks:
                                        logger.info(f"✅ Found {len(risks)} risk scores in RiskTrack (item {idx})")
                                        logger.info(f"   Sample risk: {risks[0]}")
                                        summary["risk_events"] = risks
                                
                                # Also check for direct risks array (legacy format)
                                elif "risks" in item and isinstance(item["risks"], list) and comp_type != "RiskTrack":
                                    if "risk_events" not in summary:
                                        summary["risk_events"] = []
                                    for risk in item["risks"][:10]:
                                        if isinstance(risk, dict):
                                            summary["risk_events"].append({
                                                "date": risk.get("date") or risk.get("t", "")[:10] if risk.get("t") else "",
                                                "event": risk.get("event") or risk.get("description"),
                                                "severity": risk.get("severity") or risk.get("level")
                                            })
                                
                                # ==========================================
                                # KEY EVENTS - KeyEventsTrack has events directly
                                # ==========================================
                                if comp_type == "KeyEventsTrack" and "events" in item and isinstance(item["events"], list):
                                    events = []
                                    for event in item["events"][:15]:
                                        if isinstance(event, dict):
                                            event_entry = {
                                                "date": event.get("t", "")[:10] if event.get("t") else event.get("date"),
                                                "event": event.get("event"),
                                                "note": event.get("note")
                                            }
                                            events.append(event_entry)
                                    if events:
                                        logger.info(f"✅ Found {len(events)} key events in KeyEventsTrack (item {idx})")
                                        logger.info(f"   Sample event: {events[0]}")
                                        summary["key_events"] = events
                                
                                # Also check for direct events array (legacy format)
                                elif "events" in item and isinstance(item["events"], list) and comp_type != "KeyEventsTrack":
                                    if "key_events" not in summary:
                                        summary["key_events"] = []
                                    for event in item["events"][:10]:
                                        if isinstance(event, dict):
                                            summary["key_events"].append({
                                                "date": event.get("date") or event.get("t", "")[:10] if event.get("t") else "",
                                                "event": event.get("event") or event.get("description")
                                            })
                                
                                # ==========================================
                                # ADVERSE EVENTS - AdverseEventAnalytics
                                # ==========================================
                                if comp_type == "AdverseEventAnalytics":
                                    if "adverseEvents" in item and isinstance(item["adverseEvents"], list):
                                        adverse = []
                                        for ae in item["adverseEvents"][:10]:
                                            if isinstance(ae, dict):
                                                adverse.append({
                                                    "event": ae.get("event") or ae.get("name"),
                                                    "date": ae.get("date") or ae.get("t", "")[:10] if ae.get("t") else "",
                                                    "severity": ae.get("severity") or ae.get("grade"),
                                                    "causality": ae.get("causality")
                                                })
                                        if adverse:
                                            logger.info(f"✅ Found {len(adverse)} adverse events in AdverseEventAnalytics (item {idx})")
                                            summary["adverse_events"] = adverse
                                    
                                    if "rucam_ctcae_analysis" in item:
                                        summary["rucam_analysis"] = item["rucam_ctcae_analysis"]
                                        logger.info(f"✅ Found RUCAM/CTCAE analysis in item {idx}")
                                
                                # Differential diagnosis
                                if "differential" in item and isinstance(item["differential"], list):
                                    summary["differential_diagnosis"] = item["differential"][:10]
                                
                                # Primary diagnosis (from Sidebar)
                                if "primaryDiagnosis" in item:
                                    summary["primary_diagnosis"] = item["primaryDiagnosis"]
                        
                        logger.info(f"📤 Returning summary with keys: {list(summary.keys())}")
                        logger.info(f"📤 Summary counts: name={summary.get('name')}, age={summary.get('age')}, meds={len(summary.get('current_medications', []))}, labs={len(summary.get('recent_labs', []))}, risks={len(summary.get('risk_events', []))}, events={len(summary.get('key_events', []))}")
                        
                        # Log actual content samples for debugging
                        if summary.get('recent_labs'):
                            logger.info(f"📤 Lab values: {summary['recent_labs'][:3]}")
                        if summary.get('current_medications'):
                            logger.info(f"📤 Medications: {summary['current_medications'][:3]}")
                        if summary.get('risk_events'):
                            logger.info(f"📤 Risk events: {summary['risk_events'][:2]}")
                        if summary.get('key_events'):
                            logger.info(f"📤 Key events: {summary['key_events'][:2]}")
                        
                        if pulmonary_locations:
                            logger.info(f"🔍 Pulmonary info found in: {pulmonary_locations}")
                        result = json.dumps(summary, indent=2)
                    
                    elif function_name == "focus_board_item":
                        query = arguments.get("query", "")
                        # Use side_agent to resolve object_id
                        context = json.dumps(self.context_data) if self.context_data else "{}"
                        object_id = await side_agent.resolve_object_id(query, context)
                        if object_id:
                            await canvas_ops.focus_item(object_id)
                            result = f"Focused on {object_id}"
                        else:
                            result = "Could not find matching board item"
                    
                    elif function_name == "create_task":
                        query = arguments.get("query", "")
                        # Use side_agent to generate and create task
                        task_result = await side_agent.generate_task_workflow(query)
                        result = f"Task created: {task_result}"
                    
                    elif function_name == "send_to_easl":
                        question = arguments.get("question", "")
                        # Use side_agent to trigger EASL
                        easl_result = await side_agent.trigger_easl(question)
                        result = f"Sent to EASL: {easl_result}"
                    
                    elif function_name == "generate_dili_diagnosis":
                        # Generate DILI diagnosis report
                        logger.info("🔬 Generating DILI diagnosis...")
                        diagnosis_result = await side_agent.create_dili_diagnosis()
                        result = json.dumps({
                            "status": "success",
                            "message": "DILI diagnosis report generated and added to board",
                            "summary": str(diagnosis_result.get('generated', {}))[:500]
                        })
                    
                    elif function_name == "generate_patient_report":
                        # Generate patient report
                        logger.info("📄 Generating patient report...")
                        report_result = await side_agent.create_patient_report()
                        result = json.dumps({
                            "status": "success",
                            "message": "Patient report generated and added to board",
                            "summary": str(report_result.get('generated', {}))[:500]
                        })
                    
                    elif function_name == "generate_legal_report":
                        # Generate legal report
                        logger.info("⚖️ Generating legal report...")
                        legal_result = await side_agent.create_legal_doc()
                        result = json.dumps({
                            "status": "success",
                            "message": "Legal compliance report generated and added to board",
                            "summary": str(legal_result.get('generated', {}))[:500]
                        })
                    
                    elif function_name == "create_schedule":
                        # Create schedule panel
                        context = arguments.get("context", "Follow-up appointment scheduling")
                        logger.info(f"📅 Creating schedule: {context}")
                        schedule_result = await canvas_ops.create_schedule({"schedulingContext": context})
                        result = json.dumps({
                            "status": schedule_result.get("status", "done"),
                            "message": schedule_result.get("message", "Schedule panel created"),
                            "api_response": schedule_result.get("api_response")
                        })
                    
                    elif function_name == "send_notification":
                        # Send notification
                        message = arguments.get("message", "Notification from voice agent")
                        logger.info(f"🔔 Sending notification: {message}")
                        notif_result = await canvas_ops.create_notification({"message": message})
                        result = json.dumps({
                            "status": notif_result.get("status", "done"),
                            "message": notif_result.get("message", "Notification sent"),
                            "api_response": notif_result.get("api_response")
                        })
                    
                    elif function_name == "create_lab_results":
                        # Create lab results on the board
                        labs = arguments.get("labs", [])
                        source = arguments.get("source", "Voice Agent")
                        logger.info(f"🧪 Creating lab results: {len(labs)} values, type: {type(labs)}")
                        logger.info(f"🧪 Labs data: {labs}")
                        
                        from datetime import datetime
                        
                        # Transform lab data for board API - handle various input formats
                        transformed_labs = []
                        
                        # Check if Gemini sent a flat array of strings like ['name:', 'ALT', 'unit:', 'U/L', 'value:110']
                        # This happens when voice transcription breaks up the data
                        if labs and all(isinstance(item, str) for item in labs):
                            logger.info("🧪 Detected flat string array - attempting to reconstruct")
                            # Try to reconstruct lab objects from flat strings
                            current_lab = {}
                            i = 0
                            while i < len(labs):
                                item = labs[i].strip()
                                
                                # Check for key:value format
                                if ':' in item:
                                    parts = item.split(':', 1)
                                    key = parts[0].strip().lower()
                                    val = parts[1].strip() if len(parts) > 1 else ''
                                    
                                    if key in ['name', 'parameter', 'test']:
                                        if current_lab.get('name'):
                                            # Save previous lab and start new one
                                            transformed_labs.append({
                                                "parameter": current_lab.get('name', 'Unknown'),
                                                "value": current_lab.get('value', 0),
                                                "unit": current_lab.get('unit', ''),
                                                "range": current_lab.get('range', ''),
                                                "status": current_lab.get('status', 'normal')
                                            })
                                            current_lab = {}
                                        current_lab['name'] = val
                                    elif key == 'value':
                                        try:
                                            current_lab['value'] = float(val) if val else 0
                                        except:
                                            current_lab['value'] = 0
                                    elif key == 'unit':
                                        current_lab['unit'] = val
                                    elif key in ['range', 'normal', 'reference']:
                                        current_lab['range'] = val
                                    elif key == 'status':
                                        current_lab['status'] = val.lower()
                                else:
                                    # Might be a standalone value - check next item for context
                                    # Common lab names
                                    lab_names = ['ALT', 'AST', 'Bilirubin', 'Albumin', 'INR', 'Creatinine', 
                                                'BUN', 'Sodium', 'Potassium', 'Glucose', 'WBC', 'RBC', 
                                                'Hemoglobin', 'Hematocrit', 'Platelets', 'PT', 'PTT']
                                    if item.upper() in [n.upper() for n in lab_names]:
                                        if current_lab.get('name'):
                                            transformed_labs.append({
                                                "parameter": current_lab.get('name', 'Unknown'),
                                                "value": current_lab.get('value', 0),
                                                "unit": current_lab.get('unit', ''),
                                                "range": current_lab.get('range', ''),
                                                "status": current_lab.get('status', 'normal')
                                            })
                                            current_lab = {}
                                        current_lab['name'] = item
                                    elif item.replace('.', '').replace('-', '').isdigit():
                                        try:
                                            current_lab['value'] = float(item)
                                        except:
                                            pass
                                    elif item in ['U/L', 'mg/dL', 'g/dL', 'mEq/L', 'mmol/L', '%']:
                                        current_lab['unit'] = item
                                    elif item.lower() in ['high', 'low', 'normal', 'abnormal']:
                                        current_lab['status'] = item.lower()
                                i += 1
                            
                            # Don't forget the last lab
                            if current_lab.get('name'):
                                transformed_labs.append({
                                    "parameter": current_lab.get('name', 'Unknown'),
                                    "value": current_lab.get('value', 0),
                                    "unit": current_lab.get('unit', ''),
                                    "range": current_lab.get('range', ''),
                                    "status": current_lab.get('status', 'normal')
                                })
                        else:
                            # Normal processing - labs should be list of dicts
                            for lab in labs:
                                # Handle case where lab might be a string (JSON) instead of dict
                                if isinstance(lab, str):
                                    try:
                                        lab = json.loads(lab)
                                    except:
                                        # If it's just a name string, create minimal entry
                                        lab = {"name": lab, "value": 0, "unit": "", "range": "", "status": "normal"}
                                
                                if isinstance(lab, dict):
                                    transformed_labs.append({
                                        "parameter": lab.get("name") or lab.get("parameter", "Unknown"),
                                        "value": lab.get("value", 0),
                                        "unit": lab.get("unit", ""),
                                        "range": lab.get("range") or lab.get("normalRange", ""),
                                        "status": lab.get("status", "normal")
                                    })
                                else:
                                    logger.warning(f"Skipping invalid lab entry: {lab}")
                        
                        lab_payload = {
                            "labResults": transformed_labs,
                            "date": datetime.now().strftime('%Y-%m-%d'),
                            "source": source
                        }
                        
                        logger.info(f"🧪 Sending lab payload: {lab_payload}")
                        lab_result = await canvas_ops.create_lab(lab_payload)
                        result = json.dumps({
                            "status": "success",
                            "message": f"Created {len(transformed_labs)} lab results on board",
                            "labs_added": [l.get('parameter') for l in transformed_labs],
                            "api_response": lab_result
                        })
                    
                    elif function_name == "create_agent_result":
                        # Create agent analysis result on the board
                        title = arguments.get("title", "Voice Agent Analysis")
                        content = arguments.get("content", "")
                        logger.info(f"📊 Creating agent result: {title}")
                        
                        from datetime import datetime
                        
                        agent_payload = {
                            "title": title,
                            "content": content,
                            "agentName": "Voice Agent",
                            "timestamp": datetime.now().isoformat()
                        }
                        
                        agent_res = await canvas_ops.create_result(agent_payload)
                        result = json.dumps({
                            "status": "success",
                            "message": f"Created agent analysis: {title}",
                            "api_response": agent_res
                        })
                    
                    else:
                        result = f"Unknown tool: {function_name}"
                    
                except Exception as tool_error:
                    logger.error(f"Tool {function_name} error: {tool_error}")
                    result = f"Error executing {function_name}: {str(tool_error)}"
                    
                    # Notify UI that tool failed
                    await self.send_tool_notification(function_name, "failed", result)
                
                function_responses.append(
                    types.FunctionResponse(
                        id=fc.id,
                        name=function_name,
                        response={"result": result}
                    )
                )
                
                # Notify UI that tool completed
                await self.send_tool_notification(function_name, "completed", result)
                
                logger.info(f"  ✅ Tool {function_name} completed")
            
            # Send responses back to Gemini - use correct Live API method
            await self.session.send(input={"function_responses": function_responses})
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            traceback.print_exc()
    
    async def stop_speaking(self):
        """Stop current Gemini response and clear audio queue"""
        logger.info("🛑 Stop button pressed")
        self.should_stop = True
        # Clear audio queue immediately
        cleared = 0
        while not self.audio_in_queue.empty():
            try:
                self.audio_in_queue.get_nowait()
                cleared += 1
            except asyncio.QueueEmpty:
                break
        logger.info(f"✅ Stopped speaking, cleared {cleared} chunks")
    
    async def listen_audio(self):
        """Receive audio from WebSocket and send to Gemini"""
        logger.info("🎤 Listening to client audio...")
        try:
            while True:
                message = await self.websocket.receive()
                
                # Check for stop command
                if "text" in message:
                    try:
                        data = json.loads(message["text"])
                        if data.get("type") == "stop":
                            await self.stop_speaking()
                            continue
                    except:
                        pass
                
                if "bytes" in message:
                    data = message["bytes"]
                    await self.out_queue.put({"data": data, "mime_type": "audio/pcm"})
        except WebSocketDisconnect:
            logger.info("Client disconnected")
            raise asyncio.CancelledError()
        except Exception as e:
            logger.error(f"Error receiving audio: {e}")
            raise asyncio.CancelledError()
    
    async def send_audio_to_gemini(self):
        """Send audio from queue to Gemini"""
        try:
            while True:
                audio_data = await self.out_queue.get()
                await self.session.send(input=audio_data)
        except Exception as e:
            logger.error(f"Error sending to Gemini: {e}")
    
    async def receive_audio(self):
        """Receive audio and handle tool calls from Gemini Live"""
        logger.info("🔊 Starting response processing...")
        try:
            while True:
                turn = self.session.receive()
                
                async for response in turn:
                    # Handle audio data - stream immediately for low latency
                    if data := response.data:
                        self.audio_in_queue.put_nowait(data)
                    
                    # Handle tool calls in background to not block audio
                    if hasattr(response, 'tool_call') and response.tool_call:
                        # Process tool call without blocking audio stream
                        asyncio.create_task(self.handle_tool_call(response.tool_call))
                        
        except Exception as e:
            logger.error(f"Error receiving audio: {e}")
            traceback.print_exc()
    
    async def play_audio(self):
        """Send audio from queue to WebSocket"""
        logger.info("🔊 Streaming to client...")
        try:
            while True:
                bytestream = await self.audio_in_queue.get()
                await self.websocket.send_bytes(bytestream)
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
    
    async def run_with_session(self):
        """
        Run voice handler with a PRE-CONNECTED session.
        This is called when using the two-phase connection (session already connected).
        """
        logger.info(f"🎵 Starting voice session with pre-connected Gemini for patient {self.patient_id}")
        
        try:
            # Session is already connected - just notify UI and start tasks
            await self.send_status_to_ui("connected", "Voice agent ready (pre-connected)")
            
            # Load patient context
            logger.info(f"Loading patient context for voice session...")
            self.context_data = canvas_ops.get_board_items()
            
            # Ensure queues are set
            if self.audio_in_queue is None:
                self.audio_in_queue = asyncio.Queue()
            if self.out_queue is None:
                self.out_queue = asyncio.Queue(maxsize=10)
            
            logger.info("🔗 Using pre-connected Gemini Live API session!")
            
            # Start concurrent tasks
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self.send_audio_to_gemini())
                tg.create_task(self.listen_audio())
                tg.create_task(self.receive_audio())
                tg.create_task(self.play_audio())
                
                # Keep alive until disconnect
                await asyncio.Future()
                
        except asyncio.CancelledError:
            logger.info("✅ Voice session ended (pre-connected)")
        except Exception as e:
            logger.error(f"❌ Voice session error: {type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                await self.send_status_to_ui("error", f"Voice session error: {str(e)}")
            except:
                pass
        finally:
            logger.info("🧹 Cleanup completed (pre-connected session)")
    
    async def run(self):
        """Main run loop with concurrent tasks"""
        logger.info(f"🎵 Starting voice session for patient {self.patient_id}")
        
        # IMMEDIATELY tell browser we're starting - prevents browser timeout
        await self.send_status_to_ui("connecting", "Initializing voice agent...")
        
        # Check environment variables before attempting connection
        api_key = os.getenv('GOOGLE_API_KEY')
        
        if api_key:
            logger.info(f"🔑 Using API Key authentication: {api_key[:10]}...{api_key[-4:]}")
        else:
            logger.error("❌ GOOGLE_API_KEY not found in environment!")
            await self.send_status_to_ui("error", "Missing GOOGLE_API_KEY")
            return
        
        try:
            # Send status update to keep browser alive
            await self.send_status_to_ui("connecting", "Loading patient context...")
            
            # Load patient context using canvas_ops (agent-2.9 way)
            logger.info(f"Loading patient context for voice session...")
            self.context_data = canvas_ops.get_board_items()
            
            # Send another status update
            await self.send_status_to_ui("connecting", "Preparing configuration...")
            
            # TEMPORARY: Use minimal config for faster connection testing
            config = {
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {"prebuilt_voice_config": {"voice_name": "Charon"}}
                }
            }
            
            logger.info(f"✅ Voice session configured (minimal config for testing)")
            
            # Send status update - connecting to API
            await self.send_status_to_ui("connecting", "Connecting to Gemini Live API...")
            
            # Connect to Gemini Live API with increased timeout
            logger.info(f"🔌 Attempting to connect to Gemini Live API...")
            logger.info(f"   Model: {MODEL}")
            logger.info(f"   Auth: API Key")
            
            # Send status right before client init
            await self.send_status_to_ui("connecting", "Initializing Gemini client...")
            
            # Initialize client lazily (only when needed)
            client = self._get_client()
            
            # Send status right before connection
            await self.send_status_to_ui("connecting", "Establishing connection (this may take 30-60 seconds)...")
            
            # Create a heartbeat task to keep browser alive during connection
            async def send_heartbeat():
                """Send periodic status updates to keep browser WebSocket alive"""
                for i in range(60):  # Up to 60 seconds
                    await asyncio.sleep(1)
                    try:
                        await self.send_status_to_ui("connecting", f"Connecting... ({i+1}s)")
                    except:
                        break  # Connection established or failed
            
            # Start heartbeat and connection in parallel
            heartbeat_task = asyncio.create_task(send_heartbeat())
            
            try:
                # Connect directly - the websocket patch handles timeout (120s)
                logger.info(f"⏱️ Connecting to Gemini Live API...")
                logger.info(f"   Config: {config.get('response_modalities')} modalities")
                logger.info("   Calling client.aio.live.connect()...")
                
                async with (
                    client.aio.live.connect(
                        model=MODEL, 
                        config=config
                    ) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    # Cancel heartbeat once connected
                    heartbeat_task.cancel()
                    
                    self.session = session
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue = asyncio.Queue(maxsize=10)
                    
                    logger.info("🔗 Connected to Gemini Live API successfully!")
                    
                    # Notify UI that voice is ready
                    await self.send_status_to_ui("connected", "Voice agent connected and ready")
                    
                    # Start concurrent tasks
                    tg.create_task(self.send_audio_to_gemini())
                    tg.create_task(self.listen_audio())
                    tg.create_task(self.receive_audio())
                    tg.create_task(self.play_audio())
                    
                    # Keep alive until disconnect
                    await asyncio.Future()
            except asyncio.CancelledError:
                # Heartbeat cancelled, this is normal
                pass
                
        except asyncio.CancelledError:
            logger.info("✅ Voice session ended")
        except (TimeoutError, asyncio.TimeoutError) as e:
            logger.error(f"❌ Voice session timeout: {e}")
            logger.error(f"   Possible causes: Network issues, firewall, model access")
            try:
                await self.send_status_to_ui("error", f"Connection timeout: {str(e)}")
            except:
                pass
        except Exception as e:
            logger.error(f"❌ Voice session error: {type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                await self.send_status_to_ui("error", f"Voice session error: {str(e)}")
            except:
                pass
        finally:
            logger.info("🧹 Cleanup completed")
