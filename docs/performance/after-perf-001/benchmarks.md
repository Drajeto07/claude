# Benchmarks

Made by `python -m scripts.benchmark` (2026-10-01 14:43 UTC); how to run and read it: [README.md](README.md).

## Machine

- CPU: Intel(R) Xeon(R) Processor @ 2.10GHz, 4 cores
- RAM: 15.7 GiB
- OS: Linux 6.18.44-fc-v50
- Python: 3.13.14
- Code: git commit d144387
- Options: repeats 3, limit 900 s per case, only: export

**Timings are noisy.** This machine ran other jobs at the same time (other test runs and builds), so read a difference under about 20% as noise; the best of the repeats is the least disturbed number. Memory is tracemalloc's peak: Python allocations only, not what lxml, Pillow or SQLite allocate themselves.

## Export

| Document | Format | Output | Best | Median | Peak memory |
|---|---|---:|---:|---:|---:|
| blocks-500 | docx | 40,918 B | 268 ms | 272 ms | 4.7 MiB |
| blocks-500 | pdf | 100,643 B | 236 ms | 241 ms | 4.8 MiB |
| blocks-2000 | docx | 48,929 B | 824 ms | 884 ms | 11.6 MiB |
| blocks-2000 | pdf | 266,244 B | 901 ms | 1.01 s | 16.8 MiB |
| blocks-5000 | docx | 64,640 B | 2.71 s | 2.78 s | 29.0 MiB |
| blocks-5000 | pdf | 597,612 B | 1.93 s | 2.56 s | 41.8 MiB |
| table-500x8 | docx | 50,166 B | 706 ms | 727 ms | 11.8 MiB |
| table-500x8 | pdf | 111,815 B | 831 ms | 969 ms | 29.4 MiB |
| pictures-50 | docx | 2,936,032 B | 258 ms | 262 ms | 9.1 MiB |
| pictures-50 | pdf | 3,656,185 B | 808 ms | 906 ms | 14.6 MiB |

