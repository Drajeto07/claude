# SmartDoc 2.0 -- roadmap

Live status: `SMARTDOC_2_0_MASTER_TRACKER.xlsx` (Roadmap and Tasks sheets). Each phase ends only with measurable
acceptance met (tests run, browser checked, preview built); a convincing mockup is not a finished feature.

| Phase | Milestones | Done when |
| --- | --- | --- |
| P0 Audit and baseline | audit, branch, spec, decisions, tracker, session state | the next session can resume from the repo alone |
| P1 Design system and shell | M1.1 tokens + Inter; M1.2 primitives (Button, TextField, Card, states); M1.3 app shell (top bar, left nav, responsive) | every new screen uses tokens/primitives; a11y checks; 375 px works |
| P2 Auth, Dashboard, New Project | M2.1 Login/Registration; M2.2 Dashboard gallery + search; M2.3 New Project chooser + AI prompt entry | existing accounts and documents work unchanged; e2e auth/dashboard pass |
| P3 Document creation | M3.1 Add Content; M3.2 Structure analysis + review (rename, level, reorder, reclassify); M3.3 Style recommendation + templates with preview | TXT/DOCX/PDF/paste reach the editor through review, content preserved |
| P4 Editor foundations | M4.1 editor layout v2; M4.2 selection model + hover outlines; M4.3 contextual toolbar + properties panel; M4.4 save state/autosave/recovery | existing editor + e2e specs pass; keyboard paths |
| P5 Free Design | M5.1 canvas kind + adapter; M5.2 elements (text, image, shape); M5.3 drag/resize/snap/layers/group; M5.4 sizes + export | canvas projects save, reopen and export; old documents untouched |
| P6 Templates + AI | M6.1 template library (both kinds); M6.2 proposal framework; M6.3 AI design/format actions | reject leaves the document unchanged (test); templates editable |
| P7 Translation | M7.1 Translate panel; M7.2 segment pipeline + overflow; M7.3 review + save as new; M7.4 bilingual compare | DOCX fidelity tests on representative documents |
| P8 Release readiness | regression, security/isolation, a11y, responsive, 1.x data compatibility, release checklist | an approvable candidate; owner's approval for any promote |

Order of the first milestones: M1.1 -> M1.2 -> M2.1 (visible on the preview the same day) -> M1.3 -> M2.2 -> M2.3.
