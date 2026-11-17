# LifePilot Design System

## Research Log

- Existing product surface: tokens and patterns extracted from `apps/web/app/style.css`; this is the established visual source of truth.
- StyleGallery: pattern selection skipped; the layout remains a document-scrolling dashboard with an expandable profile section and existing card/grid patterns.

## Tokens

- Light palette: background `#f6f5f2`, paper `#ffffff`, ink `#232622`, muted `#7e817a`, line `#e9e8e3`, green `#315c48`, pale green `#eaf0eb`, accent `#d9b574`.
- Dark palette: background `#171a18`, paper `#202421`, ink `#e8ebe5`, muted `#a5aaa1`, line `#343a35`, green `#79a68a`, pale green `#28382e`.
- Typography: DM Sans for interface text; Playfair Display for brand and primary headings.
- Existing primitives: `.card`, `.panel`, `.panel-head`, `.person-form`, `.list-item`, `.avatar`, `.quiet`.

## Layout

Layout: Dashboard people region - edit and inspect one selected person while retaining the overview -> expandable profile panel within the existing dashboard grid; scroll owner: document; anti-patterns: nested scroll areas, horizontal overflow at mobile width, disconnected relationship labels.

Layout: Dashboard scheduling controls - create tasks and appointments, adjust a saved appointment, and set personal quiet hours -> existing dashboard cards with compact labeled forms and inline appointment details; scroll owner: document; anti-patterns: hidden required fields, nested scroll areas, horizontal overflow at mobile width.

## Screen brief: Dashboard scheduling controls

- Primary action: save a task, appointment, or personal schedule preference.
- Content priority: task title and deadline; appointment title and local start time; profile time zone and quiet-hours range.
- Interaction: optional repeat interval for dated tasks; appointment changes preserve duration and update their reminder.
- Excluded: calendar views, notification delivery preferences, and event recurrence.

## Components and behavior

- Person records remain in the existing two-column dashboard card; selecting a person opens their editable profile and relationships in place.
- User profile is a compact editable panel reachable from the dashboard header.
- Relationship rows identify both people and preserve the entered direction and relationship type.
- Forms use the existing two-column `.person-form`, collapsing to one column on narrow screens; labels remain visible.
