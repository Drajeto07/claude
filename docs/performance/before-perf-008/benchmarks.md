# Benchmarks

Made by `python -m scripts.benchmark` (2026-10-06 11:51 UTC); how to run and read it: [README.md](README.md).

## Machine

- CPU: Intel(R) Xeon(R) Processor @ 2.10GHz, 4 cores
- RAM: 15.7 GiB
- OS: Linux 6.18.44-fc-v70
- Python: 3.13.14
- Code: git commit unknown
- Options: blocks 1651,12201, repeats 4, limit 900 s per case, only: patch, save

**Timings are noisy.** This machine ran other jobs at the same time (other test runs and builds), so read a difference under about 20% as noise; the best of the repeats is the least disturbed number. Memory is tracemalloc's peak: Python allocations only, not what lxml, Pillow or SQLite allocate themselves.

## Save (PUT /content)

| Document | Request body | documents.data stored | Best | CPU of the best | Median | Peak memory |
|---|---:|---:|---:|---:|---:|---:|
| blocks-1651 | 1,294,666 B | 1,855,950 B | 228 ms | 213 ms | 234 ms | 22.5 MiB |
| blocks-12201 | 9,582,019 B | 13,707,930 B | 1.86 s | 1.80 s | 2.11 s | 164.9 MiB |

## Patch (PATCH /content, one paragraph)

| Document | Request body | Response | Best | CPU of the best | Median | Peak memory |
|---|---:|---:|---:|---:|---:|---:|
| blocks-1651 | 1,037 B | 1,229 B | 229 ms | 181 ms | 253 ms | 21.3 MiB |
| blocks-12201 | 1,037 B | 1,229 B | 1.56 s | 1.55 s | 1.74 s | 155.6 MiB |

