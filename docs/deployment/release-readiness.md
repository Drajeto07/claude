# Готовност за първото пускане (към 2026-10-13, вечерта)

Тракер: фаза 19, лист FIRST_RELEASE. Как върви: [vercel.md](vercel.md). Ръчните проверки: [manual-checks.md](manual-checks.md).

## Къде сме

| | Състояние |
|---|---|
| **Production сега** | `dpl_HxSobnp5…`, commit `4c8fdca`, https://smartdoc-peach.vercel.app (зад Vercel Authentication). Работи: `/api/ready` = ready, регистрация, табло. **Пази файловете в контейнера** (губят се) и е в iad1 -- новите настройки влизат в сила едва със следващ deployment. |
| **Кандидат** | `dpl_322EDgsYzSEbSQYEKGav3jdPGP13`, commit `f644146` (кодът от `b5f8142`), `smartdoc-mw2cz3il7-drajeto.vercel.app`, READY, fra1. = проверения от собственика `3302c48` + лимитът от 270 s за задача (само тестове, не и браузър). |
| **Production настройки** | Добавени 2026-10-13 с одобрение: `STORAGE_BACKEND`, `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `CORS_ORIGINS`, `FRONTEND_URL`. Вече бяха: `DATABASE_URL`, S3 ключовете, `DATABASE_POOLER`, `JOB_BACKEND`, `NEXT_PUBLIC_API_BASE_URL`, `PORT`. Липсва: `SENTRY_DSN` (собственикът). |
| **Тестове** | backend 2599 passed / 11 skipped; Vitest 368; tsc; next build; Playwright 59 passed (локално). |
| **Проверено на Preview** (собственикът + логовете на Supabase) | `/api/ready` с database и storage ok; TXT и DOCX с картинка: качване, отваряне, повторно отваряне след изчакване; DOCX експорт, отворен в Word; заявките от fra1; всички 200/202. |
| **Не е проверено на живо** | Изолация с два акаунта; лимит над 4 MB; грешен тип файл; PDF качване; шаблони; изтриване на документ (manual-checks.md 3, 7, 10-15). |

## SENTRY_DSN (собственикът, без стойността в чата)

1. sentry.io → организация `drajeto` → проект `smartdoc-backend` → Settings → **Client Keys (DSN)**.
2. Копирайте DSN-а (започва с `https://` и завършва с номера на проекта).
3. Vercel → smartdoc → Settings → Environment Variables → **Add**: име `SENTRY_DSN`, стойността, само
   **Production** (по желание и Preview) → Save. Не е нужен redeploy сега: влиза със следващия deployment.
4. Кажете ми „добавен“ -- проверявам само, че името е там.

## Проверки преди Promote (в този ред)

1. Собственикът, на кандидата `smartdoc-mw2cz3il7-drajeto.vercel.app` (2-3 минути): вход, отваряне на документ,
   един DOCX експорт; по желание manual-checks.md 11 (файл над 4 MB) и 13-15 (втори акаунт).
2. Claude: логовете на кандидата (без грешки), обектите в bucket-а (брой/размер), имената на Production настройките.
3. `SENTRY_DSN` добавен (по желание преди Promote; без него грешките се виждат само в логовете).
4. **Отделно одобрение за Promote.** Promote build-ва наново с Production настройките.
5. След Promote (Claude, веднага): deployment READY в fra1; `/api/ready` = `database: ok, storage: ok` (през
   браузъра на собственика или bypass, ако бъде одобрен); логовете за 5xx; Supabase: заявки от FRA.
6. Собственикът, на https://smartdoc-peach.vercel.app: вход с акаунта от разработката, отваряне на документ, качване
   на DOCX с картинка, експорт. **Старите документи с картинки:** картинките им бяха на диска на старата
   инстанция и няма да се покажат -- това не е регресия (решение REL-020: данните остават).
7. Rollback при проблем: Vercel → Deployments → `dpl_HxSobnp5…` → Instant Rollback (базата няма нужда от нищо).

## Оставащи блокери

| | Какво | Чие |
|---|---|---|
| REL-010 | Promote на кандидата + проверките по-горе | одобрение на собственика |
| REL-003 | `SENTRY_DSN` | собственикът |
| REL-011 | Изолация с два акаунта на живо | собственикът (manual-checks.md 13-15) |
| REL-022 | Достъп за автоматични проверки | решено: **без** bypass засега; проверките са ръчни |
| REL-008 | Uptime monitor -- не може да вижда `/api/health` зад Vercel Authentication без bypass | след решение за достъпа |
| TEST-043 | CI в браузър: pull request feature → main (без merge) | собственикът (в GitHub) |
| REL-016 / REL-023 | Реални имейли и възстановяване на парола; без тях -- без публична регистрация | домейн на собственика |
| REL-014 | Почистване (виж плана по-долу) | одобрение на собственика |

## План за REL-014 (почистване) -- само план, нищо не е изтрито

**Какво чака почистване, докато задачите работят в заявката (`JOB_BACKEND=eager`):**

| Какво | Кога по замисъл | Кое го трие |
|---|---|---|
| Файлове на експорти (`jobs/<id>/output`) | 24 часа след експорта (`JOB_FILE_TTL_HOURS`) | `sweep_job_files` |
| Редове за задачи | 7 дни (`JOB_RETENTION_DAYS`); никога „dead letter“ | `sweep_job_files` |
| Изтекли/отменени сесии, използвани/изтекли еднократни токени, неизползвани записи за браузъри | 30 / 7 / 400 дни | `sweep_account_records` |
| Картинки, към които не сочи нито един документ | по-стари от 1 ден (`GRACE_PERIOD`); запазените Word оригинали -- само ако `KEPT_ORIGINAL_RETENTION_DAYS` > 0 (сега 0: пазят се) | `sweep_unused_assets` |

Не се трият: акаунти, документи, картинки на документи, шаблони, версии.

**Предложение (на етапи, всеки с одобрение):**
1. **Отчет без триене:** скрипт/endpoint, който само брои какво би изтрил всеки sweep (брой и общ размер), пуснат
   ръчно срещу Production базата -- само четене.
2. **Защитен endpoint** `GET /api/cron/maintenance`: изпълнява `sweep_job_files` и `sweep_account_records` (без
   картинките на първо време); отказва (401) без `Authorization: Bearer <CRON_SECRET>`; 503, ако `CRON_SECRET`
   липсва; пише в лога само броя изтрити.
3. **Vercel Cron** в `vercel.json`: веднъж дневно (лимитът на Hobby), напр. 03:00 UTC. `CRON_SECRET` се добавя от
   собственика във Vercel (секрет; Vercel го праща сам към cron заявката).
4. Тестове: endpoint-ът без/с грешен ключ (401), без `CRON_SECRET` (503), с ключ -- трие само изтеклото; документи
   и акаунти недокоснати.
5. Първо на Preview (Cron работи само в Production -- там се проверява след Promote, с отчета от т. 1 за сравнение).
6. `sweep_unused_assets` -- отделно, по-късно, след като отчетът от т. 1 покаже какво би изтрил.
