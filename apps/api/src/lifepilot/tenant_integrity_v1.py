"""Frozen database guard definitions for migration 0055; do not modify in place."""
from collections import defaultdict

from sqlalchemy import text

# Shared family space references intentionally do not require matching owner IDs.
LINKS = (
    ("person_contact_methods","person_id","people","id"),
    ("person_call_logs","person_id","people","id"),
    ("person_organizations","person_id","people","id"),
    ("person_organizations","organization_id","organizations","id"),
    ("person_name_history","person_id","people","id"),
    ("person_name_history","source_capture_id","captures","id"),
    ("person_life_events","person_id","people","id"),
    ("person_life_events","source_capture_id","captures","id"),
    ("memories","person_id","people","id"),
    ("memories","source_capture_id","captures","id"),
    ("journal_entry_people","entry_id","journal_entries","id"),
    ("journal_entry_people","person_id","people","id"),
    ("journal_entry_projects","entry_id","journal_entries","id"),
    ("journal_entry_projects","project_id","projects","id"),
    ("journal_entry_events","entry_id","journal_entries","id"),
    ("journal_entry_events","event_id","events","id"),
    ("pet_people","pet_id","pets","id"),
    ("pet_people","person_id","people","id"),
    ("pet_events","pet_id","pets","id"),
    ("pet_events","event_id","events","id"),
    ("memory_embeddings","memory_id","memories","id"),
    ("entity_embeddings","conversation_id","conversations","id"),
    ("entity_embeddings","task_id","tasks","id"),
    ("entity_embeddings","relationship_id","relationships","id"),
    ("entity_embeddings","project_id","projects","id"),
    ("tasks","person_id","people","id"),
    ("tasks","project_id","projects","id"),
    ("relationships","source_person_id","people","id"),
    ("relationships","target_person_id","people","id"),
    ("relationships","source_memory_id","memories","id"),
    ("user_person_relationships","person_id","people","id"),
    ("user_person_relationships","source_capture_id","captures","id"),
    ("conversation_participants","conversation_id","conversations","id"),
    ("conversation_participants","person_id","people","id"),
    ("loans","lender_person_id","people","id"),
    ("loans","borrower_person_id","people","id"),
    ("loans","source_memory_id","memories","id"),
    ("gifts","person_id","people","id"),
    ("gifts","source_memory_id","memories","id"),
    ("events","source_memory_id","memories","id"),
    ("event_participants","event_id","events","id"),
    ("event_participants","person_id","people","id"),
    ("event_photos","event_id","events","id"),
    ("reminders","task_id","tasks","id"),
    ("reminders","event_id","events","id"),
    ("reminders","birthday_person_id","people","id"),
    ("reminders","contact_person_id","people","id"),
    ("captures","parent_capture_id","captures","id"),
    ("conversation_projects","conversation_id","conversations","id"),
    ("conversation_projects","project_id","projects","id"),
    ("memory_projects","memory_id","memories","id"),
    ("memory_projects","project_id","projects","id"),
    ("commitments","source_capture_id","captures","id"),
    ("commitments","person_id","people","id"),
    ("commitments","project_id","projects","id"),
    ("commitments","conversation_id","conversations","id"),
    ("work_checkpoints","task_id","tasks","id"),
    ("work_checkpoints","project_id","projects","id"),
    ("focus_sessions","task_id","tasks","id"),
    ("focus_sessions","checkpoint_id","work_checkpoints","id"),
    ("task_steps","task_id","tasks","id"),
    ("focus_checkins","session_id","focus_sessions","id"),
    ("temporal_facts","person_id","people","id"),
    ("temporal_facts","source_capture_id","captures","id"),
    ("fact_conflict_decisions","person_id","people","id"),
    ("fact_conflict_decisions","fact_a_id","temporal_facts","id"),
    ("fact_conflict_decisions","fact_b_id","temporal_facts","id"),
    ("face_training_cards","person_id","people","id"),
    ("document_indexes","id","attachments","id"),
    ("document_pages","document_id","document_indexes","id"),
    ("decision_entries","person_id","people","id"),
    ("decision_entries","project_id","projects","id"),
    ("decision_entries","memory_id","memories","id"),
    ("decision_entries","attachment_id","attachments","id"),
    ("decision_reviews","decision_id","decision_entries","id"),
    ("place_entries","place_id","places","id"),
    ("place_entries","person_id","people","id"),
    ("place_entries","event_id","events","id"),
    ("place_entries","conversation_id","conversations","id"),
    ("place_entries","memory_id","memories","id"),
    ("inventory_items","owner_person_id","people","id"),
    ("inventory_items","place_id","places","id"),
    ("inventory_items","receipt_attachment_id","attachments","id"),
    ("inventory_history","item_id","inventory_items","id"),
    ("inventory_loans","loan_id","loans","id"),
    ("inventory_loans","item_id","inventory_items","id"),
)
OWNED_TABLES = (
    "approval_requests",
    "attachments",
    "audit_events",
    "capture_keys",
    "captures",
    "commitments",
    "conversation_participants",
    "conversation_projects",
    "conversations",
    "dav_keys",
    "decision_entries",
    "decision_reviews",
    "document_indexes",
    "document_pages",
    "entity_embeddings",
    "event_participants",
    "event_photos",
    "events",
    "face_training_cards",
    "fact_conflict_decisions",
    "family_shares",
    "family_spaces",
    "focus_checkins",
    "focus_sessions",
    "gifts",
    "inventory_history",
    "inventory_items",
    "inventory_loans",
    "journal_entries",
    "journal_entry_events",
    "journal_entry_people",
    "journal_entry_projects",
    "loans",
    "memories",
    "memory_embeddings",
    "memory_projects",
    "organizations",
    "people",
    "person_call_logs",
    "person_contact_methods",
    "person_life_events",
    "person_name_history",
    "person_organizations",
    "pet_events",
    "pet_people",
    "pets",
    "place_entries",
    "places",
    "projects",
    "push_subscriptions",
    "relationships",
    "reminders",
    "resource_revisions",
    "routines",
    "task_steps",
    "tasks",
    "temporal_facts",
    "trash_entries",
    "user_person_relationships",
    "work_checkpoints",
)
POLYMORPHIC = {
    "attachments": ("resource_type", {"person":"people","memory":"memories","conversation":"conversations","event":"events","project":"projects"}),
    "family_shares": ("kind", {"memory":"memories","task":"tasks","event":"events","inventory":"inventory_items"}),
}


def groups():
    result=defaultdict(list)
    for table,column,target,pk in LINKS:
        result[table].append((column,target,pk))
    return result


def preflight(connection):
    """Never rewrite or silently delete inconsistent data; report counts only."""
    violations=[]
    for table,column,target,pk in LINKS:
        count=connection.execute(text(f"SELECT count(*) FROM {table} AS c JOIN {target} AS p ON p.{pk}=c.{column} WHERE c.owner_id<>p.owner_id")).scalar_one()
        if count:
            violations.append(f"{table}.{column}: {count}")
    for table,(kind,mapping) in POLYMORPHIC.items():
        for value,target in mapping.items():
            count=connection.execute(text(f"SELECT count(*) FROM {table} AS c JOIN {target} AS p ON p.id=c.resource_id WHERE c.{kind}=:kind AND c.owner_id<>p.owner_id"),{"kind":value}).scalar_one()
            if count:
                violations.append(f"{table}.{kind}={value}: {count}")
    if violations:
        raise RuntimeError("Kontofremde Datenbankverknüpfungen gefunden. Migration abgebrochen; Backup und manuelle Prüfung erforderlich: "+"; ".join(violations))


def install(connection):
    dialect=connection.dialect.name
    if dialect not in ("sqlite","postgresql"):
        raise RuntimeError("Nicht unterstützte Datenbank für Kontointegrität")
    grouped=groups()
    for table in OWNED_TABLES:
        refs=grouped.get(table,[])
        poly=POLYMORPHIC.get(table)
        if dialect=="sqlite":
            for action in ("INSERT","UPDATE"):
                checks=[]
                if action=="UPDATE":
                    checks.append("SELECT CASE WHEN NEW.owner_id IS NOT OLD.owner_id THEN RAISE(ABORT, 'tenant_integrity') END;")
                for column,target,pk in refs:
                    changed=f" AND NEW.{column} IS NOT OLD.{column}" if action=="UPDATE" else ""
                    checks.append(f"SELECT CASE WHEN NEW.{column} IS NOT NULL{changed} AND NOT EXISTS (SELECT 1 FROM {target} WHERE {pk}=NEW.{column} AND owner_id=NEW.owner_id) THEN RAISE(ABORT, 'tenant_integrity') END;")
                if poly:
                    kind,mapping=poly
                    changed=f" AND (NEW.resource_id IS NOT OLD.resource_id OR NEW.{kind} IS NOT OLD.{kind})" if action=="UPDATE" else ""
                    for value,target in mapping.items():
                        checks.append(f"SELECT CASE WHEN NEW.{kind}='{value}'{changed} AND NOT EXISTS (SELECT 1 FROM {target} WHERE id=NEW.resource_id AND owner_id=NEW.owner_id) THEN RAISE(ABORT, 'tenant_integrity') END;")
                if checks:
                    connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS lp_tenant_{table}_{action.lower()} BEFORE {action} ON {table} FOR EACH ROW BEGIN "+" ".join(checks)+" END")
        else:
            checks=["IF TG_OP = 'UPDATE' THEN IF NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN RAISE EXCEPTION 'tenant_integrity' USING ERRCODE = '23514'; END IF; END IF;"]
            def guard(column,target,pk,condition="TRUE",changed=None):
                changed=changed or f"NEW.{column} IS DISTINCT FROM OLD.{column}"
                # Native FK locking handles ordinary referenced rows; polymorphic
                # references also acquire KEY SHARE during validation.
                return (f"IF {condition} AND NEW.{column} IS NOT NULL THEN "
                        f"IF TG_OP = 'INSERT' OR ({changed}) THEN "
                        f"PERFORM 1 FROM {target} WHERE {pk}=NEW.{column} AND owner_id=NEW.owner_id FOR KEY SHARE; "
                        "IF NOT FOUND THEN RAISE EXCEPTION 'tenant_integrity' USING ERRCODE = '23514'; END IF; END IF; END IF;")
            for column,target,pk in refs:
                checks.append(guard(column,target,pk))
            if poly:
                kind,mapping=poly
                for value,target in mapping.items():
                    checks.append(guard("resource_id",target,"id",f"NEW.{kind}='{value}'",f"NEW.resource_id IS DISTINCT FROM OLD.resource_id OR NEW.{kind} IS DISTINCT FROM OLD.{kind}"))
            connection.exec_driver_sql(f"CREATE OR REPLACE FUNCTION lp_tenant_{table}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "+" ".join(checks)+" RETURN NEW; END; $$")
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS lp_tenant_guard ON {table}")
            connection.exec_driver_sql(f"CREATE TRIGGER lp_tenant_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION lp_tenant_{table}()")


def uninstall(connection):
    for table in OWNED_TABLES:
        if connection.dialect.name=="sqlite":
            for action in ("insert","update"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS lp_tenant_{table}_{action}")
        else:
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS lp_tenant_guard ON {table}")
            connection.exec_driver_sql(f"DROP FUNCTION IF EXISTS lp_tenant_{table}()")
