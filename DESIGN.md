# LifePilot Design System

## Research Log

- Existing product surface: tokens and patterns extracted from `apps/web/app/style.css`; this is the established visual source of truth.
- StyleGallery: pattern selection skipped; the layout remains a document-scrolling dashboard with an expandable profile section and existing card/grid patterns.

## Tokens

- Light palette: background `#f6f5f2`, paper `#ffffff`, ink `#232622`, muted `#7e817a`, line `#e9e8e3`, green `#315c48`, pale green `#eaf0eb`, accent `#d9b574`, destructive action `#8b3d35`.
- Dark palette: background `#171a18`, paper `#202421`, ink `#e8ebe5`, muted `#a5aaa1`, line `#343a35`, green `#79a68a`, pale green `#28382e`, destructive action `#8b3d35`.
- Typography: DM Sans for interface text; Playfair Display for brand and primary headings.
- Existing primitives: `.card`, `.panel`, `.panel-head`, `.person-form`, `.list-item`, `.avatar`, `.quiet`.

## Layout

Layout: Application sections - keep people, memory, planning, objects, and review tasks focused and independently addressable -> fixed sidenav shell with route-based single content region; scroll owner: document; anti-patterns: unrelated sections in one long page, nested scroll areas, horizontal overflow at mobile width. Pattern reference: https://github.com/changeroa/StyleGallery/blob/main/patterns/viewport-shell/fixed-sidenav-shell.md

Layout: People directory and profile - browse the contact list, then inspect one person's details and relationship context -> route-based list-detail; scroll owner: document; anti-patterns: profile forms mixed into the directory, inaccessible destructive actions, relationship context without named people. Pattern reference: https://github.com/changeroa/StyleGallery/blob/main/patterns/split-sidebar/list-detail.md

Layout: People directory cards and relationship context - search, filter, and sort contacts, then follow linked profile cards grouped by relationship area -> responsive card grid in the directory and grouped card grids in profiles, with a separate top-right remove control; scroll owner: document; anti-patterns: profile photos without authorized delivery, non-clickable relationship names, club membership stored only as free text, or a remove action mixed into the identity link. Pattern reference: existing `.people-grid`, `.relationship-card-grid`, and `.organization-member-grid` patterns in `apps/web/app/style.css`.

Layout: Planning and appointments - enter one appointment with multiple participants and manage tasks in a focused planning view -> stacked planning sections; scroll owner: document; anti-patterns: single-person appointment selector, unlabeled participant controls, nested scroll areas. Pattern reference: https://github.com/changeroa/StyleGallery/blob/main/patterns/stacking/stack.md

Layout: Memory, objects, and review - navigate between episodic records, loans and gifts, and pending capture review -> route-based content sections with compact lists; scroll owner: document; anti-patterns: unrelated records sharing one page, destructive controls without confirmation.

Layout: LifePilot Chat - switch between capturing an original note and asking questions over cited database results -> focused single-column conversation with a bounded transcript and composer; scroll owner: `.chat-transcript` for conversation history, document for the page; anti-patterns: silently treating questions as facts, presenting generated answers without sources, hiding the review step.

Layout: Dashboard scheduling controls - create tasks and appointments, adjust a saved appointment, and set personal quiet hours -> existing dashboard cards with compact labeled forms and inline appointment details; scroll owner: document; anti-patterns: hidden required fields, nested scroll areas, horizontal overflow at mobile width.

Layout: Event archive - scan a month, select a date, then inspect an event's context, participant cards, place and photos -> calendar grid with one selected-event detail region below it; scroll owner: document; anti-patterns: mixing future reminders into past memories, unattached attendee names, photos without owner-scoped access, nested scroll areas.

## Screen brief: Dashboard scheduling controls

- Primary action: save a task, appointment, or personal schedule preference.
- Content priority: task title and deadline; appointment title and local start time; profile time zone and quiet-hours range.
- Interaction: optional repeat interval for dated tasks; appointment changes preserve duration and update their reminder.
- Excluded: calendar views, notification delivery preferences, and event recurrence.

## Screen briefs: Navigation update

### People directory and person profile
- Primary action: open a person profile from the directory; the profile's primary action is saving edits.
- Information priorities: searchable, filterable, sortable people cards with profile photo and age; prominent profile identity; grouped, clickable relationship and club membership cards.
- Left out on purpose: tasks, events, gifts, and loans unrelated to the selected person.
- Required content: first and last name, nickname, birthday, gender, email, phone, address, work, organization, notes, photo upload, age, search, filters, sorting, relationships grouped by family/friends/work/other, clickable linked profiles, gender-derived relationship labels, club and organization memberships (including the user's self profile), profile update, relationship add/remove, person delete with confirmation.
- Data shape -> component: many contacts use a filter bar and responsive card grid; one selected person is a dedicated detail view with prominent photo, edit form, grouped relationship cards, membership cards, and sourced context.

### Planning
- Primary action: save a task or appointment.
- Information priorities: upcoming appointments; participants; open tasks and deadlines.
- Left out on purpose: contact editing and unrelated capture review.
- Required content: task title, due time, repetition, appointment title, start, location, zero or more people, appointment edit/delete, task complete/delete.
- Data shape -> component: appointments and tasks are chronological/action lists; appointment participants use a multi-select.

### Events

- Primary action: capture a past event with its date and context, then find and open it from the calendar.
- Information priorities: selected date and event title; participant cards; place; contextual notes and event photos.
- Left out on purpose: future task/reminder management, which stays under Planning.
- Required content: past event creation from a reviewed chat capture, month navigation, date selection, event detail, participant cards linking to profiles, place name/address, photo upload and deletion.
- Data shape -> component: one month grid groups events by local date; selecting a calendar entry reveals a single detail surface with reusable people cards and an image grid.

### Memories, things, and inbox
- Primary action: save or review the record native to the current section.
- Information priorities: original notes and conversations; active loans and gift ideas; unreviewed captures and approvals.
- Left out on purpose: unrelated planning and profile forms.
- Required content: memories, conversations, sources, loans, returns, gift ideas, capture original text, suggestion review, approvals, confirmed deletions.
- Data shape -> component: chronological memories use a timeline; active object records use compact rows; review uses source-first articles with explicit actions.

### LifePilot Chat
- Primary action: save an unstructured note for review or ask a natural-language question about stored records.
- Information priorities: explicit mode, clear statement that capture is persisted before review, answer with clickable source records.
- Left out on purpose: automatic acceptance of extracted facts and unsupported model answers without retrieved data.
- Required content: capture/question switch, transcript, message composer, processing feedback, structured capture suggestions in the transcript, source cards, link to the review inbox, and a natural-language follow-up on an existing capture.
- Data shape -> component: capture requests use the durable, parent-linked capture pipeline; suggestions stay reviewable and are deduplicated against saved records; question requests use owner-scoped hybrid search and an OpenAI-compatible grounded response.

## Components and behavior

- Person records use a filterable directory; selecting a person opens a dedicated route with editable profile, relationships, and source-linked context.
- User profile is an editable settings route linked from the application header.
- Relationship rows identify both people and preserve the entered direction and relationship type.
- Forms use the existing two-column `.person-form`, collapsing to one column on narrow screens; labels remain visible.
- Events use a month grid and a selected-event detail surface. Participant cards link to person profiles; venue details and authorized photos stay with the event record.
