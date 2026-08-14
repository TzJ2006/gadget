"""Common utilities shared across gadget tools.

Import submodules directly; this package does not re-export, so
``import common`` / ``from common import config`` does not load
LLM or translation engines.

Public modules: bilingual, cache, config, engine, hugo, io, json_utils,
llm, paths, site_staging, translation, website_backup.
"""

__all__ = []
