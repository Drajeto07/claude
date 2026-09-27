<!-- The implementation brief Boril gave on 2026-09-27 (116 sections), kept verbatim so any session can
     follow it. Progress against it lives in SmartDoc_Master_Implementation_Tracker.xlsx and
     docs/AI-CONTINUATION.md. -->

Ти си Principal Software Architect, Senior Full-Stack Engineer, Document Processing Engineer, OOXML/DOCX Engineer, PDF Engineer, AI Systems Engineer, Security Engineer, QA Lead и DevOps Engineer.
РАБОТИШ ВЪРХУ СЪЩЕСТВУВАЩИЯ REPOSITORY НА:
SMARTDOC FORMATTER
==================================================
0. МИСИЯ
==================================================
Този prompt има за цел да превърне текущия SmartDoc Formatter в:
PRODUCTION-READY DOCUMENT TRANSFORMATION PLATFORM
със следната основна продуктова логика:
UPLOAD / PASTE
→ ANALYZE
→ PRESERVE
→ FORMAT
→ EDIT
→ TRANSLATE
→ CONVERT
→ REVIEW
→ EXPORT
Основната product promise е:
"Format, convert or translate your document without silently changing or destroying its content or structure."
Приложението НЕ трябва да се превръща в:
"AI chatbot with file upload"
и НЕ трябва да се превръща в:
"generic Word clone".
То трябва да бъде:
DOCUMENT ENGINE
+
AI INTELLIGENCE LAYER
AI:

* анализира
* класифицира
* предлага
* превежда
* извлича правила
* прави semantic mapping

ENGINE:

* валидира
* пази
* прилага
* редактира
* рендерира
* export-ва
* сравнява

==================================================
1. ЗАДЪЛЖИТЕЛНА ОСНОВА
==================================================
Текущият repository вече има реална основа:

* Next.js frontend
* FastAPI backend
* PostgreSQL
* migrations
* authentication/session architecture
* workspace ownership
* deterministic formatting engine
* StyleSystem
* templates
* AI provider abstraction
* structured AI output
* document model
* DOCX import/export
* PDF import/export
* editor
* background processing architecture
* billing/entitlements architecture
* tests
* E2E
* security controls

НЕ започвай от нулата.
НЕ изтривай работеща архитектура само за да я замениш с друга.
НЕ заменяй deterministic engine с AI.
НЕ премахвай validation layer.
НЕ премахвай structured outputs.
НЕ премахвай conflict-resolution системата.
==================================================
2. SOURCE OF TRUTH
==================================================
Source of truth е:

1. реалният repository
2. runtime behavior
3. реалните tests
4. реалните document fixtures
5. реалните exports/imports
6. audit evidence

Documentation НЕ е доказателство сама по себе си.
Ако README казва:
SUPPORTED
но реален round-trip test доказва:
LOSSY
→ feature-ът е LOSSY.
Никога не маркирай feature като DONE само защото има:

* component
* route
* class
* function
* schema
* UI control

Feature е DONE само ако:
IMPLEMENTED
+
INTEGRATED
+
TESTED
+
VERIFIED
==================================================
3. CURRENT AUDIT BASELINE
==================================================
Предишният audit установи следното.
Тези findings трябва да бъдат приети като CURRENT KNOWN RISKS и да бъдат адресирани.
Критичните:

1. Editor save може да изхвърли nested blocks:
   * lists
   * pictures
   * code
   * quotes
   * content inside table cells/list items
2. AI structure fidelity check може да пропусне:
   * text omissions
   * removed negation
   * number changes
   * inserted text
3. Import/export може silent да промени:
   * hidden text
   * list numbering
   * section headers
   * metadata
   * alt text
   * document structure
4. List numbering може да се промени:
   * "Чл. 1." → "1."
   * "(a)" → "a."
   * custom start values → default numbering
5. AI instruction operations могат да:
   * delete
   * insert
   * move
content без достатъчно user preview
6. Content controls / metadata / comment threads / sensitivity-related information могат да се загубят.
7. Image fidelity има gaps:
   * alt text
   * crop
   * rotation
   * picture formats
8. Table export може да променя:
   * header state
   * borders
   * alignment
   * widths
   * geometry
9. Големи изображения могат да предизвикат огромна memory consumption.
10. Големите tables имат performance problem.
11. Plan limits могат да имат concurrency race.
12. Malformed DOCX може да доведе до HTTP 500.
13. Опасни/неподходящи href/field инструкции трябва да бъдат филтрирани.
14. Account essentials трябва да бъдат проверени:

* password reset
* email verification
* password change
* account deletion

15. Operations/monitoring трябва да бъдат потвърдени.
16. Whole-document autosave трябва да бъде оптимизиран.
17. PDF multilingual rendering трябва да бъде надеждно.
18. Export metadata трябва да бъде правилно.
19. Canonical model трябва да може да представя повече от:
paragraphs + runs + simple tables.
20. Current tests могат да пропускат import-side data loss, ако сравняват само app model-а.

Това не са хипотези.
Те са findings от текущия audit.
НЕ ги игнорирай.
==================================================
4. FIRST ACTION — CREATE CONTROL CENTER
==================================================
Преди да променяш production code:
СЪЗДАЙ EXCEL TRACKER:
SmartDoc_Master_Implementation_Tracker.xlsx
Той е задължителен.
Използвай openpyxl или друг надежден XLSX library.
Ако openpyxl е наличен, предпочети него.
Не създавай CSV.
Не създавай markdown вместо Excel.
Искам реален:
.xlsx
==================================================
5. EXCEL STRUCTURE
==================================================
Workbook трябва да има поне следните sheets:

1. MASTER
2. CRITICAL_FIXES
3. DOCUMENT_FIDELITY
4. DOCX_OOXML
5. PDF
6. EDITOR
7. FORMATTING
8. AI
9. SECURITY
10. PERFORMANCE
11. TESTING
12. PRODUCT_FEATURES
13. TRANSLATION
14. PDF_TO_EDITABLE
15. BILLING_PLANS
16. INFRA
17. CHANGE_LOG
18. SESSION_STATE
19. RELEASE_GATES

==================================================
6. MASTER SHEET
==================================================
MASTER трябва да съдържа минимум:
| ID | Phase | Category | Feature/Task | Description | Priority | Status | Evidence | Tests | Owner/System | Dependencies | Risk | Started | Completed | Last Verified | Commit | Notes |
Status values:
NOT_STARTED
IN_PROGRESS
BLOCKED
IMPLEMENTED
TESTING
VERIFIED
DONE
FAILED
DEFERRED
UNKNOWN
Priority:
P0
P1
P2
P3
НЕ позволявай произволни status strings.
==================================================
7. PROGRESS TRACKING
==================================================
Excel трябва автоматично да може да показва:
Total tasks
Completed tasks
Verified tasks
In progress
Blocked
Failed
Remaining
Добави:

* completion %
* verified %
* phase %
* category %
* P0 remaining
* P1 remaining

Използвай Excel formulas.
Добави conditional formatting:
DONE → visually clear
IN_PROGRESS → visually clear
BLOCKED → visually clear
FAILED → visually clear
P0 → visually highlighted
НЕ разчитай само на цветове.
Status трябва да бъде текст.
==================================================
8. EVERY TASK MUST HAVE AN ID
==================================================
Използвай стабилни IDs.
Например:
CORE-001
CORE-002
DOCX-001
DOCX-002
PDF-001
AI-001
TRAN-001
SEC-001
PERF-001
TEST-001
PLAN-001
INFRA-001
Тези ID-та не трябва да се променят след създаване.
==================================================
9. EXCEL MUST BE UPDATED DURING WORK
==================================================
След всяка atomic implementation task:

1. update code
2. run relevant tests
3. record result
4. update Excel
5. update CHANGE_LOG
6. update SESSION_STATE

НЕ чакай края на phase.
Пример:
Task DOCX-021
Status:
IMPLEMENTED
Tests:
test_numbering_roundtrip.py
Evidence:
export/docx_numbering.py
Commit:
abc123
Last verified:
timestamp
Така Excel трябва винаги да показва истинското състояние.
==================================================
10. NEVER FAKE PROGRESS
==================================================
НЕ маркирай:
DONE
ако:

* tests fail
* build fail
* feature is only UI
* only happy path works
* real export is broken
* fidelity is unverified
* security is unverified

DONE означава:
implemented + tested + verified.
==================================================
11. SESSION CHECKPOINT SYSTEM
==================================================
СЪЗДАЙ:
docs/AI-CONTINUATION.md
и:
docs/session-state.json
SESSION_STATE трябва да пази:

* current phase
* current task ID
* last completed task
* current task details
* files changed
* tests run
* test results
* known blockers
* next exact task
* current commit
* current branch
* current Excel status
* unfinished work
* important discoveries
* migration state
* schema version
* whether database migrations were applied
* whether production code was changed
* last checkpoint timestamp

==================================================
12. CONTINUATION CONTRACT
==================================================
Когато session/context/tool limit започне да се доближава:
НЕ започвай нов голям task.
Първо:

1. finish current safe atomic step, if possible
2. run relevant verification
3. save Excel
4. save SESSION_STATE
5. save AI-CONTINUATION.md
6. record exact next task
7. record exact command/test to continue from
8. record current branch/commit

AI-CONTINUATION.md трябва да съдържа:
CURRENT STATE
LAST VERIFIED
WHAT WAS CHANGED
WHAT PASSED
WHAT FAILED
WHAT REMAINS
NEXT ACTION
IMPORTANT WARNINGS
==================================================
13. REMINDER / RESUME
==================================================
Не спирай доброволно.
Работи до hard environment/session limit.
Ако средата предоставя:

* reminder
* scheduler
* task scheduling
* session continuation

използвай го.
При наближаване на лимита създай reminder за възобновяване след следващия възможен session reset.
НЕ измисляй дата/час.
Използвай реално достъпното време/следващ reset, ако платформата го предоставя.
Ако платформата НЕ предлага reminder:
не твърди, че си поставил такъв.
Вместо това:

* update AI-CONTINUATION.md
* update SESSION_STATE
* update Excel
* output exact continuation instruction

Следващата сесия трябва да може да продължи само чрез:
"Прочети docs/AI-CONTINUATION.md и продължи от next task."
==================================================
14. GIT SAFETY
==================================================
Преди големи промени:
създай branch:
feature/smartdoc-production-hardening
или подходящо име.
Преди всяка голяма phase:
commit.
Пример:
phase-01-integrity
phase-02-security-performance
phase-03-document-fidelity
phase-04-pdf-editable
phase-05-translation
phase-06-product
НЕ прави giant uncommitted change set.
==================================================
15. PHASE 0 — BASELINE
==================================================
Първо:

* inspect full repository
* inspect current branch
* run tests
* run frontend tests
* run E2E
* run typecheck
* run lint
* run build
* inspect database
* inspect migrations
* inspect dependencies
* inspect Docker
* inspect worker
* inspect storage
* inspect current fixtures

Запиши baseline резултатите в:
Excel
+
docs/AI-CONTINUATION.md
+
docs/architecture/current-baseline.md
Не променяй production behavior в тази стъпка.
==================================================
16. PHASE 1 — DOCUMENT INTEGRITY
==================================================
Това е P0.
ОПРАВИ ПЪРВО:
16.1 Editor serialization loss
Поправи:
tiptapToDocument.ts
така че никакъв неподдържан block node да бъде silently discarded.
Подход:
A. fully map
или
B. preserve losslessly
или
C. block save with explicit error
Никога:
silent discard.
Добави regression tests за:

* list in cell
* code in cell
* image in cell
* quote with list
* list item with code
* nested structures
* pasted rich HTML

==================================================
17. IMPORT LOSS REPORT
==================================================
Създай:
Document Fidelity Report
след import/format/export.
Ако елемент е:

* changed
* unsupported
* preserved
* approximated

покажи:
element
feature
source state
new state
confidence
reason
Потребителят трябва да може да види:
"No content changes"
само ако системата реално го е доказала.
==================================================
18. AI FIDELITY
==================================================
Изцяло замени слабата fidelity check логика.
НЕ използвай:
substring containment
като единствена проверка.
Създай:
order-aware
count-aware
token-aware
numeric-aware
punctuation-aware
structure-aware
comparison.
Провери поне:

* sentence deletion
* word deletion
* "not" removal
* number change
* unit change
* percentage change
* date change
* added sentence
* reordered sentence
* duplicated content
* punctuation alteration
* heading changes

Числа трябва да бъдат особено защитени.
Пример:
5 mg
НЕ може да стане:
50 mg
без explicit user action.
==================================================
19. AI STRUCTURAL OPERATIONS
==================================================
AI operations:
insert
delete
move
replace
са HIGH RISK.
Всички destructive операции трябва да минат през:
PLAN
→ VALIDATE
→ PREVIEW
→ USER ACCEPT
→ APPLY
Не прилагай delete/replace silently.
Formatting-only operations могат да имат optional auto-apply.
Content-changing operations:
MUST REQUIRE USER REVIEW
==================================================
20. IMPORT/EXPORT PRESERVATION
==================================================
Пази:
ORIGINAL SOURCE
когато е необходимо.
При DOCX:
original package може да бъде запазен като immutable source artifact.
След това:
canonical model
+
preservation metadata
+
source package references
Използвай source package preservation, когато canonical model не може да представи дадена OOXML feature.
==================================================
21. DOCX FIDELITY ENGINE
==================================================
DOCX трябва да се разглежда като:
OOXML PACKAGE
а не като:
paragraph list.
Провери/имплементирай preservation на:

* document.xml
* styles.xml
* numbering.xml
* settings.xml
* relationships
* media
* headers
* footers
* footnotes
* endnotes
* comments
* commentsExtended при наличие
* custom properties
* core properties
* app properties
* theme
* webSettings
* fontTable
* glossary ако има
* embedded objects ако има
* custom XML ако има
* content controls
* fields

Не е задължително всичко да е editable.
Но трябва да е:
SUPPORTED
или
PRESERVED
или
EXPLICITLY UNSUPPORTED
Никога silent loss.
==================================================
22. WORD CHARACTER FORMATTING
==================================================
Поддържай или preservation strategy за:

* bold
* italic
* underline
* double underline
* strike
* double strike
* color
* highlight
* small caps
* all caps
* subscript
* superscript
* character spacing
* character scale
* character position
* language
* RTL
* theme font
* theme color
* hidden text
* proofing-related metadata

==================================================
23. WORD PARAGRAPH FORMATTING
==================================================
Поддържай:

* alignment
* left indent
* right indent
* first-line indent
* before spacing
* after spacing
* line spacing
* keep-with-next
* keep-lines-together
* page-break-before
* widow/orphan
* outline level
* tabs
* paragraph borders
* shading
* direction
* contextual spacing
* pagination controls

==================================================
24. SECTIONS
==================================================
Section трябва да стане real first-class concept.
Поддържай:

* section break
* next page
* continuous
* even page
* odd page
* portrait
* landscape
* page size
* margins
* columns
* header distance
* footer distance
* first-page header/footer
* even/odd headers
* linked-to-previous
* page number restart

НЕ допускай:
last section header
да се показва на целия document.
==================================================
25. NUMBERING
==================================================
Това е P0/P1.
Поддържай:

* decimal
* upper roman
* lower roman
* upper alpha
* lower alpha
* bullets
* custom prefixes/suffixes
* start values
* restart
* continuation
* multilevel
* numId
* abstractNum
* ilvl
* numbering indentation

Направи round-trip fixtures:
1 level
2 level
3 level
5 level
custom numbering
restart numbering
continuation across sections
==================================================
26. TABLE ENGINE
==================================================
Пълна table fidelity:

* row
* column
* header
* merge
* vertical merge
* colspan
* rowspan
* cell widths
* row heights
* cell margins
* borders
* shading
* alignment
* vertical alignment
* nested tables
* repeated header rows
* table styles
* captions
* wrapping

НЕ force-вай първия ред като header без доказателство.
НЕ force-вай Table Grid.
Не променяй geometry само защото exporter-ът така е написан.
==================================================
27. IMAGES
==================================================
Image трябва да има first-class asset representation.
Поддържай:

* asset_id
* mime
* width
* height
* alt text
* crop
* rotation
* anchor
* wrap
* position
* relationship
* original metadata

Премахни base64 като primary storage model.
==================================================
28. DRAWINGS / TEXT BOXES
==================================================
Разпознавай поне:

* inline drawings
* anchored drawings
* text boxes
* drawing positioning
* wrap settings
* shape relationship references

Ако не могат да бъдат редактирани:
PRESERVE.
==================================================
29. FIELDS
==================================================
Провери:
PAGE
NUMPAGES
SECTIONPAGES
DATE
TIME
AUTHOR
TITLE
FILENAME
REF
SEQ
STYLEREF
HYPERLINK
TOC
Разграничи:

* field code
* field result
* field relationship

Не изписвай:
"Invalid source specified."
без да има причина.
==================================================
30. COMMENTS / TRACK CHANGES
==================================================
Провери:

* comments
* replies
* authors
* ranges
* inserted text
* deleted text
* formatting changes
* move changes

В първи етап:
preserve if not editable.
След това:
editor support where practical.
Никога silent loss.
==================================================
31. CONTENT CONTROLS
==================================================
Разпознавай:
w:sdt
и типове:

* plain text
* rich text
* checkbox
* dropdown
* combo
* date
* picture
* repeating content

Пази ги ако editor не може да ги редактира.
==================================================
32. METADATA
==================================================
Пази:

* author
* title
* subject
* keywords
* created
* modified
* company
* manager
* custom properties
* sensitivity-related properties where technically possible

Не overwrite-вай metadata с:
python-docx
или internal service identity.
==================================================
33. SECURITY HARDENING
==================================================
ОПРАВИ:

* malformed DOCX → safe 4xx
* malformed PDF → safe 4xx
* image pixel bombs
* decompression limits
* PDF bombs
* huge XML
* parser abuse
* malicious SVG
* javascript href
* dangerous field instructions
* arbitrary external relationships
* unsafe external resources
* prompt injection
* AI output abuse

Никога не допускай document content да стане system instruction.
==================================================
34. HREF SECURITY
==================================================
Allowlist:
https
http
mailto
ако use-case го позволява.
Treat carefully:
file:
ftp:
javascript:
data:
vbscript:
Не export-вай:
javascript:
като active hyperlink.
Не allow arbitrary field instructions.
==================================================
35. IMAGE RESOURCE LIMITS
==================================================
Добави:

* compressed upload limit
* decompressed limit
* max pixel count
* max width
* max height
* max images/document
* max total image bytes
* format allowlist

Reject before expensive rasterization.
==================================================
36. PERFORMANCE
==================================================
ОПРАВИ:
500×8 table export bottleneck.
Използвай:

* O(n) / O(n log n) operations
* bulk operations
* avoid per-cell expensive scans
* cache repeated style resolution
* avoid repeated full document traversals

Постави safe limits.
==================================================
37. DOCUMENT MEMORY
==================================================
НЕ пази неограничен:
full document deep copy
за всяка операция.
Раздели:
EDITOR HISTORY
от:
PERSISTED VERSION HISTORY
Използвай:

* bounded history
* compressed representation
* delta where practical
* asset references instead of blobs

==================================================
38. AUTOSAVE
==================================================
Autosave трябва да бъде:

* debounced
* change aware
* conflict aware
* retry aware

Не изпращай целия document на всеки малък edit, ако delta/patch architecture е разумна.
Направи threshold strategy.
==================================================
39. API / ERROR MODEL
==================================================
Всеки error:
{
code,
message,
details,
request_id
}
Не показвай stack traces на user.
Всички parser failures трябва да имат безопасен user-facing response.
==================================================
40. PDF ENGINE — ВТОРИ ОСНОВЕН ПРОДУКТ
==================================================
PDF трябва да има:
TEXT PDF
SCANNED PDF
HYBRID PDF
classifier.
Провери:

* page dimensions
* text blocks
* coordinates
* fonts
* font sizes
* colors
* lines
* rectangles
* images
* vector graphics
* tables
* links
* annotations
* bookmarks
* forms
* AcroForm
* signatures
* attachments
* metadata
* rotation
* crop box
* media box
* bleed
* trim
* layers

==================================================
41. PDF → EDITABLE DOCUMENT
==================================================
Това е нова major feature.
Product flow:
UPLOAD PDF
↓
CLASSIFY
↓
TEXT / SCANNED / HYBRID
↓
LAYOUT EXTRACTION
↓
OCR IF NEEDED
↓
STRUCTURE RECONSTRUCTION
↓
DOCUMENT MODEL
↓
EDITOR
↓
EDIT
↓
EXPORT DOCX/PDF
Раздели на:
PHASE A:
PDF → editable text
PHASE B:
PDF → editable structured document
PHASE C:
PDF → high fidelity reconstruction
Не твърди 100% fidelity.
Системата трябва да знае:
confidence
за:

* text blocks
* headings
* tables
* columns
* images
* reading order

==================================================
42. PDF LAYOUT MODEL
==================================================
Ако е необходимо:
разшири Document Model с layout primitives.
Например концептуално:
Page
Block
TextRun
ImageBlock
TableBlock
Shape
TextBox
с координати:
x
y
width
height
rotation
Но НЕ въвеждай coordinate complexity навсякъде, ако semantic document model е достатъчен.
Използвай layout model само когато PDF import го изисква.
==================================================
43. OCR
==================================================
Добави OCR abstraction.
Поддържай:
OCR provider interface
така че implementation да може да се сменя.
OCR output трябва да включва:

* text
* confidence
* bounding boxes
* page
* language/script

OCR content е untrusted.
==================================================
44. PDF PAGE OPERATIONS
==================================================
Разгледай/имплементирай:

* reorder pages
* rotate
* delete
* duplicate
* extract
* split
* merge PDFs

Това трябва да бъде отделен PDF service, а не logic в editor.
==================================================
45. TRANSLATION — ТРЕТА ОСНОВНА PRODUCT FEATURE
==================================================
Добави translation architecture.
Supported modes:

1. selected text
2. selected run group
3. selected paragraph
4. selected block
5. selected page
6. whole document

Основното правило:
TRANSLATE WITHOUT DESTROYING FORMAT.
==================================================
46. TRANSLATION DATA MODEL
==================================================
НЕ превеждай:
whole document → giant string
Използвай semantic segments.
Пример:
Paragraph
→ Segment A
→ Segment B
→ Segment C
Всеки segment трябва да пази:

* source text
* source element id
* source run IDs
* marks
* style references
* source language
* target language
* translation status
* translation provider
* glossary terms

==================================================
47. TRANSLATION PIPELINE
==================================================
Selection translation:
SELECT
↓
SEGMENT
↓
TRANSLATE
↓
VALIDATE
↓
PREVIEW
↓
ACCEPT / REJECT
Whole document:
SOURCE VERSION
↓
TRANSLATED VERSION
Не унищожавай source version.
==================================================
48. TRANSLATION AI SAFETY
==================================================
Translation AI:
НЕ трябва да:

* променя numbers
* променя dates
* променя medical dosage
* променя units
* добавя missing facts
* измисля content

Създай validation за:

* numbers
* units
* dates
* percentages
* identifiers

Освен това:
medical/legal/official documents:
показват ясно:
"AI-assisted translation — review required."
НЕ:
"Certified translation."
==================================================
49. TERMINOLOGY / GLOSSARY
==================================================
Добави:
Glossary
с:
source term
target term
domain
locked
case_sensitive
Translation engine трябва да може да заключва терминология.
Особено за:

* medical
* legal
* business
* technical

==================================================
50. FONT RESOLVER
==================================================
Създай:
FontResolver
НЕ оставяй AI сам да избира.
Провери:

* Unicode coverage
* script support
* font availability
* language
* fallback chain
* embedding capability
* RTL compatibility

Scripts:

* Latin
* Cyrillic
* Greek
* Arabic
* Hebrew
* Devanagari
* CJK
* emoji

Първо:
deterministic coverage
след това:
AI recommendation
Но engine винаги валидира.
==================================================
51. TRANSLATION UX
==================================================
При selection:
Translate
→ target language
→ preview
→ original vs translated
→ Accept
→ Reject
Whole document:
"Create translated version"
Не презаписвай source.
==================================================
52. MULTILINGUAL DOCUMENTS
==================================================
Поддържай:
mixed language document.
Пример:
German
+
English
+
Bulgarian
+
Arabic
Не приемай един global font за целия документ, ако content изисква fallback.
==================================================
53. PDF MULTILINGUAL RENDERING
==================================================
PDF exporter трябва да използва:
real font registration / embedding
а не:
everything → Helvetica.
RTL shaping трябва да бъде правилно обработено.
CJK трябва да бъде реално readable.
Emoji трябва да бъде handled gracefully.
==================================================
54. DOCUMENT HEALTH 2.0
==================================================
Разшири Document Health.
Провери:

* inconsistent fonts
* spacing
* hierarchy
* headings
* numbering
* empty paragraphs
* broken links
* missing alt text
* captions
* tables
* page breaks
* unsupported features
* hidden text
* mixed language
* inconsistent style
* layout anomalies
* section inconsistency

Fixes трябва да са deterministic.
AI може само да обяснява.
==================================================
55. FORMAT BY EXAMPLE
==================================================
Това трябва да бъде core feature.
SOURCE DOCUMENT

* 

REFERENCE DOCUMENT
↓
STYLE EXTRACTION
↓
STYLE SYSTEM
↓
SEMANTIC MAPPING
↓
DETERMINISTIC FORMATTING
AI може:
classify
+
map
Engine:
apply
Показвай:
Before
vs
After
==================================================
56. STYLE EXTRACTION
==================================================
Reference document трябва да може да предоставя:

* page setup
* margins
* fonts
* heading styles
* paragraph styles
* lists
* tables
* captions
* headers
* footers
* images
* spacing
* numbering
* color system

Не copy-вай blind formatting.
Extract:
STYLE SYSTEM.
==================================================
57. USER TRUST
==================================================
В UI трябва да има:
"Content protection"
и:
"Changes detected"
Ако няма доказателство за zero content changes:
НЕ показвай:
"Content unchanged."
Покажи:
"Formatting applied. 3 items require review."
==================================================
58. REVIEW CHANGES
==================================================
Добави:
Review Changes
като общ layer.
Change categories:
FORMAT
STRUCTURE
CONTENT
METADATA
PRESERVATION
TRANSLATION
CONTENT changes изискват explicit user acceptance.
==================================================
59. CLEAN COPY
==================================================
Разгледай:
"Create clean copy"
който позволява:

* remove comments
* accept tracked changes
* remove hidden text
* remove metadata
* normalize formatting

Но всяко action трябва да бъде explicit.
==================================================
60. DOCUMENT REPAIR
==================================================
Добави architecture за:
Repair document
Откривай:

* broken numbering
* inconsistent styles
* broken tables
* broken links
* unsupported structures
* malformed input

Repair трябва да показва:
detected issue
proposed fix
preview
apply
==================================================
61. ADDITIONAL PRODUCT FEATURES
==================================================
Разгледай и приоритизирай:

* document compare
* version compare
* batch formatting
* batch export
* batch translation
* merge documents
* split documents
* page reorder
* page rotate
* page delete
* page extract
* accessibility checker
* heading hierarchy checker
* link checker
* alt-text checker
* metadata editor
* global style replacement
* find/replace with formatting
* table repair
* list repair
* OCR
* PDF merge/split
* clean copy
* tracked change cleanup
* template extraction
* document-to-template
* template matching
* multilingual support
* RTL
* CJK
* citation preservation
* bibliography preservation
* forms
* content controls
* custom fields
* watermark
* glossary
* terminology lock
* translation memory

НЕ имплементирай всичко едновременно.
Добави ги в Excel като:
NOW
NEXT
LATER
ARCHITECTURE_ONLY
==================================================
62. FEATURE PRIORITIZATION
==================================================
NOW:

1. Document integrity
2. Fidelity
3. Security
4. Performance
5. PDF → editable
6. Translation MVP
7. FontResolver
8. Review Changes
9. Document Health 2.0
10. Format by Example hardening

NEXT:

* batch processing
* document compare
* repair
* accessibility
* advanced template sharing
* teams
* translation memory

LATER:

* advanced forms
* SmartArt editing
* OLE
* full tracked-change editor
* advanced citation manager
* advanced drawing editor

Architecture must leave room for them.
==================================================
63. PLAN / BILLING MODEL
==================================================
Използвай usage units.
НЕ прави само:
feature = true/false
Primary usage units:

* documents
* exports
* PDF pages
* OCR pages
* translation characters
* AI operations
* storage
* batch jobs

Всички quotas са configurable.
==================================================
64. INITIAL PLAN HYPOTHESIS
==================================================
Използвай следните като INITIAL DEFAULTS.
Това са product hypotheses, не final prices.
FREE:

* 5 documents/month
* 20 PDF conversion pages/month
* 5 OCR pages/month
* 10,000 translation characters/month
* 10 AI operations/month
* 25 exports/month
* basic templates
* basic formatting
* no batch
* no team workspace

PRO:

* 100 documents/month
* 500 PDF conversion pages/month
* 100 OCR pages/month
* 500,000 translation characters/month
* 300 AI operations/month
* 500 exports/month
* Format by Example
* custom templates
* advanced Document Health
* version history
* batch operations with reasonable limits

BUSINESS:

* 1,000 documents/workspace/month
* 5,000 PDF conversion pages/month
* 1,000 OCR pages/month
* 5,000,000 translation characters/month
* 2,000 AI operations/month
* high export limits
* workspace/team features
* shared templates
* batch processing
* priority processing
* advanced controls

ВАЖНО:
Провери тези limits спрямо реалната инфраструктурна/AI cost след measurement.
Не ги hardcode-вай в business logic.
Трябва да са configurable.
==================================================
65. ENTITLEMENT ARCHITECTURE
==================================================
Използвай:
EntitlementService
Не:
if plan == "PRO"
навсякъде.
Примери:
can_translate
max_translation_chars
max_pdf_pages
max_ocr_pages
max_ai_operations
can_batch_process
can_format_by_example
max_storage
max_documents
Провери quotas server-side.
==================================================
66. PLAN LIMIT RACE
==================================================
Всички usage checks трябва да бъдат atomic.
Не:
CHECK
→ PROCESS
→ INCREMENT
ако това позволява race.
Използвай transaction/atomic update/reservation strategy.
Тествай concurrency.
==================================================
67. STRIPE
==================================================
Billing implementation трябва да бъде реално интегрируема.
Провери:

* checkout
* portal
* subscription
* upgrade
* downgrade
* cancel
* renewal
* failed payment
* webhook
* idempotency

Webhook е source of truth за subscription state.
==================================================
68. BACKGROUND JOBS
==================================================
Тежките операции:

* OCR
* large PDF conversion
* large DOCX export
* translation
* batch processing
* AI analysis

трябва да могат да се изпълняват като jobs.
Job:
id
type
status
progress
document_id
workspace_id
created_at
started_at
finished_at
error
retry_count
idempotency_key
==================================================
69. JOB SAFETY
==================================================
Jobs трябва да имат:

* retry limit
* timeout
* idempotency
* cancellation where safe
* stuck detection
* exponential backoff
* dead-letter strategy

Никога endless retry.
==================================================
70. STORAGE
==================================================
Използвай:
StorageProvider
Local
+
S3-compatible
Assets:
source files
images
generated exports
OCR artifacts
има:
retention
deletion
access control
content type
size limits
Не пази exports безкрайно.
==================================================
71. ACCOUNT SECURITY
==================================================
Добави/провери:

* password reset
* email verification
* password change
* account deletion
* session revocation
* secure cookies
* CSRF
* rate limiting
* suspicious login handling

==================================================
72. PRIVACY
==================================================
НЕ логвай:

* document content
* full prompts
* full translation text
* medical text
* legal text

ако не е абсолютно необходимо.
Използвай:

* redacted logs
* request IDs
* operation IDs

==================================================
73. DOCUMENT PRIVACY
==================================================
Потребителят трябва да може да:

* delete document
* delete asset
* delete exports
* delete account

Account deletion трябва да има cascading policy.
==================================================
74. TESTING — НЕ БРОЙ САМО ТЕСТОВЕ
==================================================
Искам:
unit
integration
E2E
security
performance
round-trip
golden-document
browser
AI validation
migration
==================================================
75. WORD-AUTHORED FIXTURES
==================================================
Създай realistic synthetic fixtures.
Поне:

1. university paper
2. CV
3. business report
4. contract
5. medical-looking synthetic report
6. invoice
7. legal-looking document
8. complex tables
9. multi-section document
10. header/footer document
11. footnote document
12. hyperlink document
13. image-heavy document
14. comments document
15. tracked changes
16. TOC
17. content controls
18. text boxes
19. mixed language
20. RTL

Където е възможно:
Word-authored.
НЕ използвай реални лични медицински данни.
==================================================
76. EXPECTED LOSS MANIFEST
==================================================
За всяка fixture:
очаквай:

* supported
* preserved
* editable
* intentionally unsupported

Направи:
expected-loss.json
или equivalent.
CI трябва да сравнява actual срещу expected.
==================================================
77. TRUE FIDELITY TEST
==================================================
Тест:
SOURCE FILE
→ IMPORT
→ MODEL
→ FORMAT
→ EDITOR SAVE
→ EXPORT
→ REIMPORT
→ COMPARE SOURCE VS RESULT
Сравнявай:
CONTENT
отделно от:
FORMATTING
отделно от:
METADATA
отделно от:
STRUCTURE
НЕ прави един global boolean:
equal = true/false
==================================================
78. INDEPENDENT VALIDATION
==================================================
Output трябва да бъде проверяван от независим tools.
DOCX:

* Word if available
* OOXML parser
* schema validation

PDF:

* pdftotext
* PyMuPDF
* independent parser

Целта е:
app не трябва сама да си казва:
"export successful"
и това да бъде единствената проверка.
==================================================
79. BROWSER TESTS
==================================================
Playwright workflows:

1. create
2. upload
3. paste
4. structure review
5. format
6. manual edit
7. autosave
8. reload
9. undo
10. redo
11. export DOCX
12. export PDF
13. hyperlink
14. image
15. tables
16. lists
17. caption
18. PDF import
19. translation selection
20. whole-document translation
21. Format by Example
22. Review Changes
23. delete
24. account flow

==================================================
80. PERFORMANCE GATES
==================================================
Benchmark:

* 1 page
* 10 pages
* 50 pages
* 100 pages
* 300 pages
* 1000 pages where feasible
* 5k elements
* 12k elements
* huge tables
* image-heavy docs
* large PDFs
* OCR
* translation

Record:

* memory
* CPU
* latency
* request size
* export duration
* browser typing latency

Excel sheet:
PERFORMANCE
must contain measured results.
==================================================
81. ACCEPTANCE THRESHOLDS
==================================================
Do NOT invent fake production SLOs.
Instead:

* measure current
* define regression threshold relative to baseline
* define safe resource ceilings
* define job timeout
* define user-facing maximum sizes

All thresholds must be recorded in Excel.
==================================================
82. FRONTEND
==================================================
Keep modular editor.
Do not create another giant DocumentEditor.
Separate:

* shell
* editor state
* selection
* formatting
* autosave
* translation
* review changes
* export
* document health
* template
* PDF tools

Server state separate from editor-local state.
==================================================
83. Tiptap MAPPING
==================================================
Audit every conversion:
Document
↔
Tiptap
for:

* nodes
* marks
* IDs
* selection
* lists
* tables
* images
* captions
* page breaks
* links
* unsupported preserved content

There must never be:
unknown node
→ silently ignored
==================================================
84. API CONTRACT
==================================================
API must remain versioned:
/api/v1/...
Use generated frontend client.
Standard error envelope.
OpenAPI is source of truth.
==================================================
85. DOCUMENT COMMAND MODEL
==================================================
Where possible, document changes should be expressed as commands:
FormatCommand
InsertCommand
DeleteCommand
MoveCommand
TranslateCommand
ConvertCommand
with:
validate
preview
apply
undo
This is especially important for:
AI
translation
repair
batch operations
==================================================
86. DOCUMENT VERSION MODEL
==================================================
Every major transformation:

* format
* translate
* repair
* convert

should be versionable.
User should be able to return to:
Original
Formatted
Translated
Repaired
Do not destroy original.
==================================================
87. TRANSLATION VERSION MODEL
==================================================
Whole document translation:
Original
→ Bulgarian v1
Selection translation:
creates revision/operation.
User can:
undo
reject
restore
==================================================
88. PDF CONVERSION VERSION MODEL
==================================================
PDF → Editable should produce:
Imported PDF version
not silently replace source.
The user should see:
"Imported from PDF"
and conversion confidence.
==================================================
89. REVIEW CHANGES AS CORE SYSTEM
==================================================
Build one review mechanism that can support:

* formatting changes
* structural changes
* AI changes
* translation
* repair

Change:
{
type,
elementId,
property,
before,
after,
reason,
source,
confidence
}
==================================================
90. UNSUPPORTED FEATURE POLICY
==================================================
Every unsupported feature must be classified:
NOT_DETECTED
DETECTED_PRESERVED
DETECTED_NOT_EDITABLE
LOSSY
UNSUPPORTED
BLOCKED
Before destructive operation:
show user.
==================================================
91. DOCUMENT CAPABILITY MATRIX
==================================================
Create machine-readable capability definitions.
Example:
DOCX:
hyperlinks:
import = yes
edit = yes
export = yes
round_trip = yes
comments:
import = yes
edit = no
export = preserved
round_trip = yes
This capability system should drive:

* UI badges
* warnings
* review
* tests
* export policy

==================================================
92. PRODUCT UX
==================================================
Main flows:
QUICK FORMAT
ADVANCED FORMAT
FORMAT BY EXAMPLE
PDF → EDITABLE
TRANSLATE
DOCUMENT HEALTH
Не карай потребителя да мисли за:
OOXML
Pydantic
workers
queues
font coverage
==================================================
93. PDF → EDITABLE UX
==================================================
After upload:
"How editable do you want the result?"
Option:
Editable Document
or:
Layout-focused reconstruction
Покажи:
confidence
и проблеми.
==================================================
94. TRANSLATION UX
==================================================
Selected text:
right-click / toolbar:
Translate
Target language
Preview
Accept
Reject
Whole document:
Translate Document
→ Create translated version
==================================================
95. TRANSLATION LANGUAGE SELECTION
==================================================
Поддържай language metadata.
Не приемай:
English → Bulgarian
само на база user selection.
Source language:
auto-detect + manual override
Target:
explicit.
==================================================
96. DOCUMENT LANGUAGE / SCRIPT
==================================================
За document segments пази:
language
script
direction
Това помага за:
font resolver
translation
PDF render
spell/proofing future support
==================================================
97. ACCESSIBILITY
==================================================
Добави checks:

* heading hierarchy
* alt text
* link labels
* table headers
* reading order
* language metadata
* contrast where relevant

==================================================
98. ADMIN / OPERATIONS
==================================================
Добави operations capabilities:

* failed jobs
* document processing failures
* usage spikes
* AI failures
* export failures
* storage usage
* account abuse

Admin UI може да бъде минимален, но operational data трябва да е достъпна.
==================================================
99. OBSERVABILITY
==================================================
Implement:

* structured logs
* request IDs
* operation IDs
* job IDs
* metrics
* latency
* failure rate

Не логвай document content.
==================================================
100. DEPLOYMENT
==================================================
Потвърди:
Docker
Postgres
Redis
Object storage
Workers
Frontend
Backend
И production startup.
==================================================
101. CI/CD
==================================================
CI трябва да изпълнява:

* backend tests
* frontend tests
* E2E
* lint
* typecheck
* build
* migrations
* security audit
* document fidelity tests

Особено:
golden document tests
трябва да са CI gate.
==================================================
102. RELEASE GATES
==================================================
Създай в Excel:
RELEASE_GATES
Минимум:
GATE-001
No silent content loss
GATE-002
No unauthorized document access
GATE-003
AI cannot silently change content
GATE-004
Plan limits atomic
GATE-005
Safe file uploads
GATE-006
DOCX valid
GATE-007
PDF valid
GATE-008
Multilingual PDF readable
GATE-009
PDF conversion has confidence/reporting
GATE-010
Translation preserves formatting
GATE-011
No destructive translation overwrite
GATE-012
Critical E2E passes
GATE-013
Migrations clean
GATE-014
No high-severity security findings
GATE-015
Monitoring exists
==================================================
103. DEFINITION OF DONE
==================================================
Не приемай проекта за DONE, докато:

1. P0 document integrity issues fixed
2. content preservation proven
3. AI fidelity proven
4. dangerous AI operations require review
5. numbering stable
6. sections preserved
7. tables stable
8. images preserved
9. hyperlinks safe
10. metadata handled
11. upload safe
12. resource limits safe
13. account basics complete
14. entitlement races fixed
15. PDF import reliable
16. PDF→editable MVP reliable
17. translation MVP reliable
18. font fallback reliable
19. multilingual PDF works
20. Format-by-Example works
21. Document Health works
22. review changes works
23. E2E passes
24. golden fixtures pass
25. CI passes
26. release gates pass

==================================================
104. IMPLEMENTATION ORDER
==================================================
PHASE 0
Baseline + Excel tracker + checkpoint system
PHASE 1
Editor integrity + content preservation
PHASE 2
AI fidelity + destructive operation review
PHASE 3
DOCX/OOXML preservation
PHASE 4
Security + resource limits
PHASE 5
Performance + autosave + history
PHASE 6
Account + billing + entitlement correctness
PHASE 7
PDF fidelity foundation
PHASE 8
PDF → Editable MVP
PHASE 9
PDF → Layout-preserving architecture
PHASE 10
Translation MVP
PHASE 11
FontResolver + multilingual rendering
PHASE 12
Format by Example hardening
PHASE 13
Document Health 2.0
PHASE 14
Review Changes / Repair
PHASE 15
Batch operations
PHASE 16
Accessibility + advanced document features
PHASE 17
Final testing
PHASE 18
Production release audit
==================================================
105. PHASE EXECUTION CONTRACT
==================================================
За всяка phase:
BEFORE:

* read tracker
* inspect current state
* inspect dependencies
* identify risks

DURING:

* implement atomic tasks
* update tracker
* update checkpoint

AFTER:

* run tests
* fix failures
* run regression
* update docs
* update Excel
* commit

След phase status:
VERIFIED
само ако tests + evidence са готови.
==================================================
106. FAILURE POLICY
==================================================
Ако тест fail:
НЕ маркирай task като done.
Ако има regression:
rollback или поправи.
Ако архитектурно решение се окаже грешно:
запиши в CHANGE_LOG.
НЕ крий failure, за да движиш progress.
==================================================
107. LARGE TASK POLICY
==================================================
Разделяй task на atomic subtasks.
Например:
DOCX-101
Preserve hyperlinks
↓
DOCX-101A
parser
DOCX-101B
model
DOCX-101C
editor
DOCX-101D
export
DOCX-101E
round-trip
Но Excel трябва да запази hierarchy чрез Parent ID.
==================================================
108. DOCUMENTATION
==================================================
Поддържай:
docs/
├── architecture/
├── document-model/
├── docx/
├── pdf/
├── translation/
├── ai/
├── formatting/
├── security/
├── testing/
├── deployment/
├── billing/
└── operations/
Documentation трябва да бъде синхронизирана с implementation.
==================================================
109. EXCEL CHANGE LOG
==================================================
CHANGE_LOG columns:
Timestamp
Task ID
Phase
Change
Files
Tests
Result
Commit
Notes
Не записвай само:
"fixed bug".
Пиши:
"Fixed editor serialization for list nodes inside table cells. Added regression test X. E2E passed."
==================================================
110. SESSION_STATE SHEET
==================================================
SESSION_STATE трябва да има:
Current Phase
Current Task
Last Completed
Last Verified
Current Branch
Current Commit
Tests Passed
Tests Failed
Open Blockers
Next Task
Next Command
Next Test
Checkpoint Time
Resume Instructions
==================================================
111. FINAL EXCEL REQUIREMENT
==================================================
В края Excel трябва да позволява на човек да отвори:
SmartDoc_Master_Implementation_Tracker.xlsx
и за под 2 минути да разбере:

* какво е направено
* какво остава
* кое е blocked
* кое е failed
* кое е verified
* кои са P0 проблемите
* докъде е всеки phase
* какви tests са минали
* какво е следващото действие

==================================================
112. FINAL REPORT
==================================================
Накрая създай:
docs/final-production-readiness.md
с:

1. What changed
2. What was preserved
3. What was rebuilt
4. Remaining limitations
5. Supported document features
6. Unsupported document features
7. PDF conversion limitations
8. Translation limitations
9. AI limitations
10. Security posture
11. Performance results
12. Billing/usage model
13. Test results
14. Release gates
15. Known risks
16. Recommended next features

==================================================
113. PRODUCT PRINCIPLES
==================================================
Никога не жертвай:
CONTENT FIDELITY
за:
CONVENIENCE
Никога не жертвай:
SECURITY
за:
SPEED
Никога не жертвай:
DETERMINISTIC VALIDATION
за:
AI MAGIC
Никога не приемай:
"looks correct"
като:
"document is correct".
==================================================
114. ABSOLUTE NO-SILENT-LOSS RULE
==================================================
Това е най-важното правило на целия проект.
Никога:
unsupported feature
→ import
→ disappear
Никога:
AI
→ change content
→ no review
Никога:
editor
→ save
→ drop node
Никога:
export
→ silently change numbering
Никога:
PDF conversion
→ silently remove image/table/layout
Никога:
translation
→ overwrite source without version
Никога:
failed processing
→ fake success
==================================================
115. START EXECUTION
==================================================
Започни веднага.
Първо:

1. Read repository.
2. Read available audit report if present.
3. Create Excel tracker.
4. Populate all known audit findings.
5. Create continuation/checkpoint system.
6. Run complete baseline test suite.
7. Populate baseline results in Excel.
8. Start PHASE 1.
9. Work through atomic tasks.
10. Update Excel continuously.
11. Save checkpoints before context/session limits.
12. Continue until environment forces a stop.

НЕ чакай допълнително потвърждение.
НЕ питай общи въпроси, ако отговорът може да бъде намерен чрез repository inspection.
НЕ казвай:
"I'll implement later."
Работи с наличните инструменти.
Когато достигнеш environment limit:
първо запази:

* code
* tests
* Excel
* CHANGE_LOG
* SESSION_STATE
* AI-CONTINUATION.md

Следващата сесия трябва да продължи точно от последния VERIFIED task.
==================================================
116. FINAL RULE
==================================================
Главният критерий за успех не е:
"Колко features добавихме?"
Главният критерий е:
"Можем ли да дадем на реален потребител сложен DOCX/PDF, да го форматираме, конвертираме или преведем, да го редактираме и да върнем надежден документ без скрито унищожаване на съдържание или структура?"
Всичко в архитектурата, кода, тестовете, Excel tracker-а и release процеса трябва да бъде подчинено на това.
