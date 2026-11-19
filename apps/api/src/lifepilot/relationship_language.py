from __future__ import annotations

import re
import unicodedata

from lifepilot.models import Person


_RELATIONSHIPS: dict[str, tuple[str, str]] = {
    "parent": ("parent", "outgoing"),
    "parent of": ("parent", "outgoing"),
    "elternteil": ("parent", "outgoing"),
    "elternteil von": ("parent", "outgoing"),
    "eltern": ("parent", "outgoing"),
    "mutter von": ("parent", "outgoing"),
    "vater von": ("parent", "outgoing"),
    "mother of": ("parent", "outgoing"),
    "father of": ("parent", "outgoing"),
    "child": ("child", "outgoing"),
    "child of": ("child", "outgoing"),
    "kind": ("child", "outgoing"),
    "kind von": ("child", "outgoing"),
    "tochter von": ("child", "outgoing"),
    "sohn von": ("child", "outgoing"),
    "daughter of": ("child", "outgoing"),
    "son of": ("child", "outgoing"),
    "spouse": ("spouse", "outgoing"),
    "spouse of": ("spouse", "outgoing"),
    "ehepartner": ("spouse", "outgoing"),
    "ehepartner von": ("spouse", "outgoing"),
    "ehefrau": ("spouse", "outgoing"),
    "ehefrau von": ("spouse", "outgoing"),
    "frau von": ("spouse", "outgoing"),
    "ehemann": ("spouse", "outgoing"),
    "ehemann von": ("spouse", "outgoing"),
    "mann von": ("spouse", "outgoing"),
    "wife of": ("spouse", "outgoing"),
    "husband of": ("spouse", "outgoing"),
    "partner": ("partner", "outgoing"),
    "partner of": ("partner", "outgoing"),
    "partner von": ("partner", "outgoing"),
    "partnerin von": ("partner", "outgoing"),
    "sibling": ("sibling", "outgoing"),
    "sibling of": ("sibling", "outgoing"),
    "geschwister": ("sibling", "outgoing"),
    "geschwister von": ("sibling", "outgoing"),
    "bruder von": ("sibling", "outgoing"),
    "schwester von": ("sibling", "outgoing"),
    "brother of": ("sibling", "outgoing"),
    "sister of": ("sibling", "outgoing"),
    "friend": ("friend", "outgoing"),
    "friends": ("friend", "outgoing"),
    "freund": ("friend", "outgoing"),
    "freundin": ("friend", "outgoing"),
    "freunde": ("friend", "outgoing"),
    "colleague": ("colleague", "outgoing"),
    "colleague of": ("colleague", "outgoing"),
    "kollege": ("colleague", "outgoing"),
    "kollege von": ("colleague", "outgoing"),
    "kollegin": ("colleague", "outgoing"),
    "kollegin von": ("colleague", "outgoing"),
    "arbeitskollege": ("colleague", "outgoing"),
    "arbeitskollege von": ("colleague", "outgoing"),
    "arbeitskollegin": ("colleague", "outgoing"),
    "arbeitskollegin von": ("colleague", "outgoing"),
}


def _normalize(role: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", role or "").casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized).split())


def relationship_category(role: str | None) -> tuple[str, str] | None:
    return _RELATIONSHIPS.get(_normalize(role))


def gender_evidence(role: str | None) -> str | None:
    normalized = _normalize(role)
    female_roles = {
        "mutter von", "tochter von", "ehefrau", "ehefrau von", "frau von",
        "schwester von", "sister of", "daughter of", "wife of",
        "kollegin", "kollegin von", "arbeitskollegin", "arbeitskollegin von",
    }
    male_roles = {
        "vater von", "sohn von", "ehemann", "ehemann von", "mann von",
        "bruder von", "brother of", "son of", "husband of",
        "kollege", "kollege von", "arbeitskollege", "arbeitskollege von",
    }
    if normalized in female_roles:
        return "female"
    if normalized in male_roles:
        return "male"
    return None


def _label(category: str, gender: str) -> str:
    labels = {
        "parent": {"female": "Mutter von", "male": "Vater von", "neutral": "Elternteil von"},
        "child": {"female": "Tochter von", "male": "Sohn von", "neutral": "Kind von"},
        "spouse": {"female": "Ehefrau von", "male": "Ehemann von", "neutral": "Ehepartner von"},
        "partner": {"female": "Partnerin von", "male": "Partner von", "neutral": "Partnerperson von"},
        "sibling": {"female": "Schwester von", "male": "Bruder von", "neutral": "Geschwister von"},
        "friend": {"female": "Freunde", "male": "Freunde", "neutral": "Freunde"},
        "colleague": {"female": "Arbeitskollegin von", "male": "Arbeitskollege von", "neutral": "Kolleg:in von"},
    }
    return labels[category].get(gender, labels[category]["neutral"])


def apply_relationship_gender(source: Person, target: Person, role: str, inverse_role: str | None) -> tuple[str, str]:
    source_gender = gender_evidence(role)
    target_gender = gender_evidence(inverse_role)
    if relationship_category(role) == ("colleague", "outgoing") and source_gender == target_gender:
        target_gender = None
    if source.gender == "unspecified" and source_gender:
        source.gender = source_gender
    if target.gender == "unspecified" and target_gender:
        target.gender = target_gender

    relation = relationship_category(role)
    inverse = relationship_category(inverse_role)
    if relation is None and inverse is None:
        return role, inverse_role or "Beziehung zu"

    if relation is not None:
        category, _ = relation
    else:
        category, _ = inverse or ("", "")
        if category in {"parent", "child"}:
            category = "child" if category == "parent" else "parent"
    if not category:
        return role, inverse_role or "Beziehung zu"

    if category == "child":
        source_label = _label("child", source.gender)
        inverse_label = _label("parent", target.gender)
    elif category == "parent":
        source_label = _label("parent", source.gender)
        inverse_label = _label("child", target.gender)
    else:
        source_label = _label(category, source.gender)
        inverse_label = _label(category, target.gender)
    return source_label, inverse_label


def refresh_relationship_labels(db, owner_id: str, person: Person) -> None:
    from lifepilot.models import Relationship
    from sqlalchemy import or_, select

    rows = db.scalars(
        select(Relationship).where(
            Relationship.owner_id == owner_id,
            or_(Relationship.source_person_id == person.id, Relationship.target_person_id == person.id),
        )
    ).all()
    people_ids = {endpoint_id for row in rows for endpoint_id in (row.source_person_id, row.target_person_id)}
    people = {
        row.id: row
        for row in db.scalars(
            select(Person).where(Person.owner_id == owner_id, Person.id.in_(people_ids))
        ).all()
    }
    for row in rows:
        source = people.get(row.source_person_id)
        target = people.get(row.target_person_id)
        if source is None or target is None:
            continue
        labels = apply_relationship_gender(source, target, row.relationship_type, row.inverse_relationship_type)
        row.relationship_type, row.inverse_relationship_type = labels


def owner_relationship_label(role: str, person_gender: str) -> str:
    kind = _normalize(role)
    role_to_category = {
        "parent": "parent", "elternteil": "parent",
        "child": "child", "kind": "child",
        "spouse": "spouse", "ehepartner": "spouse",
        "partner": "partner", "sibling": "sibling", "geschwister": "sibling",
        "friend": "friend", "freunde": "friend", "colleague": "colleague",
    }
    category = role_to_category.get(kind)
    if category is None:
        return role.strip()
    gender = person_gender if person_gender in {"female", "male", "diverse"} else "unspecified"
    labels = {
        "parent": {"female": "Mutter", "male": "Vater", "neutral": "Elternteil"},
        "child": {"female": "Tochter", "male": "Sohn", "neutral": "Kind"},
        "spouse": {"female": "Ehefrau", "male": "Ehemann", "neutral": "Ehepartner"},
        "partner": {"female": "Partnerin", "male": "Partner", "neutral": "Partnerperson"},
        "sibling": {"female": "Schwester", "male": "Bruder", "neutral": "Geschwister"},
        "friend": {"female": "Freundin", "male": "Freund", "neutral": "Freund:in"},
        "colleague": {"female": "Arbeitskollegin", "male": "Arbeitskollege", "neutral": "Arbeitskolleg:in"},
    }
    return labels[category].get(gender, labels[category]["neutral"])
