# Documentation

**Where it stands:** [final-production-readiness.md](final-production-readiness.md) -- the production-hardening
programme's final report (what changed, what is supported and not, test results, release gates, risks, what next).

| Folder | What |
| --- | --- |
| [architecture](architecture/) | the system as it stands and where it goes: current and target state, fidelity (import, export and PDF reports), jobs, the migration plan, the final audit |
| [document-model](document-model/README.md) | the document JSON: elements, runs and marks, tables, lists, sections, preserved pieces, proposals |
| [docx](docx/README.md) | Word import and export: what is kept, approximated or left out, and why |
| [pdf](pdf/README.md) | PDF in (inspection, reconstruction, editable or layout-focused, confidence, OCR) and out (fonts, scripts, the check after writing) |
| [fonts](fonts/README.md) | the font catalogue, the FontResolver, shaping and right-to-left text, the fonts a server needs |
| [translation](translation/README.md) | translations as proposals, the tag protocol, the checks, the glossary, metering |
| [ai](ai/README.md) | what the AI does and never does, prompts that keep documents apart from instructions, budgets |
| [formatting](formatting/README.md) | the formatting engine, rule priorities, templates and Format by Example, values |
| [security](security/README.md) | accounts and sessions, uploads, limits, headers and CSP, audit lines |
| [testing](testing/README.md) | the test suites, fixtures, end-to-end tests, mutation checks |
| [performance](performance/README.md) | the benchmarks, the UTF-8 storage change, the performance gate |
| [deployment](deployment/README.md) | the images, the services, settings, releasing, what is and isn't verified |
| [billing](billing/README.md) | plans, entitlements, metering, Stripe |
| [operations](operations/README.md) | log ids, metrics, what to alert on |

Working files: `AI-CONTINUATION.md` and `session-state.json` (where the work stands, for picking it up),
`implementation-brief.md` (the brief), `cloud-prompts/` and `cloud-reports/` (work done in cloud sessions),
`spec.md` (the original MVP specification).
