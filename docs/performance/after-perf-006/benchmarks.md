# Benchmarks

Made by `python -m scripts.benchmark` (2026-10-01 07:51 UTC); how to run and read it: [README.md](README.md).

## Machine

- CPU: Intel(R) Xeon(R) Processor @ 2.80GHz, 4 cores
- RAM: 15.7 GiB
- OS: Linux 6.18.44-fc-v50
- Python: 3.13.14
- Code: git commit 024783b
- Options: repeats 3, limit 900 s per case, only: load, save

**Timings are noisy.** This machine ran other jobs at the same time (other test runs and builds), so read a difference under about 20% as noise; the best of the repeats is the least disturbed number. Memory is tracemalloc's peak: Python allocations only, not what lxml, Pillow or SQLite allocate themselves.

## Save (PUT /content)

| Document | Request body | documents.data stored | Best | Median | Peak memory |
|---|---:|---:|---:|---:|---:|
| blocks-500 | 391,787 B | 564,084 B | 88 ms | 91 ms | 8.3 MiB |
| blocks-2000 | 1,569,286 B | 2,248,418 B | 259 ms | 291 ms | 32.7 MiB |
| blocks-5000 | 3,924,936 B | 5,617,738 B | 842 ms | 940 ms | 81.5 MiB |
| table-500x8 | 719,989 B | 1,199,423 B | 226 ms | 231 ms | 35.2 MiB |
| pictures-50 | 3,890,391 B | 77,743 B | 122 ms | 134 ms | 15.0 MiB |

## Load (GET)

| Document | Response | Best | Median | Peak memory |
|---|---:|---:|---:|---:|
| blocks-500 | 537,857 B | 22 ms | 27 ms | 3.2 MiB |
| blocks-2000 | 2,144,326 B | 67 ms | 97 ms | 12.6 MiB |
| blocks-5000 | 5,357,916 B | 157 ms | 163 ms | 31.2 MiB |
| table-500x8 | 1,093,493 B | 67 ms | 71 ms | 11.8 MiB |
| pictures-50 | 71,871 B | 15 ms | 15 ms | 655 KiB |

