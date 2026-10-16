# Benchmarks

Made by `python -m scripts.benchmark` (2026-10-01 07:38 UTC); how to run and read it: [README.md](README.md).

## Machine

- CPU: Intel(R) Xeon(R) Processor @ 2.80GHz, 4 cores
- RAM: 15.7 GiB
- OS: Linux 6.18.44-fc-v50
- Python: 3.13.14
- Code: git commit 370ed49
- Options: repeats 3, limit 900 s per case, only: export, import, load, save

**Timings are noisy.** This machine ran other jobs at the same time (other test runs and builds), so read a difference under about 20% as noise; the best of the repeats is the least disturbed number. Memory is tracemalloc's peak: Python allocations only, not what lxml, Pillow or SQLite allocate themselves.

## Import

| Fixture | File | Blocks | Best | Median | Peak memory |
|---|---:|---:|---:|---:|---:|
| documents/01-simple.docx | 36,769 B | 4 | 59 ms | 61 ms | 2.2 MiB |
| documents/02-rich-text.docx | 37,021 B | 3 | 61 ms | 88 ms | 2.2 MiB |
| documents/03-tables.docx | 36,907 B | 3 | 56 ms | 61 ms | 2.2 MiB |
| documents/04-images.docx | 37,413 B | 5 | 58 ms | 63 ms | 2.2 MiB |
| documents/05-links.docx | 36,835 B | 4 | 61 ms | 64 ms | 2.2 MiB |
| documents/06-lists.docx | 36,769 B | 6 | 66 ms | 99 ms | 2.2 MiB |
| documents/07-headings.docx | 36,695 B | 12 | 61 ms | 65 ms | 2.2 MiB |
| documents/08-caption.docx | 37,485 B | 5 | 59 ms | 60 ms | 2.2 MiB |
| documents/09-sections.docx | 36,693 B | 2 | 60 ms | 60 ms | 2.2 MiB |
| documents/10-header-footer.docx | 37,799 B | 1 | 57 ms | 65 ms | 2.2 MiB |
| documents/11-page-breaks.docx | 36,710 B | 7 | 57 ms | 60 ms | 2.2 MiB |
| documents/12-complex.docx | 39,417 B | 14 | 68 ms | 71 ms | 2.2 MiB |
| documents/13-kept-blocks.docx | 36,917 B | 7 | 61 ms | 64 ms | 2.2 MiB |
| documents/14-section-headers.docx | 38,884 B | 7 | 57 ms | 64 ms | 2.2 MiB |
| documents/15-numbering.docx | 37,300 B | 18 | 75 ms | 85 ms | 2.2 MiB |
| documents/16-table-engine.docx | 37,153 B | 6 | 62 ms | 68 ms | 2.2 MiB |
| documents/17-pictures.docx | 38,692 B | 9 | 72 ms | 134 ms | 2.2 MiB |
| word/a01-formatting.docx | 13,577 B | 33 | 35 ms | 36 ms | 569 KiB |
| word/a02-tables.docx | 20,377 B | 15 | 65 ms | 69 ms | 962 KiB |
| word/a03-lists.docx | 14,957 B | 30 | 49 ms | 51 ms | 721 KiB |
| word/a04-images.docx | 429,886 B | 24 | 33 ms | 34 ms | 1.4 MiB |
| word/a05-sections.docx | 26,505 B | 12 | 47 ms | 48 ms | 478 KiB |
| word/a06-fields.docx | 22,820 B | 22 | 68 ms | 69 ms | 487 KiB |
| word/a07-review.docx | 16,986 B | 8 | 40 ms | 40 ms | 438 KiB |
| word/a08-content-controls.docx | 21,515 B | 12 | 42 ms | 43 ms | 475 KiB |
| word/a09-objects.docx | 48,504 B | 10 | 26 ms | 27 ms | 576 KiB |
| word/a10-notes.docx | 13,815 B | 12 | 31 ms | 39 ms | 452 KiB |
| word/a11-multilingual.docx | 13,107 B | 12 | 31 ms | 35 ms | 523 KiB |
| word/a12-properties.docx | 12,156 B | 4 | 17 ms | 21 ms | 397 KiB |
| word/a13-pictures.docx | 113,442 B | 10 | 24 ms | 26 ms | 676 KiB |
| word/a14-modified-styles.docx | 12,048 B | 6 | 21 ms | 23 ms | 433 KiB |
| word/a15-links.docx | 12,022 B | 6 | 18 ms | 19 ms | 379 KiB |
| word/r01-university-paper.docx | 24,351 B | 24 | 49 ms | 52 ms | 624 KiB |
| word/r02-cv.docx | 14,608 B | 6 | 24 ms | 26 ms | 465 KiB |
| word/r03-contract.docx | 19,763 B | 6 | 26 ms | 29 ms | 458 KiB |
| word/r04-medical-synthetic.docx | 12,321 B | 7 | 23 ms | 24 ms | 442 KiB |
| word/r05-invoice.docx | 20,623 B | 3 | 27 ms | 29 ms | 491 KiB |

## Export

| Document | Format | Output | Best | Median | Peak memory |
|---|---|---:|---:|---:|---:|
| blocks-500 | docx | 40,918 B | 273 ms | 292 ms | 4.7 MiB |
| blocks-500 | pdf | 100,643 B | 245 ms | 261 ms | 4.8 MiB |
| blocks-2000 | docx | 48,929 B | 882 ms | 896 ms | 11.6 MiB |
| blocks-2000 | pdf | 266,244 B | 946 ms | 967 ms | 16.8 MiB |
| blocks-5000 | docx | 64,640 B | 2.44 s | 2.69 s | 29.0 MiB |
| blocks-5000 | pdf | 597,612 B | 2.27 s | 2.40 s | 41.8 MiB |
| table-500x8 | docx | 50,162 B | 247.12 s | 247.12 s | not measured |
| table-500x8 | pdf | 111,815 B | 1.03 s | 1.39 s | 29.4 MiB |
| pictures-50 | docx | 2,936,031 B | 338 ms | 360 ms | 9.1 MiB |
| pictures-50 | pdf | 3,656,185 B | 993 ms | 1.15 s | 14.6 MiB |

## Save (PUT /content)

| Document | Request body | documents.data stored | Best | Median | Peak memory |
|---|---:|---:|---:|---:|---:|
| blocks-500 | 391,787 B | 1,117,596 B | 69 ms | 72 ms | 6.9 MiB |
| blocks-2000 | 1,569,286 B | 4,463,490 B | 299 ms | 302 ms | 27.7 MiB |
| blocks-5000 | 3,924,936 B | 11,154,890 B | 852 ms | 918 ms | 68.8 MiB |
| table-500x8 | 719,989 B | 1,408,015 B | 204 ms | 232 ms | 29.9 MiB |
| pictures-50 | 3,890,391 B | 111,055 B | 101 ms | 106 ms | 15.0 MiB |

## Load (GET)

| Document | Response | Best | Median | Peak memory |
|---|---:|---:|---:|---:|
| blocks-500 | 537,857 B | 24 ms | 25 ms | 3.2 MiB |
| blocks-2000 | 2,144,326 B | 77 ms | 79 ms | 12.6 MiB |
| blocks-5000 | 5,357,916 B | 159 ms | 179 ms | 31.2 MiB |
| table-500x8 | 1,093,493 B | 53 ms | 89 ms | 11.8 MiB |
| pictures-50 | 71,871 B | 11 ms | 12 ms | 655 KiB |

