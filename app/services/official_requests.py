import re
from textwrap import dedent

from app.services.directory import get_contact


ISSUE_WORKFLOWS = {
    "ict_complaint": {
        "label": "ICT Complaint",
        "output_type": "request_summary",
        "office": "ICT Support",
        "keywords": [
            "portal login issue",
            "portal is not opening",
            "portal error",
            "portal issue",
            "login issue",
            "login problem",
            "login not working",
            "portal not working",
            "technical issue",
            "result checking issue",
            "result access issue",
            "registration issue",
            "portal not opening",
            "cannot login",
            "cant login",
            "can't login",
        ],
        "intro": "Alright, let us get the ICT issue clearly so it can be handled well.",
        "step_1_context": "First step: tell me the main ICT problem in one short sentence.",
        "fields": [
            {
                "key": "issue_summary",
                "label": "Issue Summary",
                "question": "What exactly is happening with the portal, login, or result page?",
                "aliases": ["issue", "problem", "summary", "what happened"],
            },
            {
                "key": "error_message",
                "label": "Error Message",
                "question": "What error message are you seeing, if any?",
                "aliases": ["error", "message", "problem message"],
            },
            {
                "key": "issue_started",
                "label": "When It Started",
                "question": "When did this problem start?",
                "aliases": ["started", "when", "date"],
            },
            {
                "key": "tried_steps",
                "label": "What You Tried",
                "question": "What browser, device, or steps have you already tried?",
                "aliases": ["tried", "browser", "device", "steps"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you want the formal complaint draft.",
        },
        "template_key": "ict_complaint",
        "request_subject": "ICT Complaint",
    },
    "bursary_payment_complaint": {
        "label": "Bursary Payment Complaint",
        "output_type": "request_summary",
        "office": "Bursary Unit",
        "keywords": [
            "payment not reflecting",
            "payment has not reflected",
            "payment not reflected",
            "school fees have not reflected",
            "school fees issue",
            "payment reflection",
            "payment problem",
            "payment issue",
            "school fees complaint",
            "school fees not reflecting",
            "fees have not reflected",
            "fees not reflected",
            "fee payment issue",
            "receipt problem",
            "clearance payment verification",
            "balance inquiry",
            "bursary issue",
            "bursary complaint",
        ],
        "intro": "Alright, let us capture the payment issue properly so Bursary can verify it.",
        "step_1_context": "First step: share the payment details so the complaint is specific.",
        "fields": [
            {
                "key": "issue_summary",
                "label": "Issue Summary",
                "question": "What is the payment problem or complaint?",
                "aliases": ["issue", "problem", "summary", "complaint"],
            },
            {
                "key": "payment_date",
                "label": "Payment Date",
                "question": "When was the payment made?",
                "aliases": ["date", "paid", "payment date"],
            },
            {
                "key": "payment_method",
                "label": "Payment Method",
                "question": "What payment method did you use?",
                "aliases": ["method", "channel", "bank", "transfer", "card"],
            },
            {
                "key": "receipt_status",
                "label": "Receipt or Reference",
                "question": "Do you have a receipt or transaction reference?",
                "aliases": ["receipt", "reference", "transaction", "rrr"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you want the formal complaint draft.",
        },
        "template_key": "bursary_payment_complaint",
        "request_subject": "Bursary Payment Complaint",
    },
    "registration_issue": {
        "label": "Registration Issue",
        "output_type": "request_summary",
        "office": "ICT Support",
        "keywords": [
            "registration issue",
            "course registration issue",
            "course registration problem",
            "registration problem",
            "register courses",
            "course form",
            "portal registration",
            "cannot register",
            "can't register",
            "cant register",
        ],
        "intro": "Alright, let us sort the registration issue out in a clear way.",
        "step_1_context": "First step: tell me exactly what happens when you try to register.",
        "fields": [
            {
                "key": "issue_summary",
                "label": "Issue Summary",
                "question": "What exactly is happening during registration?",
                "aliases": ["issue", "problem", "summary", "what happened"],
            },
            {
                "key": "issue_started",
                "label": "When It Started",
                "question": "When did the registration issue begin?",
                "aliases": ["started", "when", "date"],
            },
            {
                "key": "error_message",
                "label": "Error Message",
                "question": "What error message or page do you see, if any?",
                "aliases": ["error", "message", "page"],
            },
            {
                "key": "tried_steps",
                "label": "What You Tried",
                "question": "What have you already tried to fix it?",
                "aliases": ["tried", "browser", "device", "steps"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you want the formal complaint draft.",
        },
        "template_key": "registration_issue",
        "request_subject": "Registration Issue",
    },
    "result_access_issue": {
        "label": "Result Access Issue",
        "output_type": "request_summary",
        "office": "ICT Support",
        "keywords": [
            "result checking issue",
            "result access issue",
            "cannot check result",
            "can't check result",
            "cant check result",
            "result portal",
            "result not opening",
            "results not showing",
            "results issue",
        ],
        "intro": "Alright, let us capture the result access problem properly.",
        "step_1_context": "First step: tell me what happens when you try to check your result.",
        "fields": [
            {
                "key": "issue_summary",
                "label": "Issue Summary",
                "question": "What exactly is happening when you try to check the result?",
                "aliases": ["issue", "problem", "summary", "what happened"],
            },
            {
                "key": "issue_started",
                "label": "When It Started",
                "question": "When did this result issue start?",
                "aliases": ["started", "when", "date"],
            },
            {
                "key": "error_message",
                "label": "Error Message",
                "question": "What error message do you see, if any?",
                "aliases": ["error", "message", "page"],
            },
            {
                "key": "tried_steps",
                "label": "What You Tried",
                "question": "Have you tried another browser, device, or network?",
                "aliases": ["tried", "browser", "device", "steps"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you want the formal complaint draft.",
        },
        "template_key": "result_access_issue",
        "request_subject": "Result Access Issue",
    },
    "clearance_issue": {
        "label": "Clearance Issue",
        "output_type": "request_summary",
        "office": "Admissions Office",
        "keywords": [
            "clearance issue",
            "clearance problem",
            "clearance payment verification",
            "clearance complaint",
            "verification issue",
            "document clearance",
            "admission clearance",
        ],
        "intro": "Alright, let us put the clearance issue into a formal structure.",
        "step_1_context": "First step: tell me what kind of clearance problem you are facing.",
        "fields": [
            {
                "key": "issue_summary",
                "label": "Issue Summary",
                "question": "What exactly is the clearance problem?",
                "aliases": ["issue", "problem", "summary", "complaint"],
            },
            {
                "key": "clearance_type",
                "label": "Clearance Type",
                "question": "Is this payment clearance, document clearance, or something else?",
                "aliases": ["type", "clearance", "payment", "document"],
            },
            {
                "key": "issue_started",
                "label": "When It Started",
                "question": "When did this issue begin?",
                "aliases": ["started", "when", "date"],
            },
            {
                "key": "document_status",
                "label": "Document or Status",
                "question": "What document, payment proof, or status is still pending?",
                "aliases": ["document", "status", "proof", "receipt"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you want the formal complaint draft.",
        },
        "template_key": "clearance_issue",
        "request_subject": "Clearance Issue",
    },
}

ISSUE_TEMPLATE_LABELS = {
    "ict_complaint": "ICT complaint",
    "bursary_payment_complaint": "Bursary payment complaint",
    "registration_issue": "Registration issue",
    "result_access_issue": "Result access issue",
    "clearance_issue": "Clearance issue",
}

_NORMALIZED_TEMPLATE_ORDER = [
    "bursary_payment_complaint",
    "ict_complaint",
    "registration_issue",
    "result_access_issue",
    "clearance_issue",
]


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _title_case(value):
    return " ".join(part.capitalize() for part in str(value or "").replace("_", " ").split())


def _get_template(issue_type):
    if not issue_type:
        return {}
    return ISSUE_WORKFLOWS.get(str(issue_type).strip().lower(), {})


def _merge_profile_data(details):
    merged = dict(details or {})
    for key in ("name", "department", "level"):
        value = str(merged.get(key) or "").strip()
        if value:
            merged[key] = value
    return merged


def infer_issue_template(message):
    normalized = _normalize(message)
    if not normalized:
        return None

    best_key = None
    best_score = 0
    for workflow_key in _NORMALIZED_TEMPLATE_ORDER:
        payload = ISSUE_WORKFLOWS[workflow_key]
        for phrase in payload.get("keywords", []):
            phrase_n = _normalize(phrase)
            if not phrase_n:
                continue
            if phrase_n in normalized:
                score = len(phrase_n.split())
                if score > best_score:
                    best_score = score
                    best_key = workflow_key

    if not best_key:
        return None

    workflow = ISSUE_WORKFLOWS[best_key]
    return {
        "template_key": best_key,
        "label": workflow["label"],
        "office": workflow["office"],
        "request_subject": workflow.get("request_subject") or workflow["label"],
    }


def resolve_official_contact(unit_name):
    return get_contact(unit_name)


def _detail_sentences(issue_type, details):
    details = _merge_profile_data(details)
    sentences = []

    name = details.get("name")
    department = details.get("department")
    level = details.get("level")
    if name and department and level:
        sentences.append(f"My name is {name}, a {level} level {department} student.")
    elif name and department:
        sentences.append(f"My name is {name}, and I am in the {department} department.")
    elif name and level:
        sentences.append(f"My name is {name}, and I am a {level} level student.")
    elif name:
        sentences.append(f"My name is {name}.")

    template = _get_template(issue_type)
    issue_summary = str(
        details.get("issue_summary")
        or details.get("summary")
        or details.get("issue_details")
        or details.get("issue")
        or ""
    ).strip()
    if issue_summary:
        sentences.append(issue_summary.rstrip(".") + ".")
    elif template:
        sentences.append(f"I am writing regarding a {template['label'].lower()}.")

    specific_pairs = [
        ("error_message", "The error message is"),
        ("issue_started", "The issue started"),
        ("payment_date", "The payment was made on"),
        ("payment_method", "The payment method used was"),
        ("receipt_status", "Receipt or transaction reference"),
        ("tried_steps", "What I have already tried"),
        ("clearance_type", "This is a"),
        ("document_status", "The pending document or status is"),
    ]

    for key, prefix in specific_pairs:
        value = str(details.get(key) or "").strip()
        if not value:
            continue
        if key == "issue_started":
            sentences.append(f"{prefix} {value}.")
        elif key in {"payment_date", "payment_method", "receipt_status", "tried_steps", "clearance_type", "document_status", "error_message"}:
            sentences.append(f"{prefix}: {value}.")

    if template and template.get("office"):
        sentences.append(f"This should be reviewed by {template['office']}.")

    return sentences


def generate_issue_summary(issue_type, details):
    template = _get_template(issue_type)
    details = _merge_profile_data(details)
    subject = template.get("label") or _title_case(issue_type)
    sentences = [f"Issue type: {subject}."]
    sentences.extend(_detail_sentences(issue_type, details))
    return " ".join(sentence.strip() for sentence in sentences if sentence.strip())


def _format_contact_block(unit_name):
    contact = resolve_official_contact(unit_name)
    if not contact:
        return ""

    lines = []
    phones = contact.get("phones") if isinstance(contact.get("phones"), list) else []
    emails = contact.get("emails") if isinstance(contact.get("emails"), list) else []

    if contact.get("office_hours"):
        lines.append(f"Office hours: {contact['office_hours']}")
    if contact.get("preferred_contact_method"):
        lines.append(f"Preferred contact method: {contact['preferred_contact_method']}")
    if contact.get("whatsapp"):
        lines.append(f"WhatsApp: {contact['whatsapp']}")
    for phone in phones or ([contact["phone"]] if contact.get("phone") else []):
        lines.append(f"Phone: {phone}")
    for email in emails or ([contact["email"]] if contact.get("email") else []):
        lines.append(f"Email: {email}")
    handles = contact.get("handles") or contact.get("common_issue_types") or contact.get("common_issues")
    if isinstance(handles, list) and handles:
        lines.append(f"Handles: {', '.join(str(item).strip() for item in handles if str(item).strip())}")
    if contact.get("office"):
        lines.append(f"Office: {contact['office']}")
    return "\n".join(lines)


def generate_official_request(unit, issue_data):
    issue_data = _merge_profile_data(issue_data)
    template = _get_template(issue_data.get("issue_type")) or infer_issue_template(issue_data.get("issue_summary")) or {}
    recipient = str(unit or template.get("office") or issue_data.get("office") or "University Office").strip()
    subject = str(issue_data.get("subject") or template.get("request_subject") or recipient).strip()
    summary = generate_issue_summary(issue_data.get("issue_type"), issue_data)
    contact_block = _format_contact_block(recipient)

    lines = [
        f"Subject: {subject}",
        "",
        f"Dear {recipient},",
        "",
    ]

    name = issue_data.get("name")
    department = issue_data.get("department")
    level = issue_data.get("level")
    if name and department and level:
        lines.append(f"My name is {name}, a {level} level {department} student.")
    elif name and department:
        lines.append(f"My name is {name} from the {department} department.")
    elif name and level:
        lines.append(f"My name is {name}, and I am a {level} level student.")
    elif name:
        lines.append(f"My name is {name}.")

    lines.extend(
        [
            "",
            summary,
            "",
            "I kindly request your assistance in reviewing this matter and advising me on the next step.",
        ]
    )

    if contact_block:
        lines.extend(["", "Contact details", contact_block])

    lines.extend(["", "Thank you.", "", "Kind regards,", "Student"])

    return "\n".join(line.rstrip() for line in lines if line is not None).strip()


def build_issue_workflow_summary(issue_key, collected):
    template = _get_template(issue_key)
    issue_type = issue_key if issue_key in ISSUE_WORKFLOWS else str(collected.get("issue_type") or "").strip().lower()
    issue_summary = generate_issue_summary(issue_type or issue_key, collected)
    request = generate_official_request(template.get("office"), collected)
    return dedent(
        f"""
        Step 3
        Final summary for {template.get('label') or _title_case(issue_key)}

        Issue summary
        {issue_summary}

        Official request draft
        {request}
        """
    ).strip()
