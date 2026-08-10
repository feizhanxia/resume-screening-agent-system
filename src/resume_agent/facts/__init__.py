"""Versioned local fact resolvers."""

from resume_agent.facts.universities import (
    UniversityCatalog,
    apply_university_resolutions,
)

__all__ = ["UniversityCatalog", "apply_university_resolutions"]
