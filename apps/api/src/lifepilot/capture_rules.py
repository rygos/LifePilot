import re
from datetime import datetime, timedelta
from itertools import combinations

from lifepilot.capture_schemas import CaptureSuggestion


def apply_family_meeting_and_loan_rules(
    original_text: str,
    captured_at: datetime,
    suggestions: list[CaptureSuggestion],
) -> list[CaptureSuggestion]:
    subject_match = re.search(
        r"(?i:\bbei)\s+(?P<person>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){1,2})",
        original_text,
    )
    meeting_day = next((day for day in ("heute", "gestern") if re.search(rf"\b{day}\b", original_text, re.IGNORECASE)), None)
    meeting_is_explicit = bool(meeting_day and re.search(r"\b(getroffen|gequatscht|gesprochen)\b", original_text, re.IGNORECASE))
    subject = _canonical_person(subject_match.group("person")) if subject_match else None
    spouse_match = re.search(r"(?i:\bseine)\s+Frau\s+([A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?)", original_text)
    spouse = spouse_match.group(1).strip() if spouse_match else None
    parent_statement = re.search(r"(?P<parents>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?\s+und\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?)\s+haben\s+(?:zwei|drei|vier|ihre|gemeinsame[nr]?)\s+(?:Söhne|Töchter|Kinder)", original_text)
    extra_parents = _name_list(parent_statement.group("parents")) if parent_statement else []
    children = _children_from_text(original_text)
    if not children and parent_statement:
        children = _name_list(original_text[parent_statement.end():])
    if subject is None and extra_parents:
        subject = extra_parents[0]
    family_surname = next((name.split()[-1] for name in children if len(name.split()) > 1), None)
    family_surname = family_surname or (subject.split()[-1] if subject and len(subject.split()) > 1 else None)
    family_surname = family_surname or (spouse.split()[-1] if spouse and len(spouse.split()) > 1 else None)
    if family_surname:
        children = [name if len(name.split()) > 1 else f"{name} {family_surname}" for name in children]
        subject = subject if subject is None or len(subject.split()) > 1 else f"{subject} {family_surname}"
        extra_parents = [name if len(name.split()) > 1 else f"{name} {family_surname}" for name in extra_parents]
        spouse = spouse if spouse is None or len(spouse.split()) > 1 else f"{spouse} {family_surname}"
    extra_parents = [next((known for known in (subject, spouse) if known and known.split()[0].casefold() == name.split()[0].casefold()), name) for name in extra_parents]
    family_people: set[str] = {name for name in (subject, spouse) if name}
    family_people.update(children)
    parents = list(dict.fromkeys([name for name in (subject, spouse, *extra_parents) if name]))
    family_people.update(parents)
    has_family = bool(subject and (spouse or children or extra_parents))
    meeting = _meeting_suggestion(subject, original_text, captured_at) if subject and meeting_is_explicit else None
    family_edges = _family_relationships(subject, spouse, children, parents) if has_family and subject else []
    loan = _loan_suggestion(subject, original_text, captured_at) if subject else None
    if meeting is None and not family_edges and loan is None:
        return suggestions

    family_first_names = {name.split()[0].casefold() for name in family_people}
    kept: list[CaptureSuggestion] = []
    for item in suggestions:
        match item.kind:
            case "conversation" | "event":
                if meeting is None:
                    kept.append(item)
            case "relationship":
                if not family_edges or not _mentions_family(item, family_first_names):
                    kept.append(item)
            case "loan":
                if loan is None:
                    kept.append(item)
            case "fact":
                if not _duplicates_meeting_or_loan(item, family_first_names, loan) and not (
                    family_edges and _mentions_family(item, family_first_names) and _describes_family_relationship(item)
                ):
                    kept.append(item)
            case "owner_relationship" | "former_name" | "life_event" | "task" | "project_link":
                kept.append(item)
    if meeting is not None:
        kept.insert(0, meeting)
    kept.extend(family_edges)
    if loan is not None:
        kept.append(loan)
    return kept


def _canonical_person(name: str) -> str:
    match name.casefold():
        case "christan decker":
            return "Christian Decker"
        case _:
            return name


def _children_from_text(original_text: str) -> list[str]:
    matches = re.finditer(r"\bseine\s+(?:Kinder|Söhne|Töchter|Sohn|Tochter)\s+(.+?)(?=\s+sowie\s+seine\s+(?:Frau|Kinder|Söhne|Töchter|Sohn|Tochter)|\s+und\s+seine\s+(?:Frau|Kinder|Söhne|Töchter|Sohn|Tochter)|\s+getroffen\b|[.!?]|$)", original_text, re.IGNORECASE)
    return list(dict.fromkeys(name for match in matches for name in _name_list(match.group(1))))


def _name_list(value: str) -> list[str]:
    cleaned = re.sub(r"\s+(?:habe|haben|hat|getroffen|gesehen)\b.*$", "", value, flags=re.IGNORECASE)
    fragments = [fragment.strip(" .,;:") for fragment in re.split(r",|\s+und\s+|\s+sowie\s+", cleaned, flags=re.IGNORECASE)]
    names = [fragment for fragment in fragments if re.fullmatch(r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]*){0,2}", fragment)]
    family_name = next((name.split()[-1] for name in reversed(names) if len(name.split()) > 1), None)
    if family_name:
        names = [f"{name} {family_name}" if len(name.split()) == 1 else name for name in names]
    return list(dict.fromkeys(names))


def _meeting_suggestion(subject: str, original_text: str, captured_at: datetime) -> CaptureSuggestion:
    occurred_at = captured_at.replace(hour=12, minute=0, second=0, microsecond=0)
    if re.search(r"\bgestern\b", original_text, re.IGNORECASE):
        occurred_at -= timedelta(days=1)
    lego = bool(re.search(r"\bLego\s+auseinander\s+gebaut\b", original_text, re.IGNORECASE))
    activity = "; Lego auseinandergenommen" if lego else ""
    source_name = re.search(r"\bbei\s+([A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){1,2})", original_text)
    source_person = source_name.group(1).strip() if source_name else subject
    correction_note = f" Im Original steht „{source_person}“; die Zuordnung wird als „{subject}“ vorgeschlagen." if source_person.casefold() != subject.casefold() else ""
    return CaptureSuggestion(
        kind="conversation",
        title=f"Treffen mit {subject}{' · Lego auseinandergenommen' if lego else ''}",
        content=f"{'Gestern' if occurred_at.date() != captured_at.date() else 'Heute'} bei {subject} getroffen und gequatscht{activity}.{correction_note}",
        person_name=subject,
        occurred_at=occurred_at,
        date_precision="day",
        confirmation_required=source_person.casefold() != subject.casefold(),
    )


def _family_relationships(subject: str, spouse: str | None, children: list[str], parents: list[str]) -> list[CaptureSuggestion]:
    edges: list[tuple[str, str, str, str, str]] = []
    if spouse and spouse.casefold() != subject.casefold():
        edges.append((subject, spouse, "Ehepartner von", "Ehepartner von", "Ehepartner"))
    for parent in parents:
        for child in children:
            edges.append((parent, child, "Elternteil von", "Kind von", "Elternteil"))
    for first, second in combinations(children, 2):
        edges.append((first, second, "Geschwister von", "Geschwister von", "Geschwister"))
    return [
        CaptureSuggestion(
            kind="relationship",
            title=f"{label}: {source} → {target}",
            content=f"Vorschlag aus der Familienbeschreibung: {source} ist {relationship} {target}. Bitte prüfen.",
            person_name=source,
            related_person_name=target,
            relationship_type=relationship,
            inverse_relationship_type=inverse,
            confirmation_required=True,
        )
        for source, target, relationship, inverse, label in edges
    ]


def _loan_suggestion(subject: str, original_text: str, captured_at: datetime) -> CaptureSuggestion | None:
    match = re.search(r"\bhat\s+mir\s+(?:einen|ein|eine|den|das|die)\s+(.+?)\s+geliehen\b", original_text, re.IGNORECASE)
    if match is None:
        return None
    item = match.group(1).strip()
    if not item:
        return None
    return CaptureSuggestion(
        kind="loan",
        title=item,
        content=f"{subject} hat mir {item} geliehen. Kein Rückgabetermin wurde genannt.",
        person_name=subject,
        occurred_at=captured_at.replace(hour=12, minute=0, second=0, microsecond=0) if re.search(r"\bheute\b", original_text, re.IGNORECASE) else None,
        date_precision="day" if re.search(r"\bheute\b", original_text, re.IGNORECASE) else "unknown",
        due_at=None,
    )


def _mentions_family(suggestion: CaptureSuggestion, family_first_names: set[str]) -> bool:
    names = (suggestion.person_name, suggestion.related_person_name)
    return any(
        name and _canonical_person(name).split()[0].casefold() in family_first_names
        for name in names
    )


def _duplicates_meeting_or_loan(
    suggestion: CaptureSuggestion,
    family_first_names: set[str],
    loan: CaptureSuggestion | None,
) -> bool:
    text = f"{suggestion.title} {suggestion.content}".casefold()
    mentions_family = any(re.search(rf"\b{re.escape(name)}\b", text) for name in family_first_names)
    describes_meeting = bool(re.search(r"getroffen|begegn|besuch|gequatsch|gesproch|lego", text))
    describes_loan = "geliehen" in text or bool(loan and loan.title.casefold() in text)
    return (mentions_family and describes_meeting) or describes_loan


def _describes_family_relationship(suggestion: CaptureSuggestion) -> bool:
    text = f"{suggestion.title} {suggestion.content} {suggestion.relationship_type or ''}".casefold()
    return bool(re.search(r"\b(vater|mutter|tochter|sohn|ehefrau|ehemann|ehepartner|geschwister|elternteil|verheiratet|frau|mann)\b", text))
