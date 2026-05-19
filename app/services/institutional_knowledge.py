import json
import re
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "institutional_knowledge.json"
_CACHE = None

_TIME_SENSITIVE_MARKERS = (
    "current",
    "currently",
    "latest",
    "recent",
    "now",
    "today",
    "this year",
    "calendar",
    "status",
    "fees",
    "school fees",
    "cut off",
    "cut-off",
    "admission",
    "officer",
    "registrar",
    "bursar",
    "rank",
)

_PORTAL_ALIASES = {
    "student_erp": ("erp", "student portal", "payment portal", "fees portal"),
    "admissions": ("admission portal", "admissions portal", "apply", "application portal"),
    "postgraduate": ("postgraduate portal", "pg portal", "masters portal", "phd portal"),
    "online_learning": ("online learning", "elearning", "e learning", "learning portal", "lms"),
    "transcript": ("transcript", "transcript portal", "records portal"),
    "library_catalogue": ("library", "library catalogue", "catalogue"),
}

_PROGRAM_ALIASES = {
    "medicine": "Medicine & Surgery",
    "medicine and surgery": "Medicine & Surgery",
    "law": "Law",
    "nursing": "Nursing",
    "nursing science": "Nursing",
    "nursing sciences": "Nursing",
    "architecture": "Architecture",
    "computer science": "Computer Science",
    "education": "Education",
}

_EXTERNAL_LEADERSHIP_ALIASES = {
    "president_of_nigeria": ("president of nigeria", "nigerian president", "president tinubu"),
    "pope": ("pope", "holy father"),
    "governor_of_enugu_state": ("governor of enugu", "enugu governor", "governor of enugu state"),
    "minister_of_education": ("minister of education", "education minister"),
    "executive_secretary_nuc": ("executive secretary nuc", "nuc executive secretary", "head of nuc", "national universities commission"),
}


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s&]", " ", (text or "").lower())
    cleaned = cleaned.replace("&", " and ")
    return " ".join(cleaned.split())


def _contains_any(normalized, phrases):
    return any(_normalize(phrase) in normalized for phrase in phrases)


def _natural_join(items):
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _needs_freshness_prefix(question):
    normalized = _normalize(question)
    return _contains_any(normalized, _TIME_SENSITIVE_MARKERS)


def _fresh_prefix(question):
    return "Based on the latest information available to me, " if _needs_freshness_prefix(question) else ""


def _name_title(record):
    if not isinstance(record, dict):
        return "", ""
    return str(record.get("name") or "").strip(), str(record.get("title") or "").strip()


def _person_line(label, record):
    name, title = _name_title(record)
    if not name:
        return ""
    return f"{label}: {name}" + (f" ({title})" if title else "")


def _faculty_dean_line(record):
    if not isinstance(record, dict):
        return ""
    name = str(record.get("name") or "").strip()
    faculty = str(record.get("faculty") or "").strip()
    status = str(record.get("status") or "Dean").strip()
    if not name or not faculty:
        return ""
    return f"{faculty}: {name}" + (f" - {status}" if status and status != "Dean" else "")


def _office_freshness(record):
    return str((record or {}).get("confidence") or "semi_dynamic").strip() or "semi_dynamic"


def _office_prefix(record, verified_phrase="As of the latest verified university information available to me"):
    if _office_freshness(record) == "verified_current":
        return verified_phrase
    return "From the latest information available to me"


def load_institutional_knowledge():
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    try:
        with DATA_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}

    _CACHE = data if isinstance(data, dict) else {}
    return _CACHE


def _response(intent, category, reply, confidence=1.0, freshness=None):
    return {
        "handled": True,
        "source": "institutional_knowledge",
        "intent": intent,
        "category": category,
        "reply": reply,
        "confidence": confidence,
        "matched_question": None,
        "fallback": False,
        "freshness": freshness or "stable",
        "use_llm": False,
    }


def _find_program_cutoff(question, cutoffs):
    normalized = _normalize(question)
    for alias, canonical in sorted(_PROGRAM_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in normalized and canonical in cutoffs:
            return canonical, cutoffs[canonical]
    return None, None


def _resolve_pioneer_management_query(normalized, data):
    if not _contains_any(
        normalized,
        (
            "pioneer staff",
            "pioneer management",
            "pioneer officers",
            "take off staff",
            "takeoff staff",
            "first staff",
            "earliest staff",
            "earliest management",
        ),
    ):
        return None

    historical = data.get("historical_pioneer_management") or {}
    officers = historical.get("available_officers") or []
    lines = [
        "The last verified university records available to me show the earliest documented pioneer structure of Godfrey Okoye University around these key roles:"
    ]
    for officer in officers:
        name = str(officer.get("name") or "").strip()
        position = str(officer.get("position") or "").strip()
        if name and position:
            lines.append(f"{name} - {position}")

    note = str(historical.get("summary") or "").strip()
    if note:
        lines.append("")
        lines.append(note)

    return _response(
        "pioneer_management",
        "university_profile",
        "\n".join(lines).strip(),
        confidence=0.74,
        freshness="historical_available",
    )


def _resolve_external_leadership_query(question, data):
    normalized = _normalize(question)
    external = data.get("external_leadership") or {}
    if not external:
        return None

    for key, aliases in _EXTERNAL_LEADERSHIP_ALIASES.items():
        if _contains_any(normalized, aliases):
            record = external.get(key) or {}
            name, title = _name_title(record)
            if not name or not title:
                return None
            return _response(
                key,
                "external_leadership",
                f"As of the latest verified information available to me, the {title} is {name}.",
                confidence=0.92,
                freshness="semi_dynamic",
            )

    return None


def _resolve_portal_query(question, data):
    normalized = _normalize(question)
    if not _contains_any(normalized, ("portal", "erp", "transcript", "online learning", "elearning", "library catalogue")):
        return None

    portals = data.get("portals") or {}
    for key, aliases in _PORTAL_ALIASES.items():
        if _contains_any(normalized, aliases):
            label = key.replace("_", " ").title()
            if key == "student_erp":
                label = "Student ERP Portal"
            elif key == "online_learning":
                label = "Online Learning Platform"
            elif key == "library_catalogue":
                label = "Library Catalogue"
            url = portals.get(key)
            if url:
                if key == "transcript":
                    reply = f"Transcript requests and academic records are handled through the Exams & Records Unit. Use the Transcript Portal: {url}"
                else:
                    reply = f"{label}: {url}"
                return _response(
                    f"{key}_portal",
                    "portals",
                    reply,
                    confidence=1.0,
                    freshness="stable",
                )

    lines = [
        f"Student ERP: {portals.get('student_erp')}",
        f"Admissions: {portals.get('admissions')}",
        f"Postgraduate: {portals.get('postgraduate')}",
        f"Transcript: {portals.get('transcript')}",
        f"Online Learning: {portals.get('online_learning')}",
        f"Library Catalogue: {portals.get('library_catalogue')}",
    ]
    return _response("portal_overview", "portals", "\n".join(line for line in lines if not line.endswith("None")))


def _resolve_office_holder(question, data):
    normalized = _normalize(question)
    offices = data.get("offices") or {}

    if _contains_any(normalized, ("tell me about the vc", "tell me about vc", "tell me about the vice chancellor", "about the vice chancellor", "about christian anieke")):
        vc = offices.get("vice_chancellor") or {}
        name = vc.get("name", "Rev. Fr. Prof. Dr. Christian Anieke")
        notes = vc.get("notes") or []
        note_text = _natural_join([note for note in notes if "verified" not in _normalize(note)])
        reply = (
            f"{name} is the verified current Vice-Chancellor of Godfrey Okoye University. "
            "He is significant in the university's history because he is closely associated with its founding, Catholic educational mission, and institutional development. "
            f"University records available to me also identify him as {note_text}."
        )
        return _response("vice_chancellor_profile", "offices", reply, confidence=1.0, freshness=vc.get("confidence", "verified_current"))

    if _contains_any(normalized, ("who is the vc", "who is vc", "vice chancellor", "vc of gouni", "vc of godfrey")) and not _contains_any(normalized, ("contact", "email", "phone", "call")):
        vc = offices.get("vice_chancellor") or {}
        return _response(
            "vice_chancellor",
            "offices",
            f"The Vice-Chancellor of Godfrey Okoye University is {vc.get('name', 'Rev. Fr. Prof. Dr. Christian Anieke')}.",
            confidence=1.0,
            freshness=vc.get("confidence", "verified_current"),
        )

    if "registrar" in normalized:
        registrar = offices.get("registrar") or {}
        name = registrar.get("name")
        if name:
            prefix = _office_prefix(registrar)
            return _response(
                "registrar",
                "offices",
                f"{prefix}, {name} is the Registrar of Godfrey Okoye University.",
                confidence=0.95,
                freshness=_office_freshness(registrar),
            )

    if "bursar" in normalized:
        bursar = offices.get("bursar") or {}
        name = bursar.get("name")
        if name:
            prefix = _office_prefix(bursar, verified_phrase="As of the latest verified university records available to me")
            return _response(
                "bursar",
                "offices",
                f"{prefix}, {name} is the Bursar of Godfrey Okoye University.",
                confidence=0.95,
                freshness=_office_freshness(bursar),
            )

    return None


def _resolve_dean_query(question, data):
    normalized = _normalize(question)
    deans = data.get("deans_of_faculties") or {}
    
    # Check for dean queries
    dean_keywords = ("dean", "head of faculty", "faculty dean", "who heads")
    if not _contains_any(normalized, dean_keywords):
        return None

    if _contains_any(normalized, ("deans", "deans of faculties", "faculty deans", "all deans", "list deans")):
        lines = ["As of the latest verified university records available to me, the faculty and school leadership includes:"]
        for key in (
            "postgraduate_studies",
            "basic_medical_sciences",
            "arts_and_education",
            "law",
            "management_and_social_sciences",
            "natural_sciences",
            "computing_and_it",
            "basic_clinical_sciences",
            "student_affairs_thinkers",
            "student_affairs_main",
        ):
            line = _faculty_dean_line(deans.get(key) or {})
            if line:
                lines.append(line)
        return _response("deans_overview", "governance", "\n".join(lines), confidence=0.95, freshness="verified_current")
    
    # Map faculty name variations to structured keys
    faculty_mappings = {
        "computing": "computing_and_it",
        "facit": "computing_and_it",
        "computer science": "computing_and_it",
        "ict": "computing_and_it",
        "law": "law",
        "management": "management_and_social_sciences",
        "social sciences": "management_and_social_sciences",
        "natural sciences": "natural_sciences",
        "environmental": "natural_sciences",
        "postgraduate": "postgraduate_studies",
        "arts": "arts_and_education",
        "education": "arts_and_education",
        "basic medical": "basic_medical_sciences",
        "basic clinical": "basic_clinical_sciences",
        "clinical": "basic_clinical_sciences",
        "student affairs": "student_affairs_main",
        "main campus": "student_affairs_main",
        "thinkers": "student_affairs_thinkers",
    }
    
    # Find which faculty the question is about
    for keyword, key in faculty_mappings.items():
        if keyword in normalized:
            dean_info = deans.get(key) or {}
            name = dean_info.get("name")
            faculty = dean_info.get("faculty")
            status = dean_info.get("status", "Dean")
            
            if name and faculty:
                prefix = "As of the latest verified university records available to me"
                return _response(
                    f"dean_{key}",
                    "governance",
                    f"{prefix}, the {status} of the {faculty} is {name}.",
                    confidence=0.95,
                    freshness="verified_current",
                )
    
    return None


def _resolve_hod_query(question, data):
    normalized = _normalize(question)
    hods = data.get("heads_of_departments") or {}
    
    # Check for HOD queries
    hod_keywords = ("hod", "head of department", "department head", "heads the", "heads")
    if not _contains_any(normalized, hod_keywords):
        return None

    if _contains_any(normalized, ("hods", "all hod", "heads of departments", "list hod", "departmental heads")):
        lines = ["As of the latest verified university records available to me, these are the available Heads of Departments:"]
        for faculty_key, departments in hods.items():
            if not isinstance(departments, dict):
                continue
            faculty_label = faculty_key.replace("_", " ").title()
            lines.append("")
            lines.append(faculty_label + ":")
            for dept_name, hod_name in departments.items():
                lines.append(f"{dept_name}: {hod_name}")
        return _response("hods_overview", "governance", "\n".join(lines).strip(), confidence=0.95, freshness="verified_current")
    
    # Search through all faculties and their departments
    for faculty_key, departments in hods.items():
        if isinstance(departments, dict):
            for dept_name, hod_name in departments.items():
                normalized_dept = _normalize(dept_name)
                if _normalize(dept_name) in normalized or any(
                    len(part) > 4 and part in normalized for part in normalized_dept.split()
                ):
                    return _response(
                        f"hod_{_normalize(dept_name).replace(' ', '_')}",
                        "governance",
                        f"As of the latest verified university information available to me, {hod_name} heads the {dept_name} department.",
                        confidence=0.95,
                        freshness="verified_current",
                    )
    
    return None


def _resolve_principal_officers_query(question, data):
    normalized = _normalize(question)
    officers = data.get("principal_officers") or {}

    if _contains_any(normalized, ("principal officers", "management team", "university management", "top officers", "principal officer")):
        labels = (
            ("Vice-Chancellor", "vice_chancellor"),
            ("Deputy Vice-Chancellor (Administration)", "deputy_vice_chancellor_administration"),
            ("Deputy Vice-Chancellor (Academic)", "deputy_vice_chancellor_academic"),
            ("Registrar", "registrar"),
            ("Bursar", "bursar"),
            ("University Librarian", "librarian"),
        )
        lines = ["As of the latest verified university information available to me, the principal officers of Godfrey Okoye University include:"]
        for label, key in labels:
            name = str((officers.get(key) or {}).get("name") or "").strip()
            if name:
                lines.append(f"{label}: {name}")
        return _response("principal_officers", "governance", "\n".join(lines), confidence=0.95, freshness="verified_current")
    
    # Check for DVC queries
    if _contains_any(normalized, ("deputy vice chancellor", "dvc", "dvc admin", "dvc academic")):
        if _contains_any(normalized, ("admin", "administration")):
            dvc = officers.get("deputy_vice_chancellor_administration") or {}
        elif _contains_any(normalized, ("academic", "academics")):
            dvc = officers.get("deputy_vice_chancellor_academic") or {}
        else:
            # List both DVCs
            dvc_admin = officers.get("deputy_vice_chancellor_administration") or {}
            dvc_acad = officers.get("deputy_vice_chancellor_academic") or {}
            admin_name = dvc_admin.get("name", "")
            acad_name = dvc_acad.get("name", "")
            if admin_name and acad_name:
                reply = (
                    f"As of the latest verified university information available to me:\n"
                    f"DVC (Administration): {admin_name}\n"
                    f"DVC (Academic): {acad_name}"
                )
                return _response("dvc_overview", "governance", reply, confidence=0.95, freshness="verified_current")
            return None
        
        name = dvc.get("name")
        if name:
            label = "Deputy Vice-Chancellor"
            if _contains_any(normalized, ("admin", "administration")):
                label = "Deputy Vice-Chancellor (Administration)"
            elif _contains_any(normalized, ("academic", "academics")):
                label = "Deputy Vice-Chancellor (Academic)"
            return _response("deputy_vice_chancellor", "governance", f"As of the latest verified university information available to me, {name} is the {label}.", confidence=0.95, freshness="verified_current")
    
    # Check for Librarian
    if _contains_any(normalized, ("librarian", "library director")):
        librarian = officers.get("librarian") or {}
        name = librarian.get("name")
        if name:
            return _response("librarian", "governance", f"As of the latest verified university information available to me, {name} is the University Librarian.", confidence=0.95, freshness="verified_current")
    
    return None


def _resolve_college_of_medicine_query(question, data):
    normalized = _normalize(question)
    college = data.get("college_of_medicine") or {}
    if not _contains_any(normalized, ("college of medicine", "provost", "deputy provost", "chief medical director", "cmd", "clinical medicine")):
        return None

    if _contains_any(normalized, ("deputy provost",)):
        name = str(college.get("deputy_provost") or "").strip()
        if name:
            return _response("college_deputy_provost", "governance", f"As of the latest verified university information available to me, the Deputy Provost of the College of Medicine is {name}.", confidence=0.95, freshness="verified_current")

    if _contains_any(normalized, ("chief medical director", "cmd", "clinical medicine", "dean of clinical medicine")):
        name = str(college.get("chief_medical_director") or "").strip()
        if name:
            return _response("cmd_dean_clinical_medicine", "governance", f"As of the latest verified university information available to me, the Chief Medical Director / Dean of Clinical Medicine is {name}.", confidence=0.95, freshness="verified_current")

    if _contains_any(normalized, ("provost", "college of medicine leadership", "college of medicine management")):
        provost = str(college.get("provost") or "").strip()
        deputy = str(college.get("deputy_provost") or "").strip()
        cmd = str(college.get("chief_medical_director") or "").strip()
        lines = ["As of the latest verified university information available to me, the College of Medicine leadership includes:"]
        if provost:
            lines.append(f"Provost: {provost}")
        if deputy:
            lines.append(f"Deputy Provost: {deputy}")
        if cmd:
            lines.append(f"Chief Medical Director / Dean of Clinical Medicine: {cmd}")
        return _response("college_of_medicine_leadership", "governance", "\n".join(lines), confidence=0.95, freshness="verified_current")

    return None


def _resolve_governance_query(question, data):
    normalized = _normalize(question)
    governance = data.get("governance") or {}
    bot = data.get("board_of_trustees") or []

    if _contains_any(normalized, ("governance structure", "management hierarchy", "university hierarchy", "leadership structure", "governance of gouni")):
        lines = ["From the latest information available to me, Godfrey Okoye University's governance structure can be understood in layers:"]
        for label, key in (
            ("Proprietor / Promoter", "proprietor"),
            ("Chancellor", "chancellor"),
            ("Chairman, Board of Trustees", "chairman_bot"),
            ("Pro-Chancellor & Chairman, Governing Council", "pro_chancellor"),
        ):
            line = _person_line(label, governance.get(key) or {})
            if line:
                lines.append(line)
        lines.append("The Vice-Chancellor leads the day-to-day academic and administrative direction of the university, supported by principal officers, deans, provosts, directors, and heads of departments.")
        lines.append("The Senate functions as the core academic authority, but the full current Senate membership is not included in the verified structured records available to me.")
        return _response("governance_structure", "governance", "\n".join(lines), confidence=0.92, freshness="semi_dynamic")

    if _contains_any(normalized, ("senate", "university senate")):
        reply = (
            "From the latest information available to me, the University Senate is the central academic authority for matters such as academic policy, programmes, examinations, and academic standards. "
            "The full current Senate membership is not included in the verified structured records available to me, so I should not invent names for it."
        )
        return _response("university_senate", "governance", reply, confidence=0.78, freshness="semi_dynamic")
    
    # Check for BOT queries
    if _contains_any(normalized, ("board of trustees", "bot", "board members", "trustees")):
        if _contains_any(normalized, ("chairman", "chair")):
            chairman = governance.get("chairman_bot") or {}
            name = chairman.get("name")
            if name:
                return _response("bot_chairman", "governance", f"As of the latest verified university information available to me, {name} is the Chairman of the Board of Trustees.", confidence=0.95, freshness="verified_current")
        
        # List all BOT members
        if bot:
            lines = ["As of the latest verified university information available to me, the Board of Trustees comprises:"]
            for member in bot:
                name = member.get("name")
                role = member.get("role", "Member")
                if name:
                    lines.append(f"{name} - {role}")
            
            return _response("bot_members", "governance", "\n".join(lines), confidence=0.95, freshness="verified_current")
    
    # Check for Chancellor/Proprietor
    if _contains_any(normalized, ("pro chancellor", "pro-chancellor", "governing council")):
        pro_chancellor = governance.get("pro_chancellor") or {}
        name, title = _name_title(pro_chancellor)
        if name:
            return _response("pro_chancellor", "governance", f"As of the latest verified university information available to me, {name} is the {title or 'Pro-Chancellor and Chairman of Governing Council'} of GOUNI.", confidence=0.95, freshness="verified_current")

    if _contains_any(normalized, ("chancellor", "proprietor", "bishop", "promoter")):
        if _contains_any(normalized, ("proprietor", "owner", "promoter")):
            proprietor = governance.get("proprietor") or {}
            name = proprietor.get("name")
            title = proprietor.get("title")
            if name:
                return _response("proprietor", "governance", f"As of the latest verified university information available to me, {name}, {title}, is the Proprietor / Promoter of GOUNI.", confidence=0.95, freshness="verified_current")
        
        if _contains_any(normalized, ("chancellor",)):
            chancellor = governance.get("chancellor") or {}
            name = chancellor.get("name")
            title = chancellor.get("title")
            if name:
                return _response("chancellor", "governance", f"As of the latest verified university information available to me, {name}, {title}, is the Chancellor of GOUNI.", confidence=0.95, freshness="verified_current")
    
    return None


def resolve_institutional_query(question):
    data = load_institutional_knowledge()
    if not data:
        return {"handled": False}

    normalized = _normalize(question)
    if not normalized:
        return {"handled": False}

    pioneer_result = _resolve_pioneer_management_query(normalized, data)
    if pioneer_result:
        return pioneer_result

    external_result = _resolve_external_leadership_query(question, data)
    if external_result:
        return external_result

    office_result = _resolve_office_holder(question, data)
    if office_result:
        return office_result
    
    # New governance handlers with high priority
    principal_officers_result = _resolve_principal_officers_query(question, data)
    if principal_officers_result:
        return principal_officers_result

    college_result = _resolve_college_of_medicine_query(question, data)
    if college_result:
        return college_result
    
    governance_result = _resolve_governance_query(question, data)
    if governance_result:
        return governance_result
    
    dean_result = _resolve_dean_query(question, data)
    if dean_result:
        return dean_result
    
    hod_result = _resolve_hod_query(question, data)
    if hod_result:
        return hod_result

    portal_result = _resolve_portal_query(question, data)
    if portal_result:
        return portal_result

    profile = data.get("university_profile") or {}
    admissions = data.get("admissions") or {}
    fees = data.get("fees") or {}

    if _contains_any(normalized, ("motto", "unity of knowledge")):
        return _response("university_motto", "university_profile", f"GOUNI's motto is \"{profile.get('motto', 'Unity of Knowledge')}\".")

    if _contains_any(normalized, ("who founded", "founder", "founded gouni", "founded godfrey")):
        return _response("university_founder", "university_profile", profile.get("founding_note", "Godfrey Okoye University became operational after receiving its NUC licence in 2009."))

    if _contains_any(normalized, ("when was", "established", "founded in", "founding year")) and _contains_any(normalized, ("gouni", "godfrey", "university")):
        return _response("university_established", "university_profile", f"Godfrey Okoye University was established on {profile.get('established', '3 November 2009')}.")

    if _contains_any(normalized, ("catholic", "owned by", "ownership", "identity", "what is gouni", "about gouni", "about godfrey okoye university", "tell me about godfrey okoye university", "first catholic")):
        reply = (
            f"Godfrey Okoye University is a {profile.get('type', 'private Catholic university')} "
            f"owned by the {profile.get('ownership', 'Catholic Diocese of Enugu')}. "
            f"It was founded in 2009, carries the motto \"{profile.get('motto', 'Unity of Knowledge')}\", and is historically recognized as the {profile.get('distinction', 'first university owned by a Catholic Diocese in Africa')}. "
            "Its academic identity combines professional training with Catholic moral formation, ethical leadership, research, and service. "
            f"Major academic areas include {_natural_join((data.get('faculties') or [])[:8])}."
        )
        return _response("university_identity", "university_profile", reply)

    if _contains_any(normalized, ("campus", "campuses", "thinkers", "ugwuomu")):
        return _response("campuses", "university_profile", f"GOUNI operates across {_natural_join(profile.get('campuses') or [])}.")

    if _contains_any(normalized, ("installment", "instalment", "pay school fees in installments", "pay fees in installments", "60", "40")):
        return _response("fee_installment_rule", "fees", fees.get("installment_rule", ""), confidence=0.95, freshness="policy")

    if _contains_any(normalized, ("personal account", "payment rule", "how do i pay", "pay fees", "school fees", "erp payment")):
        prefix = _fresh_prefix(question)
        reply = f"{prefix}{fees.get('payment_rule', '')} ERP Portal: {fees.get('erp_portal')}."
        return _response("fees_payment_rule", "fees", reply, confidence=0.9, freshness="semi_dynamic")

    if _contains_any(normalized, ("cut off", "cut-off", "jamb score", "jamb mark", "admission mark")):
        cutoffs = admissions.get("cut_off_marks") or {}
        program, mark = _find_program_cutoff(question, cutoffs)
        if program and mark:
            return _response(
                f"{_normalize(program).replace(' ', '_')}_cutoff",
                "admissions",
                f"Based on the latest information available to me, the JAMB cut-off mark for {program} is {mark}. Cut-off marks may change by admission cycle.",
                confidence=0.92,
                freshness="semi_dynamic",
            )
        lines = [f"{program}: {mark}" for program, mark in cutoffs.items()]
        return _response(
            "cutoff_overview",
            "admissions",
            "Based on the latest information available to me, the published JAMB cut-off marks include:\n" + "\n".join(lines),
            confidence=0.86,
            freshness="semi_dynamic",
        )

    if _contains_any(normalized, ("admission", "apply", "application", "o level", "olevel", "screening")):
        reply = (
            f"{admissions.get('status_note', 'Admissions information may change by cycle')} "
            f"General requirement: {admissions.get('general_requirement')} "
            f"Apply through: {admissions.get('application_portal')}."
        )
        return _response("admissions_overview", "admissions", reply, confidence=0.88, freshness="semi_dynamic")

    if _contains_any(normalized, ("transcript", "records", "credential verification")):
        records = data.get("exams_records") or {}
        reply = (
            f"Transcript and academic record matters are handled by the {records.get('unit', 'Exams & Records Unit')} "
            f"under the {records.get('parent_office', 'Office of the Registrar')}. "
            f"Use the transcript portal: {records.get('transcript_portal')}."
        )
        return _response("transcript_records", "portals", reply, confidence=0.95, freshness="stable")

    if _contains_any(normalized, ("recent", "happening", "news", "announcement", "announcements", "events")):
        announcements = data.get("announcements") or []
        reply = "The last information available to me mentions recent GOUNI developments such as " + _natural_join(announcements) + "."
        return _response("recent_announcements", "announcements", reply, confidence=0.82, freshness="semi_dynamic")

    if _contains_any(normalized, ("ranking", "rankings", "recognition", "webometrics", "times higher")):
        rankings = data.get("rankings") or {}
        reply = rankings.get("summary", "")
        areas = rankings.get("recognition_areas") or []
        if areas:
            reply = f"{reply} Recognition areas include {_natural_join(areas)}."
        return _response("rankings", "rankings", reply, confidence=0.82, freshness="semi_dynamic")

    if _contains_any(normalized, ("accreditation", "accredited", "nuc", "council of legal education")):
        accreditation = data.get("accreditation") or {}
        return _response("accreditation", "accreditation", accreditation.get("summary", ""), confidence=0.84, freshness="semi_dynamic")

    if _contains_any(normalized, ("scholarship", "scholarships", "legacy project", "financial support")):
        scholarships = data.get("scholarships") or {}
        return _response("scholarships", "scholarships", scholarships.get("summary", ""), confidence=0.86, freshness="semi_dynamic")

    if _contains_any(normalized, ("postgraduate", "masters", "master", "phd", "pgd", "school of postgraduate")):
        pg = data.get("postgraduate_programmes") or {}
        reply = (
            f"The School of Postgraduate Studies offers {_natural_join(pg.get('levels') or [])}. "
            f"Programmes exist across areas such as {_natural_join((pg.get('areas') or [])[:8])}. "
            f"Postgraduate portal: {pg.get('portal')}."
        )
        return _response("postgraduate_programmes", "postgraduate_programmes", reply, confidence=0.9, freshness="stable")

    if _contains_any(normalized, ("teaching hospital", "gounith", "college of medicine", "medical school")):
        hospital = data.get("teaching_hospital") or {}
        reply = (
            f"{hospital.get('name', 'GOUNI Teaching Hospital')} is located at the {hospital.get('location', 'Ugwuomu-Nike campus')}. "
            f"The College of Medicine was formally established in {hospital.get('college_established', '2022')} and supports {_natural_join(hospital.get('supports') or [])}."
        )
        return _response("teaching_hospital", "facilities", reply, confidence=0.92, freshness="stable")

    if _contains_any(normalized, ("partnership", "partnerships", "collaboration", "collaborations", "international")):
        reply = "The last time I checked, GOUNI had collaborations with " + _natural_join(data.get("partnerships") or []) + "."
        return _response("partnerships", "partnerships", reply, confidence=0.84, freshness="semi_dynamic")

    if _contains_any(normalized, ("directorate", "directorates", "units")):
        return _response("directorates", "directorates", f"Key directorates include {_natural_join(data.get('directorates') or [])}.", confidence=0.9)

    if _contains_any(normalized, ("facilities", "atm", "radio", "library", "campus services")):
        return _response("facilities", "facilities", f"Campus facilities include {_natural_join(data.get('facilities') or [])}.", confidence=0.9)

    if _contains_any(normalized, ("faculties", "faculty list", "list faculties", "schools", "academic faculties")):
        return _response(
            "faculties",
            "faculties",
            f"As of the latest verified university information available to me, GOUNI's major faculties and schools include {_natural_join(data.get('faculties') or [])}.",
            confidence=0.95,
            freshness="semi_dynamic",
        )

    return {"handled": False}
