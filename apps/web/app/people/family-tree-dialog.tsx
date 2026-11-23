"use client";

import { useEffect, useMemo, useState } from "react";

export type FamilyTreePerson = {
  id: string;
  first_name: string;
  last_name: string;
  nickname: string | null;
  gender: string;
  birthday: string | null;
  birthday_precision: string;
  photo_key: string | null;
};

type FamilyTreeRelationship = {
  id: string;
  source_person_id: string;
  target_person_id: string;
  relationship_type: string;
  inverse_relationship_type: string;
  confirmed: boolean;
};

export type FamilyTree = { root_person_id: string; people: FamilyTreePerson[]; relationships: FamilyTreeRelationship[] };
type PositionedPerson = { person: FamilyTreePerson; generation: number; x: number; y: number };

const FAMILY_TYPES: Record<string, string> = {
  "mutter von": "Mutter", "vater von": "Vater", "elternteil von": "Elternteil", "parent of": "Elternteil",
  "tochter von": "Tochter", "sohn von": "Sohn", "kind von": "Kind", "child of": "Kind",
  "ehefrau von": "Ehepartnerin", "ehemann von": "Ehepartner", "ehepartner von": "Ehepartner",
  "frau von": "Ehepartnerin", "mann von": "Ehepartner", "wife of": "Ehepartnerin", "husband of": "Ehepartner",
  "partnerin von": "Partnerin", "partner von": "Partner", "partnerperson von": "Partnerperson",
  "bruder von": "Bruder", "schwester von": "Schwester", "geschwister von": "Geschwister",
  "sibling of": "Geschwister", "brother of": "Bruder", "sister of": "Schwester",
};

function category(label: string): "parent" | "child" | "peer" {
  const normalized = label.toLocaleLowerCase("de-DE").replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  if (["mutter von", "vater von", "elternteil von", "parent of", "eltern von"].includes(normalized)) return "parent";
  if (["tochter von", "sohn von", "kind von", "child of"].includes(normalized)) return "child";
  return "peer";
}

function ageLabel(person: FamilyTreePerson): string | null {
  if (person.birthday_precision === "approximate") return null;
  if (!person.birthday || person.birthday_precision !== "exact") return null;
  const birth = new Date(`${person.birthday}T00:00:00`);
  if (Number.isNaN(birth.valueOf())) return null;
  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const month = today.getMonth() - birth.getMonth();
  if (month < 0 || (month === 0 && today.getDate() < birth.getDate())) age -= 1;
  return age >= 0 ? `${age} Jahre` : null;
}

export function FamilyTreeDialog({
  person,
  request,
  onClose,
  renderPhoto,
}: {
  person: Pick<FamilyTreePerson, "id" | "first_name" | "last_name">;
  request: (path: string, init?: RequestInit) => Promise<FamilyTree>;
  onClose: () => void;
  renderPhoto: (person: FamilyTreePerson) => React.ReactNode;
}) {
  const [tree, setTree] = useState<FamilyTree | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void request(`/api/people/${person.id}/family-tree`, { signal: controller.signal })
      .then(setTree)
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Der Stammbaum konnte nicht geladen werden.");
      });
    return () => controller.abort();
  }, [person.id, request]);

  const layout = useMemo(() => {
    if (!tree) return null;
    const peopleById = new Map(tree.people.map(item => [item.id, item]));
    const edges = tree.relationships.flatMap(edge => {
      const direct = category(edge.relationship_type);
      const reverse = category(edge.inverse_relationship_type);
      let parentId: string;
      let childId: string;
      let peer = false;
      if (direct === "parent") { parentId = edge.source_person_id; childId = edge.target_person_id; }
      else if (direct === "child") { parentId = edge.target_person_id; childId = edge.source_person_id; }
      else if (reverse === "parent") { parentId = edge.target_person_id; childId = edge.source_person_id; }
      else if (reverse === "child") { parentId = edge.source_person_id; childId = edge.target_person_id; }
      else { parentId = edge.source_person_id; childId = edge.target_person_id; peer = true; }
      return peopleById.has(parentId) && peopleById.has(childId) ? [{ ...edge, parentId, childId, peer }] : [];
    });
    const generations = new Map<string, number>([[tree.root_person_id, 0]]);
    const queue = [tree.root_person_id];
    while (queue.length) {
      const current = queue.shift()!;
      const currentGeneration = generations.get(current)!;
      for (const edge of edges) {
        const adjacent = edge.parentId === current ? edge.childId : edge.childId === current ? edge.parentId : edge.peer && edge.parentId === current ? edge.childId : edge.peer && edge.childId === current ? edge.parentId : null;
        if (!adjacent || generations.has(adjacent)) continue;
        const nextGeneration = edge.peer ? currentGeneration : edge.parentId === current ? currentGeneration + 1 : currentGeneration - 1;
        generations.set(adjacent, nextGeneration);
        queue.push(adjacent);
      }
    }
    const groups = new Map<number, FamilyTreePerson[]>();
    for (const item of tree.people) {
      const generation = generations.get(item.id) ?? 0;
      groups.set(generation, [...(groups.get(generation) ?? []), item]);
    }
    for (const group of groups.values()) group.sort((a, b) => a.id === tree.root_person_id ? -1 : b.id === tree.root_person_id ? 1 : `${a.first_name} ${a.last_name}`.localeCompare(`${b.first_name} ${b.last_name}`, "de"));
    const minGeneration = Math.min(...groups.keys());
    const maxGeneration = Math.max(...groups.keys());
    const maxRows = Math.max(...[...groups.values()].map(group => group.length), 1);
    const columnWidth = 232;
    const rowHeight = 142;
    const positions: PositionedPerson[] = [];
    for (const [generation, group] of groups) group.forEach((item, index) => positions.push({ person: item, generation, x: (generation - minGeneration) * columnWidth + 20, y: index * rowHeight + 28 }));
    return { edges, positions, byId: new Map(positions.map(item => [item.person.id, item])), width: (maxGeneration - minGeneration + 1) * columnWidth + 40, height: maxRows * rowHeight + 48 };
  }, [tree]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return <div className="dialog-backdrop profile-dialog-backdrop family-tree-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="card family-tree-dialog" role="dialog" aria-modal="true" aria-labelledby="family-tree-title">
      <div className="panel-head"><div><span className="eyebrow">FAMILIE</span><h2 id="family-tree-title">Stammbaum von {person.first_name} {person.last_name}</h2><p className="muted">Vorfahren, Nachkommen und verbundene Familienmitglieder</p></div><button type="button" className="quiet" onClick={onClose} aria-label="Stammbaum schließen">×</button></div>
      <div className="family-tree-legend"><span><i /> Bestätigt</span><span><i className="unconfirmed" /> Noch unbestätigt</span><span>Jede Karte öffnet das Personenprofil.</span></div>
      {error && <p className="error" role="alert">{error}</p>}
      {!tree && !error && <p className="empty" role="status">Stammbaum wird geladen …</p>}
      {tree && layout && <div className="family-tree-scroll" aria-label="Stammbaumdiagramm">
        <div className="family-tree-canvas" style={{ width: layout.width, height: layout.height }}>
          <svg className="family-tree-lines" width={layout.width} height={layout.height} aria-hidden="true">
            {layout.edges.map(edge => {
              const from = layout.byId.get(edge.parentId); const to = layout.byId.get(edge.childId);
              if (!from || !to) return null;
              const a = { x: from.x + 184, y: from.y + 52 }; const b = { x: to.x, y: to.y + 52 };
              const middle = edge.peer ? a.x + 54 : (a.x + b.x) / 2;
              const d = edge.peer ? `M ${a.x} ${a.y} C ${a.x + 54} ${a.y}, ${b.x + 238} ${b.y}, ${b.x + 184} ${b.y}` : `M ${a.x} ${a.y} C ${middle} ${a.y}, ${middle} ${b.y}, ${b.x} ${b.y}`;
              const label = edge.peer ? FAMILY_TYPES[edge.relationship_type.toLocaleLowerCase("de-DE")] ?? FAMILY_TYPES[edge.inverse_relationship_type.toLocaleLowerCase("de-DE")] ?? "Familie" : "";
              return <g key={edge.id}><path d={d} className={edge.confirmed ? "family-tree-edge" : "family-tree-edge pending"} />{label && <text x={middle} y={Math.min(a.y, b.y) - 8} className="family-tree-edge-label">{label}</text>}</g>;
            })}
          </svg>
          {layout.positions.map(({ person: node, x, y }) => <a key={node.id} className={`family-tree-node${node.id === tree.root_person_id ? " current" : ""}`} href={`/people/${node.id}`} style={{ left: x, top: y }} aria-label={`Profil von ${node.first_name} ${node.last_name} öffnen`}>
            {renderPhoto(node)}<span className="family-tree-node-name">{node.first_name} {node.last_name}</span>{node.nickname && <span className="family-tree-node-meta">„{node.nickname}“</span>}{ageLabel(node) && <span className="family-tree-node-meta">{ageLabel(node)}</span>}
          </a>)}
        </div>
      </div>}
      {tree && tree.people.length === 1 && <p className="empty">Für diese Person sind noch keine Familienbeziehungen hinterlegt.</p>}
    </section>
  </div>;
}
