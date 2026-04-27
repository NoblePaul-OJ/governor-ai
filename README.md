# University Support Assistant - Prototype 1

## Project Title
Development of an AI-Powered Chatbot System for Student Support and Administrative Services in African Universities

## Student
- Name: Paul- Ojimadu, Noble. C
- Department: Computer Science
- Institution: Godfrey Okoye University
- Supervisor: Dr. S. C. Echezona

## Current Phase (Simple Frontend + Backend)
This phase delivers a clean web chatbot interface and a simple supervised backend.
No full knowledge base integration yet.

### Frontend
- Landing page with project context
- Chat interface page with timestamps and typing indicator

### Backend
- `POST /api/chat` for rule-based intent response
- `GET /api/intents` to show current support domains
- `GET /api/logs` for prototype query logs
- Structured university contact directory (`contactDirectory.json`) with:
  - `office_name`
  - `description`
  - `email`
  - `phone`
  - `location`
- Contact lookup flow for prompts like: `How do I contact ...?`
  - Returns exact official contact details from the directory
- Task-oriented interaction layer for:
  - `hostel booking`
  - `VC appointment`
  - `contact request`
  - `complaints/issues`
  - `transcript request`
- Guided workflow format for task conversations:
  - `Step 1` collect information
  - `Step 2` guide action
  - `Step 3` finalize with clear next actions
- Session state tracking includes current workflow step (`step_1`, `step_2`, `step_3` completion output)
- Final output generation as request summary or email draft, depending on workflow
- Optional SQLite persistence for completed task requests (`TASK_DB_ENABLED=1`)

### Admin Task Request Views
- `GET /admin/task-requests` to view saved task workflow submissions
- `GET /admin/task-requests.json` to fetch saved task workflow submissions as JSON

### Current Supported Domains
- Registration
- Fees & Payment
- Results/Records
- Admissions
- Hostel Allocation
- Academic Schedules
- Departmental Inquiries

## Run
1. Install dependencies:
   `pip install -r requirements.txt`
2. Start app:
   `python run.py`
3. Open:
   - Home: `http://127.0.0.1:5000/`
   - Chat: `http://127.0.0.1:5000/chat`
   - Admin dashboard: `http://127.0.0.1:5000/admin` (contains statistics, logs, keyword analytics and intent rule editor)

### Testing
A small pytest suite is provided to verify the rule engine, logging, keyword analysis, and API endpoints:

```bash
python -m pytest
```
## Note
The chatbot is supervised and rule-bound. It provides guidance and escalates to the appropriate office when needed.
