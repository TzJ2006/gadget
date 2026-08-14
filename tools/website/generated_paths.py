"""Pipeline-generated Hugo paths, relative to content/.

Deploy pipelines write complete bilingual pairs here (gadget_generated /
gadget:src-hash). Translation and preflight skip them so src-hash markers
stay in sync. Override with translate_site_batch --include-generated.
"""

GENERATED_CONTENT_DIRS = (
    "bugJournal/daily",
    "bugJournal/weekly",
    "bugJournal/monthly",
    "research",
)
GENERATED_CONTENT_FILES = ("benchmark.md", "benchmark.zh.md")
