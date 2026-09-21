# SmartDoc Formatter — Software Requirements & Technical Specification

Версия: 1.0
Статус: Предварителна техническа спецификация за разработка на MVP

Цел на документа: Да служи като единен blueprint за проектиране, разработване, тестване и последващо разширяване на приложението.

> Клеширано в репото от `SmartDoc_Formatter_Technical_Documentation.docx`, за да не зависи бъдещата работа от файл извън проекта. Виж [README.md](../README.md) за статус по фази спрямо тази спецификация.

## 1. Обща информация

SmartDoc Formatter е уеб приложение за автоматизирано структуриране и форматиране на документи. Потребителят предоставя суров текст, съществуващ файл и/или правила за форматиране. AI модулът анализира съдържанието и определя логическата му структура, след което отделен formatting engine прилага избраните правила. Резултатът се визуализира в интерактивен редактор със страници, подобен като концепция на Canva, където потребителят може да редактира документа преди експортиране.

Първоначалната версия е Formatter, а не пълноправен AI Writer. Тя не трябва да променя смисъла или текста автоматично. AI Writer и AI-базираното подобряване на текста са предвидени за следващи версии.

## 2. Проблем, който системата решава

При курсови работи, реферати, заявления, CV и други документи потребителят често разполага със съдържанието, но трябва ръчно да настройва шрифтове, размери, отстъпи, междуредия, заглавия, страници и други правила. Допълнителен проблем възниква при копиране на съдържание от AI чатове или други източници, когато първоначалното форматиране се разпада.

Целта на системата е да отдели съдържанието от неговото визуално оформление и да автоматизира повтарящата се работа, като остави окончателния контрол в ръцете на потребителя.

## 3. Цели на проекта

- Автоматично разпознаване на логическата структура на суров текст.
- Прилагане на ясни и повторяеми правила за форматиране.
- Поддръжка на готови и персонализирани шаблони.
- Възможност за качване и анализиране на официални указания.
- Визуализация като реални страници преди експортиране.
- Директна WYSIWYG редакция на съдържанието и стила.
- Контролирано прилагане на промени с възможност за Undo/Redo.
- Експорт към DOCX и PDF в MVP.
- Архитектура, позволяваща по-късно AI Writer, акаунти и други услуги.

## 4. Обхват на MVP

| Включено в MVP | Не е задължително за MVP |
|---|---|
| Paste/въвеждане на текст | Потребителски акаунти |
| TXT, DOCX и PDF вход | Cloud document history |
| Ръчно въвеждане на правила | AI Writer |
| Качване на файл с указания | Онлайн споделяне |
| Готови шаблони | Съвместно редактиране |
| AI структурен анализ | Разширена библиотека от шаблони |
| Formatting engine | Допълнителни export формати |
| Страничен WYSIWYG preview/editor | |
| Style analysis като отделна функция | |
| DOCX/PDF export | |

## 5. Целеви потребители

- Студенти и ученици — курсови работи, реферати и есета.
- Офис служители — писма, отчети, молби и други официални документи.
- Търсещи работа — структурирани CV и мотивационни писма.
- Всеки потребител, който разполага с текст, но не иска да извършва ръчното форматиране.

## 6. Основен потребителски сценарий

1. Потребителят отваря приложението.
2. Създава нов документ.
3. Поставя суров текст или качва файл.
4. Избира тип документ или Auto Detect.
5. Избира готов шаблон или качва указания.
6. Добавя допълнителни инструкции, ако е необходимо.
7. Натиска Analyze / Generate.
8. Системата извлича съдържанието.
9. AI анализира структурата и правилата.
10. Formatting engine прилага правилата.
11. Preview показва документа като отделни страници.
12. Потребителят редактира съдържание и оформление.
13. При конфликт системата показва предложение за промяна.
14. Потребителят приема или отказва предложението.
15. Всички промени могат да бъдат върнати чрез Undo.
16. Потребителят експортира DOCX или PDF.

Този процес развива първоначалния workflow: входни данни → AI обработка → интерактивна редакция → финализиране и изход.

## 7. Функционални изисквания

### 7.1 Input

- FR-IN-001: Системата трябва да позволява директно поставяне на текст.
- FR-IN-002: Системата трябва да позволява директно въвеждане на текст.
- FR-IN-003: Системата трябва да приема TXT, DOCX и PDF входни файлове.
- FR-IN-004: Системата трябва да приема файл с инструкции.
- FR-IN-005: Системата трябва да позволява ръчно въвеждане на инструкции.
- FR-IN-006: Системата трябва да позволява избор на тип документ.
- FR-IN-007: Системата трябва да поддържа Auto Detect.

### 7.2 Типове документи

Първоначално трябва да бъдат предвидени поне:

- Курсова работа
- Реферат
- CV
- Молба / заявление
- Мотивационно писмо
- Жалба

Архитектурата не трябва да ограничава списъка до тези типове. Нов тип трябва да може да се добавя чрез шаблон и правила, без пренаписване на core engine.

### 7.3 AI структурен анализ

AI трябва да анализира текста и да създава структурно представяне, без да променя оригиналното съдържание в MVP.

- Разпознаване на заглавие и нива на заглавия.
- Разпознаване на параграфи.
- Разпознаване на номерирани и неномерирани списъци.
- Разпознаване на таблици.
- Разпознаване на цитати.
- Разпознаване на изображения и captions, когато са налични.
- Разпознаване на дати, подписи, контактни данни и други metadata.
- Разпознаване на header/footer съдържание, когато е налично.
- Разпознаване на библиография и референции.
- Определяне на йерархичните отношения между елементите.
- Определяне на confidence score за всяко AI решение.

### 7.4 Правила за разпознаване на структура

AI не трябва да определя елемент само по един признак. Например кратък ред преди дълъг параграф може да бъде заглавие, но това трябва да се преценява в контекст.

Анализът трябва да взема предвид комбинация от позиция, нов ред, дължина, пунктуация, номерация, семантика, повторяемост, отношенията с последващото съдържание и структурата на целия документ.

Пример: „1. Въведение" следва да бъде разпознато като Heading 1, докато последващият по-дълъг текст се разпознава като Paragraph.

При ниска увереност системата трябва да маркира решението като несигурно и, когато е уместно, да поиска потвърждение от потребителя.

### 7.5 Document Model

AI не трябва да генерира директно визуален DOCX. То трябва да връща структурирана абстракция на документа.

```
Document
├── Metadata
├── Sections
│   ├── Heading
│   ├── Paragraph
│   ├── List
│   ├── Table
│   ├── Image
│   ├── Quote
│   ├── Caption
│   ├── Footnote
│   └── Other elements
└── Formatting references
```

Всеки елемент трябва да има стабилен идентификатор, тип, съдържание, позиция/ред и, когато е приложимо, hierarchy level и confidence.

### 7.6 Примерна AI структура

```json
{
  "type": "heading",
  "id": "el-001",
  "level": 1,
  "text": "1. Въведение",
  "confidence": 0.96
}
```

Това е концептуален формат. Реалната JSON schema трябва да бъде формализирана преди имплементацията и да се валидира автоматично.

### 7.7 Formatting Rules Engine

Formatting engine е отделен от AI слоя. Той получава структурирания документ и набор от правила и прилага тези правила детерминистично.

Възможните настройки включват: Font family, Font size, Bold / Italic / Underline, Text color, Alignment, Line spacing, Paragraph spacing, First-line indent, Margins, Page size, Page breaks, Numbering, Bullets, Header, Footer, Page numbers, Table formatting, Image sizing and alignment.

### 7.8 Правила от инструкции

Инструкциите могат да бъдат зададени ръчно или извлечени от качен документ. AI трябва да превръща естествения език в структурирани технически правила, например font, font-size, margins и line-height.

```
Rule
├── target: Heading 1
├── property: fontSize
├── value: 14
└── unit: pt
```

### 7.9 Приоритет на правилата

За да се избегнат двусмислици, при конфликт се използва следната логика:

1. Изрична текуща промяна на потребителя.
2. Изрична инструкция, зададена от потребителя.
3. Официално качено правило/указание.
4. Избран custom template.
5. Готов template.
6. AI inference.
7. Default настройки.

### 7.10 Conflict Resolution

Когато две правила си противоречат, системата не трябва тихо да избира едното, ако промяната има видим ефект върху документа. Тя трябва да създаде change proposal.

```
Formatting conflict

Required: Times New Roman, 12 pt
Current:  Arial, 14 pt

[Apply recommended] [Keep current]
```

Потребителят трябва да може да приеме или откаже промяната. Приетите промени влизат в history и могат да бъдат отменени.

### 7.11 Templates

Системата трябва да има готови шаблони и custom templates.

- Academic — Курсова работа, Реферат, Дипломна работа.
- Professional — CV, Мотивационно писмо, Доклад.
- Official — Молба, Заявление, Жалба.

Потребителят трябва да може да създаде собствен шаблон, например с конкретните изисквания на университет.

### 7.12 WYSIWYG Preview / Editor

Preview трябва да показва документа като реални отделни страници. Потребителят трябва да може да избира елемент и да го редактира директно.

- Редактиране на текст.
- Добавяне и изтриване на текст.
- Избор на шрифт.
- Промяна на размер.
- Bold, Italic, Underline.
- Промяна на цвят.
- Подравняване.
- Междуредие и paragraph spacing.
- Добавяне/премахване на page break.
- Добавяне на секция.
- Работа с таблици и изображения.
- Undo / Redo.

### 7.13 Document Outline

Редакторът трябва да има панел с outline на документа. Той трябва да показва Heading 1/2/3 и да позволява бързо преминаване към съответната секция.

При промяна на йерархията outline-ът и автоматичното съдържание трябва да се актуализират.

### 7.14 Автоматично съдържание

За типове документи, при които съдържанието е приложимо, системата трябва да може да генерира Table of Contents от heading структурата. За CV, молби и други неподходящи типове функцията трябва да бъде изключена или да не се предлага.

### 7.15 Style Analysis

Style Analysis е отделна AI функция и не трябва да променя текста автоматично. Тя анализира консистентността на тона и стила и показва потенциални отклонения.

```
STYLE ANALYSIS
Consistency: 87%
Detected tone: Formal / Academic

Issues:
- Paragraph 4 appears informal.
- Paragraph 8 switches to first person.
- Paragraph 11 differs stylistically.

Actions:
[Improve with AI]
[Ignore]
```

Функцията „Improve with AI" е бъдещо контролирано действие и трябва да се активира само след изрично желание на потребителя.

### 7.16 AI Writer — Phase 2

AI Writer не е част от MVP. Той ще бъде добавен след стабилизиране на Formatter-а.

Очакваният бъдещ workflow е: тема/идея → AI генерира съдържание → структурен анализ → formatting engine → preview → редакция → export.

### 7.17 Export

MVP трябва да поддържа поне DOCX и PDF. Потребителят избира желания формат след финализиране.

DOCX трябва да остане редактируем документ, а PDF — готов визуален документ за споделяне или подаване.

## 8. Архитектура

```
                    ┌──────────────────────┐
                    │      Next.js UI      │
                    │  Editor / Preview    │
                    └──────────┬───────────┘
                               │
                         REST / API
                               │
                    ┌──────────▼───────────┐
                    │      FastAPI         │
                    │     Backend          │
                    └──────────┬───────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼────────┐    ┌────────▼────────┐    ┌────────▼────────┐
│ Parser Service │    │   AI Service     │    │ Formatting      │
│ TXT/DOCX/PDF   │    │ Structure/Style │    │ Engine           │
└───────┬────────┘    └────────┬────────┘    └────────┬────────┘
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                       ┌───────▼────────┐
                       │ Export Service │
                       │ DOCX / PDF     │
                       └────────────────┘
```

Препоръчителният технологичен стек е Next.js + React + TypeScript за frontend и Python + FastAPI за backend. AI provider трябва да бъде зад abstraction layer, така че системата да не зависи архитектурно от един доставчик.

## 9. Frontend архитектура

- Landing / New Document screen.
- Input workspace.
- Template selector.
- Instructions panel.
- Document editor.
- Page renderer.
- Toolbar.
- Properties sidebar.
- Document outline.
- Conflict modal.
- History/Undo manager.
- Export dialog.

Интерфейсът трябва да бъде разделен на функционални области, а не да се изгражда като един монолитен компонент.

## 10. Backend архитектура

Backend трябва да бъде организиран като услуги с ясно разделени отговорности.

| Service | Отговорност |
|---|---|
| Parser Service | Извличане на съдържание от TXT/DOCX/PDF |
| Document Service | Управление на структурирания Document Model |
| AI Service | Структурен анализ, document type detection и Style Analysis |
| Rules Service | Нормализиране и валидиране на formatting rules |
| Formatting Service | Прилагане на правилата |
| Preview/Render Service | Подготовка на визуално представяне |
| Export Service | DOCX/PDF генерация |
| Template Service | Готови и custom шаблони |

## 11. API концепция

Конкретните endpoint-и трябва да бъдат финализирани преди имплементация. Препоръчителната концепция е:

```
POST /api/documents/parse
POST /api/documents/analyze
POST /api/documents/format
POST /api/documents/render
POST /api/documents/export
POST /api/style/analyze
GET  /api/templates
POST /api/templates
POST /api/templates/validate
```

API договорът трябва да използва валидирани JSON schemas. Frontend не трябва да зависи от вътрешната имплементация на AI provider-а.

## 12. AI архитектура

AI Service трябва да бъде разделен на отделни задачи:

- Document type classification.
- Structure detection.
- Instruction extraction.
- Ambiguity/confidence detection.
- Style analysis.
- Future text improvement.
- Future content generation.

AI output трябва да бъде структурирано и валидируемо, а не свободен текст. При невалиден AI output backend трябва да откаже резултата и да изпълни retry/repair стратегия.

## 13. AI ограничения

- AI няма право да променя оригиналния текст в основния Formatter workflow.
- AI не трябва да прилага директно визуални стилове.
- AI трябва да връща структурни решения и confidence.
- AI не трябва да презаписва ръчни промени без изрично действие.
- Ниската увереност трябва да бъде видима или да доведе до потвърждение, когато решението е съществено.
- AI Writer и text improvement трябва да бъдат отделни режими.

## 14. Document Model — концептуална спецификация

```
Document
{
  id,
  metadata,
  documentType,
  templateId,
  settings,
  sections[],
  elements[],
  formattingRules[],
  revisions[]
}

Element
{
  id,
  type,
  content,
  parentId,
  order,
  level,
  confidence,
  styleRef
}

FormattingRule
{
  id,
  target,
  property,
  value,
  unit,
  priority,
  source
}
```

Тази структура е базова архитектурна спецификация. Преди coding тя трябва да бъде превърната в конкретна TypeScript type система и backend Pydantic schemas.

> **Реализирано в Phase 1** — виж [`backend/app/models/document.py`](../backend/app/models/document.py) и [`frontend/types/document.ts`](../frontend/types/document.ts).

## 15. State и Undo/Redo

Редакторът трябва да пази immutable или versioned document states. Всяка значима операция трябва да може да бъде записана като промяна.

- Text edit
- Style change
- Element move
- Element insertion/deletion
- Page break change
- Formatting rule override

Undo/Redo не трябва да зависи от повторно извикване на AI.

## 16. Конфиденциалност и файлове

Документите могат да съдържат академична, лична или професионална информация. MVP трябва да обработва файловете временно и да не предполага постоянно съхранение, тъй като акаунти и cloud history не са част от първата версия.

Файловете трябва да бъдат валидирани по тип и размер. Временните файлове трябва да се изтриват след приключване на workflow-а, освен ако са необходими за текущата сесия.

## 17. Error Handling

| Случай | Поведение |
|---|---|
| Невалиден файл | Ясно съобщение и възможност за нов upload |
| Неподдържан формат | Отказ с обяснение |
| AI timeout | Retry и съобщение към потребителя |
| Невалиден AI JSON | Validation + repair/retry |
| Неясна структура | Confidence warning / потребителско потвърждение |
| Конфликт на правила | Conflict modal |
| Export failure | Запазване на текущия редакторски state и повторен export |
| Прекалено голям документ | Контролирано ограничение и съобщение |

## 18. Non-Functional Requirements

- NFR-001: Интерфейсът трябва да бъде responsive за desktop и подходящ за tablet.
- NFR-002: Приложението трябва да запазва редакциите на текущата сесия при нормална работа.
- NFR-003: AI резултатите трябва да бъдат валидирани преди прилагане.
- NFR-004: Export процесът не трябва да унищожава редакторския state при грешка.
- NFR-005: Компонентите трябва да бъдат модулни и тестируеми.
- NFR-006: AI provider трябва да може да бъде заменен без промяна на editor core.
- NFR-007: Formatting rules трябва да бъдат детерминистични.
- NFR-008: Ръчните промени трябва да имат предимство пред автоматичните предложения.

## 19. Сигурност

- Валидиране на всички качени файлове.
- Ограничаване на размера на upload.
- Sanitization на HTML/rich-text съдържание.
- Защита на API endpoints.
- Секретите за AI provider да не присъстват във frontend.
- Временните файлове да не се оставят безконтролно на сървъра.
- Да не се записва чувствително съдържание в application logs.

## 20. Потребителски интерфейс

Препоръчителният основен layout е трикомпонентен:

```
┌─────────────────────────────────────────────────────────────┐
│ Toolbar                                                     │
├───────────────┬───────────────────────────┬─────────────────┤
│               │                           │                 │
│ Document      │       Page Preview        │ Properties      │
│ Outline       │       / Editor            │ / Formatting    │
│               │                           │                 │
│               │                           │                 │
├───────────────┴───────────────────────────┴─────────────────┤
│ Status / Validation / Export                                │
└─────────────────────────────────────────────────────────────┘
```

На малък екран панелите могат да се превръщат в collapsible drawers.

## 21. Първоначални екрани

- Home / New Document.
- Document Setup — type, template, instructions.
- Processing / Analysis state.
- Editor / Preview.
- Style Analysis panel.
- Conflict modal.
- Export dialog.

## 22. Project folder structure

```
smartdoc/
├── frontend/
│   ├── app/
│   ├── components/
│   ├── editor/
│   ├── pages/
│   ├── services/
│   ├── types/
│   └── utils/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── ai/
│   │   ├── parsers/
│   │   ├── formatting/
│   │   ├── export/
│   │   └── templates/
│   └── tests/
│
├── docs/
├── tests/
└── README.md
```

> Реализирано директно под repo root-а (без вложена `smartdoc/` папка) и без `frontend/pages/` (App Router се ползва вместо Pages Router — двете са взаимно изключващи се в Next.js). Папки без съдържание все още (`formatting/`, `export/`, `templates/`) се добавят във фазата, в която реално получат файлове.

## 23. Development roadmap

### Phase 0 — Specification
- Финализиране на Document Model.
- Финализиране на JSON schemas.
- Избор на конкретна editor библиотека.
- Избор на AI provider.
- Определяне на MVP acceptance criteria.

### Phase 1 — Core
- Next.js project.
- FastAPI project.
- Basic API communication.
- Paste/input screen.
- Document Model.
- Basic editor.

### Phase 2 — Parsing
- TXT parser.
- DOCX parser.
- PDF parser.
- Plain-text normalization.

### Phase 3 — AI
- Document type detection.
- Structure analysis.
- Confidence scoring.
- Instruction extraction.
- Structured AI output validation.

### Phase 4 — Formatting
- Formatting rules engine.
- Template system.
- Heading styles.
- Paragraph styles.
- Lists.
- Page settings.
- Headers/footers.
- Page numbers.
- Table/image rules.

### Phase 5 — Editor
- Real page preview.
- Toolbar.
- Properties panel.
- Outline.
- Undo/Redo.
- Conflict system.

### Phase 6 — Export
- DOCX export.
- PDF export.
- Export validation.

### Phase 7 — Testing
- Unit tests.
- Integration tests.
- AI schema tests.
- Export tests.
- Manual UI tests.
- Real academic document test cases.

> **Статус: Phase 0-1-2-3-4-5-6 завършени изцяло** (foundation + реален TXT/DOCX/PDF/Markdown parsing + реален AI structure analysis + детерминистичен formatting rules engine с templates + пълен editor: визуална пагинация/toolbar/outline/Properties panel/formatting undo-redo/Conflict Resolution modal по §7.10 + реален DOCX/PDF export; виж [README.md](../README.md) за подробности и направените допускания). Phase 7 (Testing) и нататък не е започнат.

## 24. Acceptance Criteria за MVP

- Потребителят може да постави суров текст.
- Потребителят може да качи TXT/DOCX/PDF.
- Потребителят може да избере тип документ.
- Потребителят може да използва Auto Detect.
- Потребителят може да избере template.
- Потребителят може да качи инструкции.
- AI може да върне структурирана структура.
- AI не променя текста във Formatter mode.
- Formatting engine прилага избраните правила.
- Документът се визуализира като отделни страници.
- Потребителят може да редактира текста и форматирането.
- Има Undo/Redo.
- Конфликтите се показват като предложения.
- Има DOCX export.
- Има PDF export.
- Не е необходим акаунт.

## 25. Тестови сценарии

| ID | Сценарий | Очакван резултат |
|---|---|---|
| TC-001 | Paste на курсова работа | Heading/paragraph структура |
| TC-002 | Качване на DOCX | Извлечено съдържание без зависимост от стария style |
| TC-003 | Качване на PDF | Извлечен текст при текстов PDF |
| TC-004 | Auto Detect | Предложен тип документ |
| TC-005 | Указания PDF | Извлечени formatting rules |
| TC-006 | Неясно заглавие | Confidence warning |
| TC-007 | Formatting conflict | Conflict modal |
| TC-008 | Ръчна промяна | User override |
| TC-009 | Undo | Последната промяна е отменена |
| TC-010 | TOC | Съдържанието следва heading структурата |
| TC-011 | CV | TOC не се предлага |
| TC-012 | DOCX export | Отварящ се редактируем DOCX |
| TC-013 | PDF export | Визуално съответствие с preview |

## 26. Phase 2 и бъдещи разширения

- AI Writer.
- AI text improvement.
- Advanced Style Analysis.
- User accounts.
- Saved documents.
- Cloud storage.
- Custom template marketplace/library.
- Version history.
- Document sharing.
- Collaborative editing.
- Additional export formats.
- Advanced academic citation tools.

## 27. Основни принципи за AI developer

- Не реализирай функционалност, която не е описана или необходима за конкретния етап.
- Не смесвай AI analysis с deterministic formatting.
- Не променяй оригиналния текст в Formatter mode.
- Не презаписвай ръчните действия на потребителя.
- Всички AI резултати трябва да бъдат структурирани и валидирани.
- Всички промени трябва да могат да бъдат отменени.
- Не прави архитектурни зависимости към един AI provider.
- Изграждай модулите така, че Phase 2 функционалностите да могат да се добавят без преработка на MVP core.
- При неясно изискване не измисляй поведение, а маркирай решението като архитектурен въпрос за уточняване.
- Преди преминаване към следваща фаза трябва да бъдат изпълнени acceptance criteria от текущата.

## 28. Кратко архитектурно резюме

SmartDoc Formatter трябва да бъде система, в която AI разбира структурата на съдържанието, но не контролира директно визуалното оформление. Структурираният Document Model е центърът между AI, formatting engine, editor и export системата.

```
User
 ↓
Input
 ↓
Parser
 ↓
AI Structure Analysis
 ↓
Document Model
 ↓
Rules + Template
 ↓
Formatting Engine
 ↓
WYSIWYG Editor
 ↓
User Approval / Manual Editing
 ↓
Export
 ├── DOCX
 └── PDF
```

Тази архитектура позволява продуктът да започне като стабилен formatter и постепенно да се превърне в по-голяма AI платформа за създаване, редактиране и форматиране на документи.

## 29. Заключение

MVP на SmartDoc Formatter трябва да реши един ясно дефиниран проблем: потребителят вече има съдържание и правила, но не иска ръчно да извършва техническото форматиране. Основният продукт трябва да автоматизира тази работа, без да отнема контрола от потребителя.

Ключовите архитектурни решения са отделяне на AI анализа от formatting engine, използване на структуриран Document Model, страничен WYSIWYG редактор с реални страници, система за конфликти и Undo/Redo и независим export слой. След стабилизирането на тази основа могат да бъдат добавени AI Writer, подобряване на текста, style analysis, акаунти и cloud функционалности.

## 30. Източници и изходна документация

Тази спецификация е изградена върху предоставените два документа за SmartDoc Formatter: първоначалното описание на системата и workflow документа. В тях са описани основният проблем, целевите потребители, функционалностите, компонентите, входовете/изходите и четирифазният workflow.

Бележка: конкретният избор на editor библиотека, точните AI provider параметри, финалните API schemas и някои технически ограничения следва да бъдат потвърдени в началото на Phase 0, преди production implementation.

> **Направени решения в Phase 0-1**: editor библиотека — Tiptap (React/ProseMirror); AI provider — Anthropic Claude API, зад provider-agnostic interface (`backend/app/ai/`).
>
> **Направени решения в Phase 2-3**: DOCX/PDF/Markdown се parse-ват детерминистично (без AI) — `python-docx`, `pypdf`, `markdown-it-py`; AI structure analysis (`messages.parse` structured output) се вика само за неструктурирана проза, с retry + text-fidelity check и fallback към naive segmenter при неуспех; модел по подразбиране — `claude-sonnet-5`.
>
> **Направени решения в Phase 4**: formatting engine-ът е изцяло детерминистичен (NFR-007) — AI участва само в extraction-а на инструкции към `FormattingRule`, никога в прилагането им; 3 вградени template-а (academic/professional/official) плюс custom templates през `POST /api/templates` (in-memory, като документите); от 7-те priority tier-а в §7.9 са реализирани само тези с реален производител тази фаза (template, custom template, инструкции — виж README за пълния списък).
>
> **Направени решения в Phase 5a**: "реални отделни страници" (§7.12) са реализирани като CSS визуална апроксимация (repeating shadow seam на всеки page-height, изчислен точно от pageSize/orientation) в един continuous scroll container, не истинска page-reflow логика — съзнателно решение, потвърдено с Boril преди старта на фазата, тъй като истинска пагинация върху Tiptap/ProseMirror е отделен голям инженерен проект. Toolbar-ът и bold/italic/font/size/alignment/list edits са изцяло локални в браузъра (директни ProseMirror marks), не минават през backend-ния FormattingRule/resolvedStyles механизъм.
>
> **Направени решения в Phase 5b**: живата per-element промяна (§7.9 tier 1) използва елемента собствен `id` като `FormattingRule.target` вместо груб type-level label — без нужда от schema промяна. `PATCH`/`DELETE .../elements/{id}/style` пазят/чистят точно едно свойство на точно един елемент; `apply_formatting` вече пази съществуващите tier-1 правила през повторно форматиране (NFR-008 — ръчните промени печелят и след нов template). Boril потвърди разделянето на Phase 5 на части (5b: само properties panel + override; 5c по-късно: истински undo/redo + пълен conflict modal по спецификацията).
>
> **Направени решения в Phase 5c**: formatting undo/redo е отделен stack от пълни `Document` snapshots в `DocumentService` (не diff/command log — документите са малки и вече изцяло in-memory) — отделен от Tiptap-овия текстов undo/redo, който остава недокоснат. Conflict modal-ът е пълната версия по §7.10 (потвърдено с Boril) — `detect_conflicts()` сравнява входящите template/instruction правила само срещу съществуващи live overrides и само където резолюцията реално би се различавала; `/format` връща 409 с конфликтите вместо да прилага нещо, ако няма подадени resolutions. Виж [README.md](../README.md) за пълния списък допускания.
>
> **Направени решения в Phase 6**: DOCX и PDF са два напълно независими exporter-а, не DOCX→PDF конверсия — проверено директно, че `soffice`/LibreOffice липсва на тази машина, а `docx`/`xlsx` skill-овете's собствен `soffice.py` wrapper е Linux-only (използва `socket.AF_UNIX`), така че shell-ване към LibreOffice не е опция тук. `backend/app/export/docx_export.py` (python-docx, вече dependency) и `backend/app/export/pdf_export.py` (`reportlab`, нова чисто-Python pip зависимост, без системен install) четат един и същ `document.resolvedStyles`, но рисуват независимо през две несвързани библиотеки. Флагната граница: reportlab няма вградени TrueType шрифтове отвъд Helvetica/Times/Courier, така че PDF шрифтовете са substituted, не пиксел-идентични с editor preview-то или DOCX-а. И двата exporter-а са round-trip тествани (build → прочети обратно) плюс живо потвърдени през браузъра. Виж [README.md](../README.md) за пълния списък допускания.
