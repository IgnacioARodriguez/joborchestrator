# UI navigation transition

This checkpoint simplifies the visible app navigation to:

- `Jobs` (`/jobs`)
- `Aplicar` (`/apply`)
- `Aplicaciones` (`/applications`)
- `Configuración` (`/settings`)

Legacy compatibility:

- `/today` redirects to `/jobs`.
- `/review` redirects to `/jobs`.
- `/pipeline` redirects to `/apply`.
- `/profile`, `/automations`, and `/insights` remain available as transitional configuration surfaces and are linked from `/settings`.
- Hash aliases such as `#today` and `#review` resolve to Jobs inside the shell.

Transitional product choices:

- Jobs reuses the existing apply queue data, pagination, search, detail drawer, and pipeline-status mutations.
- Aplicar keeps the existing pipeline-oriented surface for now.
- Aplicaciones keeps the existing application kanban and CRM helpers.
- Configuración groups profile, operational automation/source controls, and advanced insights without redesigning those screens yet.
