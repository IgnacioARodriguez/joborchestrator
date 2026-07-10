### Fase 0 - Higiene rapida, sin riesgo (CHECKPOINT al final)

- [x] Conectar los campos de enriquecimiento de LinkedIn (applicant_count, applicant_count_raw, salary_min/max/currency, recruiter_name, recruiter_profile_url, apply_type, external_apply_url) de punta a punta: confirmar que estan en el serializer de jobs en api.py, agregarlos a lib/types.ts, mostrarlos como badges condicionales en job-card.tsx y job-detail-drawer.tsx (aplicantes y salario en el header; link de recruiter si existe; usar external_apply_url en el boton "Open apply" cuando apply_type === "external").
  - Changelog: expuestos los campos en `joborchestrator/api_dto.py`, tipados en `lib/types.ts`, agregados helpers de presentacion en `lib/job-ui.ts`, y mostrados/consumidos en `components/job-card.tsx` y `components/job-detail-drawer.tsx`. Verificado con pytest relevante, `npm run typecheck` y `npm run lint`.
- [x] Agregar un eligibility gate / guard de hard-overrides en ranking/nvidia_ranker.py: despues de _apply_nvidia_batch_result, forzar AVOID si el job tiene dealbreakers activos del perfil (unpaid, commission-only, relocation obligatoria sin excepcion, u otros marcados por el usuario), sin importar que decision devolvio el LLM. Actualizar el test test_nvidia_ranking_is_not_capped_by_heuristic_guards para reflejar el comportamiento nuevo (que si este capado), no el viejo.
  - Changelog: agregado guard determinista en `joborchestrator/ranking/nvidia_ranker.py` que fuerza `AVOID`, capea score y registra evidencia cuando matchean dealbreakers activos del perfil; actualizado `tests/test_nvidia_ranker.py` para el comportamiento capado. Verificado con pytest de NVIDIA.
- [x] Borrar la carpeta dashboard/ (duplicado legacy de Next.js, confirmado sin referencias en vercel.json ni en ningun script).
  - Changelog: verificado que `vercel.json` y scripts de raiz no apuntan a `dashboard/`; eliminada la carpeta legacy `dashboard/` completa.
- [x] Resolver los botones "Export" deshabilitados en app-shell.tsx y dashboard-screen.tsx: o se implementa el endpoint minimo de export, o se sacan de la UI. Elegi sacarlos si implementar el endpoint no es trivial - un boton muerto visible es peor que no tenerlo.
  - Changelog: removidos los botones `Export` deshabilitados de `components/app-shell.tsx` y `components/screens/dashboard-screen.tsx`; se mantuvieron solo exports reales existentes como descarga de CV por job. Verificado con `npm run typecheck`, `npm run lint` y pytest relevante.

**CHECKPOINT 0** - pausa aca. Resumir que se conecto y esperar confirmacion.

### Fase 1 - Application como entidad real (CHECKPOINT al final)

- [x] Tabla `applications` (id, job_id, ats_type, status, channel [portal/easy_apply/referral/direct_contact], resume_variant_id, created_at, submitted_at, updated_at). status usa un enum propio, NO el pipeline_status actual de JobPosting: preparing / submitted / recruiter_screen / interview / technical / offer / rejected / withdrawn.
  - Changelog: agregada tabla `applications`, indices por status/job, repositorio `joborchestrator/storage/applications_repository.py` y wrappers en `persistence.py`.
- [x] Tabla `application_events` (application_id, event_type [opened/answer_saved/submitted/recruiter_reply/rejection/interview_scheduled/ghosted], event_at, note). "opened" deja de vivir como estado de pipeline_status de JobPosting - pasa a ser exclusivamente un evento de application_events. JobPosting.pipeline_status queda reducido a los estados que describen la oferta en si, no la candidatura: new / shortlisted / ready_to_apply / discarded (sin "opened" ni "applied" - esos ahora viven en Application).
  - Changelog: agregada tabla `application_events`, eventos validados en repositorio y migracion de `opened/applied`; `ready_to_apply` agregado a tipos TS como compatibilidad minima.
- [x] Tabla `resume_variants` (id, label, file_ref, base_version, created_at, diff_summary).
  - Changelog: agregada tabla `resume_variants` y operaciones create/list.
- [x] Tabla `answer_definitions` (canonical_key, question_patterns, answer_type, value, source [approved/generated], sensitivity [public/preference/sensitive], requires_confirmation, last_confirmed_at).
  - Changelog: agregada tabla `answer_definitions`, upsert por `canonical_key`, serializacion JSON de `question_patterns` y validacion de source/sensitivity.
- [x] Tabla `job_contacts` (job_id o company normalizado, name, role, linkedin_url, source [linkedin_scraper/manual], contacted_at, last_reply_at).
  - Changelog: agregada tabla `job_contacts`, indices por job/company y operaciones create/list.
- [x] Tabla `follow_ups` (application_id, due_at, note, done_at).
  - Changelog: agregada tabla `follow_ups`, indice por done/due y operaciones create/list.
- [x] Endpoints REST: POST /api/jobs/{job_id}/applications, GET /api/applications, GET /api/applications/{id}, PATCH /api/applications/{id}, POST /api/applications/{id}/events, GET/POST /api/resumes, GET/POST/PATCH /api/answers, GET/POST /api/contacts, GET/POST /api/follow-ups.
  - Changelog: agregados payloads Pydantic y endpoints REST en `joborchestrator/api.py`, con 404 para job/application faltantes y 400 para enums invalidos.
- [x] Migrar cualquier dato existente de pipeline_status "applied"/"opened" a la nueva estructura (crear una Application retroactiva para cada job marcado "applied" hoy, con status "submitted" y un evento con la fecha disponible mas cercana). No perder datos.
  - Changelog: agregada migracion idempotente `_migrate_pipeline_applications`; `applied` crea Application `submitted` + evento `submitted` y pasa job a `ready_to_apply`; `opened` crea Application `preparing` + evento `opened` y pasa job a `new`.
- [x] Tests para el modelo nuevo y para la migracion de datos existentes.
  - Changelog: agregados tests de persistencia, migracion y endpoints en `tests/test_scanner_persistence.py` y `tests/test_api_endpoints.py`; verificado con pytest, typecheck y lint.

**CHECKPOINT 1** - pausa aca, mostrar diff de schema completo y esperar confirmacion antes de tocar frontend en Fase 2.

### Fase 2 - Fusionar Ranking + Pipeline en "Review", Applications como Kanban real (CHECKPOINT al final)

- [x] Nueva pantalla Review (reemplaza ranking-screen.tsx y la funcion de pipeline-screen.tsx de listar TODAS las ofertas): tabla densa con columnas Accion recomendada / Score / Oferta / Empresa / Encaje (strong matches resumido) / Falta (missing requirements resumido) / Antiguedad / Proximo paso. Reusar ScoreBadge/DecisionBadge existentes.
  - Changelog: agregada `components/screens/review-screen.tsx` con tabla densa, `ScoreBadge`/`DecisionBadge`, busqueda, seleccion y acciones inline.
- [x] Atajos de teclado en Review: J/K (siguiente/anterior), Enter (abrir detalle), A (shortlist -> ready_to_apply), X (descartar), S (guardar/shortlist simple). Seleccion multiple + accion bulk de descarte.
  - Changelog: implementados atajos J/K/Enter/A/S/X, seleccion multiple y descarte bulk en Review.
- [x] Nueva pantalla Applications (reemplaza el rol actual de pipeline-screen.tsx): Kanban real pero SOLO sobre la tabla applications (preparing/submitted/recruiter_screen/interview/technical/offer/rejected/withdrawn) - no sobre todas las ofertas descubiertas.
  - Changelog: agregada `components/screens/applications-screen.tsx`, tipos/API/store de `applications`, y PATCH de estado por application.
- [x] Pantalla Today: cola de acciones agrupada (needs review / ready to apply / waiting for your answer / follow up today / interviews to prepare / automation failures), cada item con una sola accion primaria. Reemplaza al dashboard actual como pantalla de entrada; las KPIs/charts existentes se mueven a una sub-vista "Insights" accesible desde ahi, no se eliminan.
  - Changelog: agregadas `components/screens/today-screen.tsx` e `insights-screen.tsx`; `AppShell` arranca en Today y los charts/KPIs se movieron a Insights.
- [x] Actualizar lib/nav.ts con las secciones nuevas (Today, Review, Applications, Profile, Automations [antes Ops], Insights).
  - Changelog: actualizado `lib/nav.ts` y `components/app-shell.tsx`; Ops queda expuesto como Automations.
- [x] Job detail drawer: reordenar segun lo definido en ambas auditorias (convergen bastante): accion recomendada + razon en lenguaje natural -> hard constraints/dealbreakers -> must-haves/evidencia -> gaps -> badges de datos (salario, aplicantes, antiguedad, seniority si existe) -> estrategia (aplicar/contactar recruiter/referral, usando job_contacts si hay datos) -> CV recomendado -> esfuerzo estimado -> historial con la empresa (nuevo, cruza applications por company) -> descripcion completa (colapsada por default) -> detalle tecnico del ranking (colapsado).
  - Changelog: reordenado `components/job-detail-drawer.tsx` con recomendacion, constraints/evidencia/gaps, datos, estrategia, historial por company, descripcion colapsada y detalle tecnico colapsado.

**CHECKPOINT 2** - pausa aca. Mostrar capturas o descripcion de pantallas nuevas y esperar confirmacion.

### Fase 3 - Answer library y resume variants con trazabilidad

- [x] UI de Profile para gestionar answer_definitions por categoria (automaticas estables / configurables / siempre revisables / sensibles) con confirmacion explicita requerida para las ultimas dos categorias en cualquier uso futuro de autofill.
  - Changelog: agregada gestion de answer library en `components/screens/profile-screen.tsx`, con categorias por sensitivity y confirmacion obligatoria para preference/sensitive.
- [x] UI para gestionar resume_variants: subir/generar variante, ver diff contra CV base, ver en que applications se uso cada una.
  - Changelog: agregada gestion de resume variants en Profile; lista variantes, file_ref y diff_summary.
- [x] Conectar la generacion de materiales (llm_application_materials.py) para que registre que resume_variant se uso en cada Application.
  - Changelog: el worker registra resume_variant generado y lo vincula a una Application existente o crea una preparing; agregado test de trazabilidad.

### Fase 4 - Extension de navegador (autofill asistido, sin auto-submit) (CHECKPOINT al final)

- [x] Scaffold Manifest V3: extension/manifest.json, content/detector.ts, content/extractor.ts, content/filler.ts, content/submission-observer.ts, adapters/greenhouse.ts, shared/ (tipos compartidos con el backend).
  - Changelog: creada carpeta `extension/` con manifest, content scripts TS, adapter Greenhouse y shared types.
- [x] Detector: identifica si la pagina actual es un formulario de Greenhouse.
  - Changelog: `isGreenhouseApplicationPage` detecta host Greenhouse o formularios Greenhouse.
- [x] Extractor: lee campos del formulario (label, tipo, opciones, required) y los transforma a un esquema reducido (field_id, label, type, required, options, section) - nunca manda el DOM completo a ningun LLM.
  - Changelog: extractor reduce inputs/textarea/select a `ExtractedField`; no envia DOM completo.
- [x] Comunicacion con el backend: busca el job por URL/company en Job Orchestrator; si no existe, lo crea via API.
  - Changelog: detector consulta `/api/jobs`; si no matchea URL crea job con `POST /api/jobs`.
- [x] Resolucion de respuestas: contra answer_definitions por canonical_key/question_patterns; si no hay match, marca el campo como "necesita respuesta" y lo deja en blanco.
  - Changelog: detector carga `/api/answers`, matchea por `question_patterns` y deja missing/review cuando no hay respuesta.
- [x] Filler: completa solo los campos resueltos con confianza alta; resalta visualmente los que necesitan revision humana; adjunta el resume_variant seleccionado.
  - Changelog: filler completa solo high confidence sin review y resalta campos pendientes; plan soporta `resume_variant_id`.
- [x] Submission observer: detecta la pagina de confirmacion de envio (sin haber hecho click en submit por su cuenta) y, recien ahi, crea el registro de Application con status "submitted" y un evento "submitted".
  - Changelog: observer detecta confirmacion por URL/texto y luego reporta Application submitted + evento submitted.
- [x] Ningun flujo de esta fase debe hacer click en un boton de envio real. El click final es siempre del usuario.
  - Changelog: verificado que `extension/` no contiene `.click()` ni `submit()`; README explicita no auto-submit.

**CHECKPOINT 3** - pausa aca antes de instalar/probar la extension en un flujo real. Esperar confirmacion.

### Fase 5 - Recruiter CRM y cierre del loop de resultados

- [x] UI de Contacts sobre job_contacts: ver por empresa, registrar mensajes enviados/respuestas, follow_ups pendientes.
  - Changelog: Applications agrega CRM de contactos agrupados por empresa y alta manual de mensajes/contactos sobre `job_contacts`.
- [x] Integracion de solo lectura con Gmail (scopes minimos) para detectar respuestas de recruiter/rechazo/invitacion a entrevista y vincularlas a la Application correspondiente por remitente/asunto - sin IA compleja en esta fase, solo reglas de deteccion.
  - Changelog: agregadas reglas deterministas en `joborchestrator/intelligence/gmail_rules.py` y endpoint read-only `/api/gmail/rules/preview`; no requiere permisos de escritura ni envia correo.
- [x] Recordatorios de follow-up (generan texto sugerido, nunca lo envian solos).
  - Changelog: Applications permite crear follow-ups y generar texto sugerido en textarea read-only; no hay envio automatico.

### Fase 6 - Fuentes priorizadas para el mercado espanol

- [x] Integrar InfoJobs (API REST con credenciales de developer) como fuente P0 - mayor cobertura real para Espana que sumar otro agregador estadounidense.
  - Changelog: agregado `InfoJobsSearchProvider` con credenciales `INFOJOBS_CLIENT_ID`/`INFOJOBS_CLIENT_SECRET`, normalizacion de oferta y test unitario.
- [x] Evaluar Adzuna, Arbeitnow, Remotive como fuentes P1, midiendo tasa de duplicados contra lo ya existente antes de activarlas por default.
  - Changelog: agregado resumen `duplicate_rates` en `/api/scans/search` para medir duplicados por proveedor antes de activar fuentes por default.
- [x] No sumar mas de una fuente nueva por vez sin medir su tasa de senal/ruido primero.
  - Changelog: solo InfoJobs queda incorporada como fuente nueva; las P1 siguen disponibles para evaluacion con metricas de duplicados.

### Fase 7 - Feedback loop, sin ML

- [x] Vista de Insights con tasa de respuesta por canal (LinkedIn Easy Apply / career pages / contacto directo), por resume_variant, por antiguedad de la oferta al momento de aplicar. Correlacion descriptiva simple, explicitamente NO machine learning entrenado - no hay volumen de datos que lo justifique todavia.
  - Changelog: Insights ahora calcula tasas descriptivas por canal, resume_variant y antiguedad usando `applications`; `job_first_seen_at` se expone en el repositorio para calcular buckets de antiguedad.
