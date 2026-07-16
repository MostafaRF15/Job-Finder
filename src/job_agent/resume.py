"""Extract text, skills, and target job titles from uploaded resumes."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from job_agent.validators import is_valid_address, is_valid_email, is_valid_phone

# #region agent log
_DEBUG_LOG = Path("/home/mostafa/.cursor/debug-6d9f2b.log")


def _dbg(hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": "6d9f2b",
            "runId": "cv-match",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with _DEBUG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


# #endregion

SKILL_LEXICON = [
    # IT Admin / infra
    "active directory", "windows server", "office 365", "microsoft 365", "exchange",
    "vmware", "hyper-v", "citrix", "sccm", "intune", "powershell", "bash",
    "cisco", "fortinet", "firewall", "vpn", "lan", "wan", "tcp/ip", "dns", "dhcp",
    "linux", "ubuntu", "centos", "redhat", "windows", "helpdesk", "itil",
    "backup", "veeam", "monitoring", "zabbix", "nagios", "virtualization",
    # Dev (still useful for dual profiles)
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "golang", "rust",
    "php", "html", "css", "react", "vue", "angular", "node.js", "nodejs",
    "django", "flask", "fastapi", "spring", "laravel",
    "sql", "mysql", "postgresql", "postgres", "mongodb", "redis",
    "docker", "kubernetes", "aws", "azure", "gcp", "git", "ci/cd",
    "terraform", "ansible", "jenkins", "devops", "rest", "api",
]

TITLE_HINTS = [
    # IT Administration first (priority domain)
    "administrateur it", "administrateur système", "administrateur systeme",
    "administrateur systèmes", "administrateur systemes",
    "administrateur réseaux", "administrateur reseaux", "administrateur réseau",
    "system administrator", "systems administrator", "network administrator",
    "it administrator", "it admin", "sysadmin", "technicien informatique",
    "technicien support", "support informatique", "ingénieur système", "ingenieur systeme",
    "ingénieur systèmes", "ingenieur systemes", "ingénieur infrastructure",
    "responsable informatique", "administrateur messagerie",
    # Software / development
    "software engineer", "backend engineer", "frontend engineer", "full stack developer",
    "fullstack developer", "devops engineer", "data engineer", "data scientist",
    "web developer", "python developer", "java developer",
    "ingénieur logiciel", "ingenieur logiciel", "développeur backend", "developpeur backend",
    "développeur frontend", "developpeur frontend", "développeur full stack",
    "developpeur full stack", "développeur web", "developpeur web", "développeuse web",
    "développeur python", "developpeur python", "développeuse", "developpeuse",
    "ingénieur devops", "ingenieur devops",
]

# Generic list of common Moroccan/Arabic/French given names — used ONLY as a
# confidence signal to split a merged, space-free name like "MOSTAFARAFI" into
# (given name, family name). Not tied to any single user; same lexicon pattern
# as SKILL_LEXICON / TITLE_HINTS above. When a token isn't recognized here, the
# split is skipped and the original value is kept rather than guessed.
COMMON_GIVEN_NAMES = frozenset(
    name.upper()
    for name in (
        "Mohammed", "Mohamed", "Ahmed", "Ali", "Omar", "Youssef", "Yousef", "Hassan",
        "Hussein", "Housni", "Ibrahim", "Idriss", "Khalid", "Karim", "Rachid", "Said",
        "Saad", "Nabil", "Samir", "Tarik", "Tariq", "Younes", "Zakaria", "Adil",
        "Amine", "Anas", "Anouar", "Badr", "Driss", "Fouad", "Hamid", "Hamza",
        "Hicham", "Imad", "Ismail", "Jamal", "Kamal", "Larbi", "Mehdi", "Mostafa",
        "Moustafa", "Mustapha", "Nizar", "Noureddine", "Othmane", "Rida", "Salah",
        "Sami", "Soufiane", "Walid", "Yassine", "Aziz", "Brahim", "Chakib", "Faisal",
        "Farid", "Ayoub", "Bilal", "Reda", "Marouane", "Mounir", "Nasser", "Yassir",
        "Abdelali", "Abdellah", "Abdellatif", "Abderrahim", "Abderrahman",
        "Abderrahmane", "Abdelaziz", "Abdelfattah", "Abdelghani", "Abdelhak",
        "Abdelhamid", "Abdelilah", "Abdeljalil", "Abdelkader", "Abdelkarim",
        "Abdelkrim", "Abdelmajid", "Abdelmalek", "Abdennasser", "Abdenbi",
        "Abdessamad", "Abdessalam", "Abdeslam", "Abdennour", "Abdeltif",
        "Jean", "Pierre", "Michel", "Marie", "Fatima", "Fatiha", "Khadija",
        "Amina", "Amine", "Aicha", "Zineb", "Nadia", "Salma", "Sara", "Sofia",
        "Hind", "Latifa", "Malika", "Naima", "Rachida", "Samira", "Siham",
        "Souad", "Yasmine", "Zahra", "Meryem", "Maryam", "Karima", "Leila",
        "Hanane", "Ghizlane", "Ilham", "Jihane", "Kenza", "Laila", "Loubna",
        "Mounia", "Najat", "Nawal", "Rajae", "Sanae", "Widad", "Zineb",
        "John", "David", "Marc", "Paul", "Anas", "Younes",
    )
)


DOMAIN_KEYWORDS = {
    "it_admin": [
        "administrateur it", "administrateur système", "administrateur systeme",
        "administrateur systèmes", "administrateur réseaux", "administrateur reseaux",
        "system administrator", "systems administrator", "network administrator",
        "it administrator", "sysadmin", "technicien informatique", "support it",
        "it support", "helpdesk", "help desk", "infrastructure", "active directory",
        "windows server", "vmware", "office 365", "microsoft 365", "exchange",
        "administrateur réseau", "exploitation", "systeme d'information",
        "systèmes d'information", "desktop support", "technicien support",
        "responsable informatique", "admin système", "admin systeme", "admin réseau",
    ],
    "software": [
        "software engineer", "software developer", "developer", "développeur", "developpeur",
        "développeuse", "developpeuse", "développement", "developpement",
        "backend", "frontend", "fullstack", "full stack", "programmer", "programmeur",
        "ingénieur logiciel", "ingenieur logiciel", "python developer", "java developer",
        "web developer", "mobile developer", "software development", "devops",
    ],
    "sales": ["commercial", "vendeur", "vente", "sales", "business developer", "account manager"],
    "hr": ["recrutement", "ressources humaines", "chargé de recrutement", "rh ", "talent"],
    "finance": ["comptable", "finance", "audit", "trésorerie", "bookkeeper"],
    "callcenter": ["call center", "téléconseiller", "teleconseiller", "customer support agent"],
}


def extract_text(filename: str, raw: bytes) -> str:
    """Pull plain text from an uploaded resume file."""
    name = (filename or "").lower()
    # #region agent log
    _dbg("H1", "resume.py:extract_text", "upload received", {"filename": name, "bytes": len(raw)})
    # #endregion

    if name.endswith(".txt") or name.endswith(".md"):
        text = raw.decode("utf-8", errors="ignore")
    elif name.endswith(".pdf"):
        text = _from_pdf(raw)
    elif name.endswith(".docx"):
        text = _from_docx(raw)
    else:
        raise ValueError("Unsupported file type. Use PDF, DOCX, or TXT.")

    text = re.sub(r"\s+", " ", text).strip()
    # #region agent log
    _dbg("H1", "resume.py:extract_text", "text extracted", {"chars": len(text), "preview": text[:160]})
    # #endregion
    if len(text) < 40:
        raise ValueError("Could not read enough text from this resume. Try PDF/DOCX/TXT with selectable text.")
    return text


def enrich_profile_from_resume(profile: dict[str, Any], resume_text: str) -> dict[str, Any]:
    """Build a CV-first profile: titles/skills/domain driven by the resume."""
    enriched = dict(profile)
    guessed_name = _guess_name(resume_text)
    found_skills = _find_skills(resume_text)
    found_titles = _find_titles(resume_text)
    for title in _extract_headline_titles(resume_text):
        if title.lower() not in [t.lower() for t in found_titles]:
            found_titles.append(title)
    found_titles = _clean_title_list(found_titles, candidate_name=guessed_name)

    domain = _detect_domain(" ".join(found_titles) + " " + resume_text[:2000] + " " + " ".join(found_skills))
    enriched["cv_domain"] = domain

    if found_titles:
        enriched["titles"] = found_titles[:8]
    else:
        # Fallback only within same domain — never keep another métier's titles
        fallback = list(profile.get("titles") or [])
        if (profile.get("cv_domain") or "") == domain and fallback:
            enriched["titles"] = fallback[:8]
        else:
            enriched["titles"] = (
                ["Software Engineer"] if domain == "software" else ["Administrateur IT"]
            )

    # CV skills win. Only keep static profile skills when they match the same domain
    # (avoids bleeding Linux/AD into a pure software CV).
    profile_domain = (profile.get("cv_domain") or "").lower()
    reuse_profile_skills = (not found_skills) and profile_domain == domain
    skill_pool = found_skills + (list(profile.get("skills") or []) if reuse_profile_skills else [])
    merged_skills: list[str] = []
    for skill in skill_pool:
        if skill.lower() not in [s.lower() for s in merged_skills]:
            merged_skills.append(skill)
    enriched["skills"] = merged_skills[:30]

    preferred = []
    for item in found_titles[:3] + found_skills[:8]:
        if item.lower() not in [p.lower() for p in preferred]:
            preferred.append(item)
    enriched["preferred_keywords"] = preferred

    # Rebuild excludes for THIS CV domain — never inherit another métier's bans
    # (e.g. profile.json excluding "développeur" was killing software searches).
    enriched["exclude_keywords"] = _excludes_for_domain(domain)

    # Always prefer CV identity — never keep a stale static profile name
    enriched["name"] = guessed_name or ""

    contact = extract_contact_fields(resume_text)
    if contact.get("email"):
        enriched["email"] = contact["email"]
    if contact.get("phone"):
        enriched["phone"] = contact["phone"]
    if contact.get("address"):
        enriched["address"] = contact["address"]
    if contact.get("linkedin"):
        enriched["linkedin"] = contact["linkedin"]
    if contact.get("headline"):
        enriched["headline"] = contact["headline"]

    enriched["resume_skills_found"] = found_skills
    enriched["resume_titles_found"] = found_titles
    enriched["resume_chars"] = len(resume_text)
    enriched["resume_query"] = _build_search_query(found_titles, found_skills, domain)

    # #region agent log
    _dbg(
        "H2",
        "resume.py:enrich_profile_from_resume",
        "cv profile built",
        {
            "name": enriched.get("name"),
            "titles": found_titles[:6],
            "skills": found_skills[:12],
            "domain": domain,
            "exclude_keywords": enriched["exclude_keywords"][:8],
            "resume_query": enriched["resume_query"],
            "has_email": bool(enriched.get("email")),
            "has_phone": bool(enriched.get("phone")),
        },
    )
    # #endregion
    return enriched


def profile_for_writing(resume_text: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a writing profile where identity comes only from the CV (not profile.json)."""
    region = (base or {}).get("region") or "morocco"
    blank = {
        "name": "",
        "titles": [],
        "skills": [],
        "region": region,
        "cv_domain": "",
        "locations": list((base or {}).get("locations") or [])[:4],
        "email": "",
        "phone": "",
        "address": "",
        "linkedin": "",
        "headline": "",
    }
    enriched = enrich_profile_from_resume(blank, resume_text)
    if not (enriched.get("name") or "").strip():
        enriched["name"] = "Candidat"
    return enriched


def extract_contact_fields(resume_text: str) -> dict[str, str]:
    """Pull email, phone, address, LinkedIn and a short headline métier from CV text.

    Never invents a value: a field that cannot be found or does not pass its
    validator (job_agent.validators) is returned as "" (this project's
    empty/unknown convention) instead of a best-effort guess.
    """
    text = resume_text or ""
    email_m = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    email = email_m.group(0).strip() if email_m else ""
    if email and not is_valid_email(email):
        email = ""

    phone = ""
    near = re.search(r"\+\d{1,3}[\s\-.]*(?:\d[\s\-.]*){8,12}", text)
    if near:
        phone = re.sub(r"\s+", " ", near.group(0)).strip()
    else:
        phone_m = re.search(
            r"(?:0|\+212)[\s\-.]?(?:\d[\s\-.]?){8,10}",
            text,
        )
        if phone_m:
            phone = re.sub(r"\s+", " ", phone_m.group(0)).strip()
    if phone and not is_valid_phone(phone):
        phone = ""

    linkedin_m = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w\-%À-ÿ]+/?",
        text,
        flags=re.I,
    )
    linkedin = ""
    if linkedin_m:
        linkedin = linkedin_m.group(0).strip()
        if not linkedin.lower().startswith("http"):
            linkedin = "https://" + linkedin.lstrip("/")

    address = _guess_address(text)
    if address and not is_valid_address(address):
        address = ""
    headline = _guess_headline(text)
    return {
        "email": email,
        "phone": phone,
        "address": address,
        "linkedin": linkedin,
        "headline": headline,
    }


def _guess_address(text: str) -> str:
    cities = (
        "Casablanca", "Rabat", "Marrakech", "Fès", "Fes", "Tanger", "Agadir",
        "Mohammedia", "Kénitra", "Kenitra", "Oujda", "Meknès", "Meknes",
        "Tétouan", "Tetouan", "Salé", "Sale",
    )
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:15]
    for line in lines:
        low = line.lower()
        if "@" in line or "linkedin" in low or re.search(r"https?://", line):
            continue
        if any(c.lower() in low for c in cities) and len(line) <= 80:
            if re.search(r"\d", line) or any(
                w in low for w in ("rue", "avenue", "quartier", "bd", "boulevard", "maroc", "morocco")
            ):
                return line
            # City + Morocco alone is still useful
            if any(c.lower() == low or c.lower() in low for c in cities):
                return line
    # Fallback: city mention in head
    head = text[:400]
    for city in cities:
        if city.lower() in head.lower():
            return f"{city}, Maroc"
    return ""


def _guess_headline(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:10]
    for line in lines[1:6]:
        low = line.lower()
        if "@" in line or re.search(r"https?://|\+\d{1,3}", line):
            continue
        if any(
            k in low
            for k in (
                "administrateur", "développeur", "developpeur", "ingénieur", "ingenieur",
                "technicien", "engineer", "developer", "analyst", "consultant", "support",
            )
        ):
            cleaned = re.split(r"[|•]", line)[0].strip()
            if 4 <= len(cleaned) <= 70:
                return cleaned
    return ""


def _excludes_for_domain(domain: str) -> list[str]:
    shared = ["unpaid", "femme de ménage", "head of retail"]
    if domain == "it_admin":
        return shared + [
            "développeur", "developpeur", "développeuse", "developpeuse",
            "backend", "frontend", "fullstack", "software engineer",
            "mobile developer", "react", "django",
            "vendeur", "commercial", "chargé de recrutement",
        ]
    if domain == "software":
        return shared + [
            "vendeur", "commercial", "chargé de recrutement", "call center",
            "bookkeeper", "comptable",
        ]
    return shared + ["vendeur", "commercial", "chargé de recrutement"]


_MAILBOX_NAME_PREFIXES = frozenset(
    {
        "contact",
        "info",
        "admin",
        "hello",
        "mail",
        "email",
        "hr",
        "cv",
        "me",
        "moi",
        "office",
        "recrutement",
        "recruitment",
        "career",
        "careers",
        "job",
        "jobs",
        "personnel",
        "service",
    }
)


def _collapse_spaced_letter_runs(text: str) -> str:
    """Repair PDF text like 'M O S T A F A R A F I' → 'MOSTAFARAFI'."""
    words = (text or "").split()
    out: list[str] = []
    i = 0
    while i < len(words):
        if len(words[i]) == 1 and words[i].isalpha():
            buf: list[str] = []
            while i < len(words) and len(words[i]) == 1 and words[i].isalpha():
                buf.append(words[i])
                i += 1
            out.append("".join(buf) if len(buf) >= 4 else " ".join(buf))
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def _name_from_email_local(local: str) -> str:
    """Build a person name from email local-part, dropping mailbox prefixes."""
    local = re.sub(r"[0-9]+", " ", local or "")
    local = local.replace(".", " ").replace("_", " ").replace("-", " ").replace("+", " ")
    parts = [p for p in local.split() if len(p) >= 2 and p.lower() not in _MAILBOX_NAME_PREFIXES]
    if not (1 <= len(parts) <= 3):
        return ""
    if not all(re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ]+$", p) for p in parts):
        return ""
    return " ".join(p.capitalize() for p in parts[:3])


def _guess_name(text: str) -> str:
    """Best-effort person name from the start of a resume."""
    # #region agent log
    def _dbg_name(hypothesis_id: str, message: str, data: dict) -> None:
        try:
            import json
            import time
            from pathlib import Path

            payload = {
                "sessionId": "acb47a",
                "runId": "post-fix",
                "hypothesisId": hypothesis_id,
                "location": "resume.py:_guess_name",
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
            Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-acb47a.log").parent.mkdir(
                parents=True, exist_ok=True
            )
            with Path("/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-acb47a.log").open(
                "a", encoding="utf-8"
            ) as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # #endregion
    raw_text = text or ""
    # Prefer repaired letter-spaced PDF extraction when present
    working = _collapse_spaced_letter_runs(raw_text)
    lines = [ln.strip() for ln in working.splitlines() if ln.strip()]
    email_m = re.search(r"([A-Z0-9._%+\-]+)@[A-Z0-9.\-]+\.[A-Z]{2,}", raw_text, flags=re.I)
    email_name = _name_from_email_local(email_m.group(1)) if email_m else ""

    # #region agent log
    _dbg_name(
        "A",
        "guess_name entry",
        {
            "n_lines": len(lines),
            "head120": re.sub(r"\s+", " ", working[:120]).strip(),
            "emails": re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", raw_text, flags=re.I)[:3],
            "email_name_cleaned": email_name,
        },
    )
    # #endregion

    # Explicit labels: Nom : Jean Dupont / Name: Jane Doe
    labeled = re.search(
        r"(?im)^(?:nom(?:\s*(?:et\s*pr[eé]nom)?|s)?|pr[eé]nom(?:\s*et\s*nom)?|name|full\s*name)\s*[:\-–]\s*(.+)$",
        working,
    )
    if labeled:
        candidate = _clean_person_name(labeled.group(1))
        if candidate:
            # #region agent log
            _dbg_name("E", "return via labeled Nom/Name", {"raw": labeled.group(1)[:80], "result": candidate})
            # #endregion
            return candidate

    skip_line = re.compile(
        r"(?i)^(curriculum\s*vitae|cv|resume|r[eé]sum[eé]|profil|profile|"
        r"coordonn[eé]es|contact|exp[eé]rience|formation|education|"
        r"[eé]ducation|skills|comp[eé]tences|objectif|summary)\b"
    )
    role_cut = re.compile(
        r"(?i)(?:^|[^A-Za-zÀ-ÖØ-öø-ÿ])(administrateur|administrator|software|engineer|d[eé]veloppeur|"
        r"d[eé]veloppeuse|technicien|ing[eé]nieur|ingenieur|backend|frontend|"
        r"devops|analyst|consultant|manager|stage|alternance|"
        r"email|t[eé]l[eé]phone|telephone|phone|adresse|linkedin|skills|"
        r"profil|profile)(?:$|[^A-Za-zÀ-ÖØ-öø-ÿ])"
    )
    role_cut_glued = re.compile(
        r"(?i)(administrateur|administrator|d[eé]veloppeur|d[eé]veloppeuse|"
        r"technicien|ing[eé]nieur|ingenieur|software|engineer)"
    )

    for line in lines[:12]:
        if skip_line.match(line):
            # #region agent log
            if re.search(r"(?i)\bcontact\b", line):
                _dbg_name("B", "skip_line matched contact-like", {"line": line[:80]})
            # #endregion
            continue
        if "@" in line or re.search(r"https?://|www\.|linkedin\.com", line, flags=re.I):
            continue
        if re.search(r"\d{5,}", line) or re.search(r"\+\d{1,3}", line):
            continue
        chunk = re.split(r"[|•·]", line)[0].strip()
        # Collapsed PDF blob like MOSTAFARAFIADMINISTRATEUR… → cut before role
        cut = role_cut_glued.search(chunk) or role_cut.search(chunk)
        if cut and cut.start() >= 4:
            before = chunk[: cut.start()].strip(" ,;-–")
            if email_name and before.replace(" ", "").lower() == email_name.replace(" ", "").lower():
                # #region agent log
                _dbg_name(
                    "A",
                    "return via collapsed head matched email",
                    {"before": before[:80], "result": email_name},
                )
                # #endregion
                return email_name
            chunk = before or chunk
        candidate = _clean_person_name(chunk)
        if candidate:
            # #region agent log
            _dbg_name(
                "B",
                "return via header line",
                {
                    "line": line[:80],
                    "chunk": chunk[:80],
                    "result": candidate,
                    "starts_with_contact": bool(re.match(r"(?i)^contact\b", line)),
                    "clean_kept_contact": "contact" in candidate.lower(),
                },
            )
            # #endregion
            return candidate

    # Flattened single-line CV head
    head = re.sub(r"\s+", " ", working[:240]).strip()
    if head:
        chunk = re.split(r"[|•·\-–—/]", head)[0].strip()
        cut = role_cut_glued.search(chunk) or role_cut.search(chunk)
        if cut and cut.start() >= 4:
            before = chunk[: cut.start()].strip()
            if email_name and before.replace(" ", "").lower() == email_name.replace(" ", "").lower():
                # #region agent log
                _dbg_name(
                    "C",
                    "return via flattened+email match",
                    {"before": before[:80], "result": email_name},
                )
                # #endregion
                return email_name
            chunk = before or chunk
            cut2 = role_cut_glued.search(chunk) or role_cut.search(chunk)
            if cut2 and cut2.start() > 3:
                chunk = chunk[: cut2.start()].strip()
        candidate = _clean_person_name(chunk)
        if candidate and not skip_line.match(candidate):
            # #region agent log
            _dbg_name(
                "C",
                "return via flattened head",
                {
                    "chunk": chunk[:100],
                    "result": candidate,
                    "clean_kept_contact": "contact" in candidate.lower(),
                },
            )
            # #endregion
            return candidate

    # Last resort: email local-part without mailbox prefixes (contact/info/…)
    if email_name:
        # #region agent log
        _dbg_name(
            "A",
            "return via email local-part cleaned",
            {
                "email_local": (email_m.group(1) if email_m else "")[:80],
                "result": email_name,
            },
        )
        # #endregion
        return email_name
    # #region agent log
    _dbg_name("A", "return empty", {"result": ""})
    # #endregion
    return ""


def _clean_person_name(raw: str) -> str:
    first = re.sub(r"\s+", " ", (raw or "").strip(" .,:;-–_|"))
    if not first:
        return ""
    # Strip section / mailbox labels glued to a real name
    first = re.sub(
        r"(?i)^(contact|coordonn[eé]es|email|mail|t[eé]l[eé]phone|phone|adresse)\s*[:\-–]?\s+",
        "",
        first,
    ).strip()
    lower = first.lower()
    if any(
        k in lower
        for k in (
            "curriculum", "vitae", "resume", "résumé", "skills", "expérience",
            "experience", "administrateur", "développeur", "developpeur",
            "ingénieur", "ingenieur", "technicien", "software", "engineer",
            "python", "django", "java", "javascript", "linux", "windows",
            "active directory", "office", "support", "@", "http",
        )
    ):
        return ""
    # #region agent log
    if re.search(r"(?i)\bcontact\b", first):
        try:
            import json
            import time
            from pathlib import Path

            with Path(
                "/media/mostafa/New Volume/dev/job-finder-agent/.cursor/debug-acb47a.log"
            ).open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "sessionId": "acb47a",
                            "runId": "post-fix",
                            "hypothesisId": "D",
                            "location": "resume.py:_clean_person_name",
                            "message": "contact token still present after strip",
                            "data": {"raw": first[:80]},
                            "timestamp": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except Exception:
            pass
    # #endregion
    # Reject leftover mailbox-only leftovers
    parts = [p for p in first.split() if p.lower() not in _MAILBOX_NAME_PREFIXES]
    if not parts:
        return ""
    first = " ".join(parts)
    # Reject if it looks like a job title alone
    if re.search(
        r"(?i)^(administrateur|d[eé]veloppeur|ing[eé]nieur|technicien|engineer|"
        r"software|python|java|support)\b",
        first,
    ):
        return ""
    parts = first.split()
    if not (1 <= len(parts) <= 4):
        return ""
    if not all(re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ''’\-]+$", p) for p in parts):
        return ""
    # Prefer at least 2 tokens for a full name; allow 1 only if capitalized name-like
    if len(parts) == 1:
        if len(parts[0]) < 3:
            return ""
        return _format_single_name_token(parts[0])
    return _format_name_tokens(parts[:3])


def _split_merged_name(token: str) -> tuple[str, str] | None:
    """Try to split a merged, space-free name (e.g. "MOSTAFARAFI") into
    (given_name, family_name) using COMMON_GIVEN_NAMES as a confidence signal.

    Returns None whenever the split would be a guess rather than a confident
    match — callers must then keep the original token unsplit.
    """
    upper = token.upper()
    if len(upper) < 6:
        return None
    matches = sorted(
        (given for given in COMMON_GIVEN_NAMES if upper.startswith(given) and len(upper) - len(given) >= 3),
        key=len,
        reverse=True,
    )
    if not matches:
        return None
    best = matches[0]
    # Ambiguous when two equally-long candidate prefixes both fit — don't guess.
    if len(matches) > 1 and len(matches[1]) == len(best):
        return None
    return upper[: len(best)], upper[len(best) :]


def _format_single_name_token(token: str) -> str:
    """Format one name token; attempt a high-confidence merged-name split first."""
    if not token.isupper():
        return token
    split = _split_merged_name(token)
    if split:
        given, family = split
        return f"{given.capitalize()} {family}"
    return token.capitalize()


def _format_name_tokens(parts: list[str]) -> str:
    """Title-case given-name tokens; preserve an all-caps family-name token as-is.

    Many CVs write "Prénom NOM" with the family name in caps — that convention is
    kept (never forced to Title Case) instead of guessing which token is which.
    """
    formatted: list[str] = []
    last_idx = len(parts) - 1
    for idx, part in enumerate(parts):
        if part.islower():
            formatted.append(part.capitalize())
        elif part.isupper() and len(part) > 1:
            # Last all-caps token = family name convention → keep uppercase.
            formatted.append(part if idx == last_idx else part.capitalize())
        else:
            formatted.append(part)  # already mixed-case as intended in the CV
    return " ".join(formatted)
def _clean_title_list(titles: list[str], candidate_name: str = "") -> list[str]:
    """Drop a leading placeholder token (or the candidate's own name — never a
    hardcoded one, always whatever this CV's _guess_name() produced) glued to a
    CV headline, e.g. "John Administrateur Systèmes" → "Administrateur Systèmes"."""
    name_tokens = [re.escape(tok) for tok in (candidate_name or "").split() if len(tok) >= 2]
    strip_pattern = r"^(?:" + "|".join(name_tokens + ["candidate", "cv", "resume"]) + r")\b[:\s-]*"
    cleaned: list[str] = []
    for title in titles:
        t = re.split(r"\bskills\b|\bexpérience\b|\bexperience\b|\béducation\b", title, flags=re.I)[0]
        t = re.sub(strip_pattern, "", t, flags=re.I).strip(" -:|/")
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) < 4 or len(t) > 70:
            continue
        if t.lower() not in [c.lower() for c in cleaned]:
            cleaned.append(t)
    # Prefer admin titles before generic ones when both exist
    cleaned.sort(key=lambda x: (0 if any(k in x.lower() for k in ("admin", "syst", "réseau", "reseau", "support", "technicien")) else 1))
    return cleaned


def _build_search_query(titles: list[str], skills: list[str], domain: str = "") -> str:
    title = " ".join(titles[:3]).lower()
    skills_l = [s.lower() for s in skills]
    domain = domain or _detect_domain(title + " " + " ".join(skills_l))

    if domain == "it_admin" or any(k in title for k in ("admin", "syst", "réseau", "reseau", "support", "technicien informatique")):
        if "réseau" in title or "reseau" in title or "network" in title:
            base = "administrateur reseaux"
        elif "support" in title or "technicien" in title:
            base = "technicien informatique"
        else:
            base = "administrateur systeme"
        preferred = [
            "windows server", "active directory", "office 365", "linux", "vmware",
            "cisco", "azure", "powershell", "firewall",
        ]
        top_skill = next((s for s in preferred if s in skills_l), "")
        return f"{base} {top_skill}".strip()

    if "backend" in title:
        base = "developpeur backend"
    elif "frontend" in title:
        base = "developpeur frontend"
    elif "devops" in title:
        base = "ingenieur devops"
    elif "data" in title:
        base = "data engineer"
    elif "full" in title:
        base = "developpeur full stack"
    elif any(k in title for k in ("software", "develop", "développ", "ingénieur logiciel")):
        base = "developpeur"
    else:
        base = titles[0] if titles else "administrateur systeme"

    preferred = ["python", "java", "javascript", "typescript", "php", "react", "django", "flask", "angular"]
    top_skill = next((s for s in preferred if s in skills_l), skills_l[0] if skills_l else "")
    return f"{base} {top_skill}".strip()


def _detect_domain(text: str) -> str:
    lower = text.lower()
    # Strong phrase boosts for IT admin (must win over software when both appear)
    scores = {name: 0 for name in DOMAIN_KEYWORDS}
    for name, kws in DOMAIN_KEYWORDS.items():
        for kw in kws:
            if kw in lower:
                # Longer / more specific phrases weigh more
                scores[name] += 2 if " " in kw else 1

    # Extra boost for explicit admin role wording
    if re.search(r"administrateur\s+(it|syst|réseau|reseau|infra)", lower):
        scores["it_admin"] += 5
    if re.search(r"(system|systems|network)\s+administrator", lower):
        scores["it_admin"] += 5
    if re.search(r"d[eé]veloppeur|software engineer|backend|frontend", lower):
        scores["software"] += 3

    best = max(scores, key=scores.get)
    # #region agent log
    _dbg("H2", "resume.py:_detect_domain", "domain scores", {"scores": scores, "chosen": best if scores[best] > 0 else "it_admin"})
    # #endregion
    if scores[best] <= 0:
        return "it_admin"  # safer default for this product audience
    return best


def _extract_headline_titles(text: str) -> list[str]:
    sample = text[:800]
    chunks = re.split(r"[\n|/•]", sample)
    titles: list[str] = []
    for part in chunks:
        cleaned = part.strip(" -:\t")
        lower = cleaned.lower()
        if any(x in lower for x in ("skill", "experience", "expérience", "éducation", "education")):
            continue
        if 3 < len(cleaned) < 60 and any(
            token in lower
            for token in (
                "administrateur", "administrator", "technicien", "support",
                "ingénieur système", "ingenieur systeme", "sysadmin",
                "engineer", "developer", "développ", "develop", "ingénieur", "ingenieur",
                "devops", "backend", "frontend", "fullstack",
            )
        ):
            cleaned = re.sub(
                r"^([A-Z][a-z]+\s+){1,3}(?=(Administrateur|Administrator|Software|Backend|Frontend|Technicien|Ingénieur|Ingenieur|Développeur|Developpeur))",
                "",
                cleaned,
            ).strip()
            titles.append(cleaned)
    return titles[:4]


def _from_pdf(raw: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(raw))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _from_docx(raw: bytes) -> str:
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _find_skills(text: str) -> list[str]:
    lower = text.lower()
    found: list[tuple[int, str]] = []
    for skill in sorted(SKILL_LEXICON, key=len, reverse=True):
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        match = re.search(pattern, lower)
        if match:
            found.append((match.start(), skill))
    found.sort(key=lambda item: item[0])
    hits: list[str] = []
    for _, skill in found:
        if skill not in hits:
            hits.append(skill)
    return hits


def _find_titles(text: str) -> list[str]:
    lower = text.lower()
    hits: list[str] = []
    for title in sorted(TITLE_HINTS, key=len, reverse=True):
        if title in lower and title not in hits:
            hits.append(title)
    return hits
