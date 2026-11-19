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
    explicit_couple = _explicit_couple_with_children(original_text)
    if explicit_couple:
        subject = explicit_couple[0]
    spouse_match = re.search(r"(?i:\bseine)\s+Frau\s+([A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?)", original_text)
    spouse = spouse_match.group(1).strip() if spouse_match else None
    if explicit_couple:
        spouse = explicit_couple[1]
    explicit_edges, explicit_owner_edges, explicit_children, explicit_parents = _explicit_child_parent_edges(original_text)
    friendship_edges = _explicit_friendship_edges(original_text)
    parent_statement = re.search(r"(?P<parents>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?\s+und\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)?)\s+haben\s+(?:zwei|drei|vier|ihre|gemeinsame[nr]?)\s+(?:Söhne|Töchter|Kinder)", original_text)
    extra_parents = _name_list(parent_statement.group("parents")) if parent_statement else []
    children = explicit_couple[2] if explicit_couple else _children_from_text(original_text)
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
    family_people.update(explicit_children)
    parents = list(dict.fromkeys([name for name in (subject, spouse, *extra_parents) if name]))
    family_people.update(parents)
    family_people.update(explicit_parents)
    meeting = _meeting_suggestion(subject, original_text, captured_at) if subject and meeting_is_explicit else None
    family_edges = (_family_relationships(subject, spouse, children, parents) if subject else []) + explicit_edges
    loan = _loan_suggestion(subject, original_text, captured_at)
    if meeting is None and not family_edges and not explicit_owner_edges and not friendship_edges and loan is None:
        return suggestions

    family_first_names = {name.split()[0].casefold() for name in family_people}
    friendship_first_names = {
        name.split()[0].casefold()
        for edge in friendship_edges
        for name in (edge.person_name, edge.related_person_name)
        if name
    }
    kept: list[CaptureSuggestion] = []
    for item in suggestions:
        match item.kind:
            case "conversation" | "event":
                if meeting is None:
                    kept.append(item)
            case "relationship":
                is_family_duplicate = family_edges and _mentions_family(item, family_first_names) and _describes_family_relationship(item)
                is_friendship_duplicate = friendship_edges and _mentions_named_people(item, friendship_first_names) and _describes_friendship(item)
                if not is_family_duplicate and not is_friendship_duplicate:
                    kept.append(item)
            case "loan":
                if loan is None:
                    kept.append(item)
            case "fact":
                if not _duplicates_meeting_or_loan(item, family_first_names, loan) and not (
                    family_edges and _mentions_family(item, family_first_names) and _describes_family_relationship(item)
                ) and not (friendship_edges and _mentions_named_people(item, friendship_first_names) and _describes_friendship(item)):
                    kept.append(item)
            case "owner_relationship":
                if not (explicit_owner_edges and _mentions_family(item, family_first_names)):
                    kept.append(item)
            case "former_name" | "life_event" | "task" | "project_link":
                kept.append(item)
    if meeting is not None:
        kept.insert(0, meeting)
    kept.extend(family_edges)
    kept.extend(explicit_owner_edges)
    kept.extend(friendship_edges)
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


def _explicit_couple_with_children(original_text: str) -> tuple[str, str, list[str]] | None:
    name = r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]*){0,2}"
    start = re.search(rf"(?P<subject>{name})\s+hat\s+eine\s+Frau", original_text, re.IGNORECASE)
    if start is None:
        return None

    suffix = original_text[start.end():]
    direct_spouse = re.match(rf"\s+(?:namens\s+)?(?P<spouse>{name})", suffix)
    spouse = direct_spouse.group("spouse").strip() if direct_spouse else None
    if spouse is None:
        spouse_after_period = re.match(
            rf"\s*[.!?]\s*(?P<spouse>{name})\s*[.!?]\s*(?:und\s+)?die beiden haben\b",
            suffix,
            re.IGNORECASE,
        )
        if spouse_after_period is None:
            return None
        spouse = spouse_after_period.group("spouse").strip()

    children_match = re.search(
        r"\bdie beiden haben\s+(?P<count>\d+|eins?|eine|einen|zwei|drei|vier|fünf)\s+Kinder\s+(?P<names>[^.!?\n]+)",
        original_text,
        re.IGNORECASE,
    )
    if children_match is None:
        return None
    count_by_word = {"ein": 1, "eins": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5}
    count_text = children_match.group("count").casefold()
    count = int(count_text) if count_text.isdecimal() else count_by_word.get(count_text)
    children = _name_list(children_match.group("names"))
    if count is None or len(children) != count:
        return None

    subject = start.group("subject").strip()
    surname_match = re.search(r"\bAlle heißen\s+(?P<surname>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+)\s+mit Nachnamen\b", original_text, re.IGNORECASE)
    surname = surname_match.group("surname") if surname_match else subject.split()[-1]
    subject = subject if len(subject.split()) > 1 else f"{subject} {surname}"
    spouse = spouse if len(spouse.split()) > 1 else f"{spouse} {surname}"
    children = [child if len(child.split()) > 1 else f"{child} {surname}" for child in children]
    return subject, spouse, children


def _explicit_child_parent_edges(original_text: str) -> tuple[list[CaptureSuggestion], list[CaptureSuggestion], list[str], list[str]]:
    relation_edges: list[CaptureSuggestion] = []
    owner_edges: list[CaptureSuggestion] = []
    children: list[str] = []
    parents: list[str] = []
    full_names = re.findall(
        r"(?=(\b[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){1,2}\b))",
        original_text,
    )
    statement = re.compile(
        r"(?P<child>[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]*){0,2})\s+ist\s+"
        r"(?:die\s+Tochter|der\s+Sohn|ein\s+Kind|eine\s+Tochter|ein\s+Sohn|Tochter|Sohn|Kind)\s+von\s+"
        r"(?P<parents>[^.!?;\n]+)",
        re.IGNORECASE,
    )
    for match in statement.finditer(original_text):
        child = match.group("child").strip()
        matching_full_names = [name for name in full_names if name.split()[0].casefold() == child.split()[0].casefold()]
        if len(matching_full_names) == 1:
            child = matching_full_names[0]
        relation = "Tochter von" if re.search(r"Tochter", match.group(0), re.IGNORECASE) else "Sohn von" if re.search(r"Sohn", match.group(0), re.IGNORECASE) else "Kind von"
        named_parents: list[str] = []
        refers_to_user = False
        for part in re.split(r"\s+(?:und|,)\s+", match.group("parents"), flags=re.IGNORECASE):
            if re.search(r"\b(?:mir|mich|meiner|meinem|meines|uns)\b", part, re.IGNORECASE):
                refers_to_user = True
            name = re.sub(r"\b(?:mir|mich|meiner|meinem|meines|uns)\b", "", part, flags=re.IGNORECASE).strip(" ,")
            if re.fullmatch(r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]*){0,2}", name):
                named_parents.append(name)
        children.append(child)
        parents.extend(named_parents)
        for parent in named_parents:
            relation_edges.append(CaptureSuggestion(
                kind="relationship",
                title=f"Elternteil: {parent} → {child}",
                content=f"{parent} ist Elternteil von {child}.",
                person_name=parent,
                related_person_name=child,
                relationship_type="Elternteil von",
                inverse_relationship_type="Kind von",
                confirmation_required=True,
            ))
        if refers_to_user:
            owner_edges.append(CaptureSuggestion(
                kind="owner_relationship",
                title=f"Elternteil: Du → {child}",
                content=f"{child} ist {relation} dir.",
                person_name=child,
                relationship_type=relation,
                confirmation_required=True,
            ))
    return relation_edges, owner_edges, list(dict.fromkeys(children)), list(dict.fromkeys(parents))


def _explicit_friendship_edges(original_text: str) -> list[CaptureSuggestion]:
    name = r"[A-ZÄÖÜ][\wÄÖÜäöüß'-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]*){0,2}"
    statement = re.compile(
        rf"(?P<first>{name})\s+und\s+(?P<second>{name})\s+(?:sind|waren)\s+(?:gute\s+)?(?:Freunde|befreundet)\b",
        re.IGNORECASE,
    )
    return [
        CaptureSuggestion(
            kind="relationship",
            title=f"Freunde: {match.group('first').strip()} ↔ {match.group('second').strip()}",
            content=f"{match.group('first').strip()} und {match.group('second').strip()} sind befreundet.",
            person_name=match.group("first").strip(),
            related_person_name=match.group("second").strip(),
            relationship_type="Freunde",
            inverse_relationship_type="Freunde",
            confirmation_required=True,
        )
        for match in statement.finditer(original_text)
    ]


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


def _loan_suggestion(subject: str | None, original_text: str, captured_at: datetime) -> CaptureSuggestion | None:
    direction = "borrowed"
    person = subject
    item: str | None = None
    incoming = re.search(r"(?P<person>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){0,2})\s+hat\s+mir\s+(?:einen|ein|eine|den|das|die)?\s*(?P<item>.+?)\s+geliehen\b", original_text)
    incoming_pronoun = re.search(r"\ber\s+hat\s+mir\s+(?:einen|ein|eine|den|das|die)?\s*(?P<item>.+?)\s+geliehen\b", original_text, re.IGNORECASE)
    outgoing_to = re.search(r"\bich\s+habe\s+(?P<item>.+?)\s+(?:an|für)\s+(?P<person>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){0,2})\s+(?:geliehen|verliehen)\b", original_text, re.IGNORECASE)
    outgoing_direct = re.search(r"\bich\s+habe\s+(?P<person>[A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß'-]+){0,2})\s+(?:heute\s+|gestern\s+)?(?:meine[nr]?|mein|einen|ein|eine|den|das|die)\s+(?P<item>[\wÄÖÜäöüß'-]+(?:\s+[\wÄÖÜäöüß'-]+){0,3})\s+(?:geliehen|verliehen)\b", original_text, re.IGNORECASE)
    if incoming is not None:
        person = _canonical_person(incoming.group("person"))
        item = incoming.group("item")
    elif incoming_pronoun is not None:
        item = incoming_pronoun.group("item")
    elif outgoing_to is not None:
        person = _canonical_person(outgoing_to.group("person"))
        item = outgoing_to.group("item")
        direction = "lent"
    elif outgoing_direct is not None:
        person = _canonical_person(outgoing_direct.group("person"))
        item = outgoing_direct.group("item")
        direction = "lent"
    if person is None or item is None:
        return None
    item = re.sub(r"^(?:mein|meine|meinen|meinem|meiner|ein|eine|einen|einem|einer|der|die|das|den)\s+", "", item, flags=re.IGNORECASE).strip()
    if not item:
        return None
    phrase = f"{person} hat mir {item} geliehen." if direction == "borrowed" else f"Ich habe {item} an {person} verliehen."
    return CaptureSuggestion(
        kind="loan",
        title=item,
        content=f"{phrase} Kein Rückgabetermin wurde genannt.",
        person_name=person,
        occurred_at=captured_at.replace(hour=12, minute=0, second=0, microsecond=0) if re.search(r"\bheute\b", original_text, re.IGNORECASE) else None,
        date_precision="day" if re.search(r"\bheute\b", original_text, re.IGNORECASE) else "unknown",
        due_at=None,
        loan_direction=direction,
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
    return bool(re.search(r"\b(vater|mutter|tochter|sohn|kind|eltern|ehefrau|ehemann|ehepartner|geschwister|elternteil|verheiratet|frau|mann)\b", text))


def _mentions_named_people(suggestion: CaptureSuggestion, first_names: set[str]) -> bool:
    text = f"{suggestion.title} {suggestion.content} {suggestion.person_name or ''} {suggestion.related_person_name or ''}".casefold()
    return all(re.search(rf"\b{re.escape(name)}\b", text) for name in first_names)


def _describes_friendship(suggestion: CaptureSuggestion) -> bool:
    text = f"{suggestion.title} {suggestion.content} {suggestion.relationship_type or ''}".casefold()
    return bool(re.search(r"\b(freund(?:e|in|en)?|befreundet|freundschaft)\b", text))
