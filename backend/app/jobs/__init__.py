"""Background jobs (корекции.docx §52): imports, AI formatting, exports and reading
reference documents, done off the request. runner.py holds the work, queue.py
decides where it runs (this process, an arq worker, or inside the request), and
the processing_jobs row is its durable state either way."""
