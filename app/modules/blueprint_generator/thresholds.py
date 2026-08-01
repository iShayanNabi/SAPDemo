"""Typed, validated access to the Blueprint Generator configuration.

Every value the generator decides for itself - which sections exist, what they
are called, which project inputs each one requires, which of its items are
*computed* from the request rather than drafted, how many items it may hold, the
identifier scheme and the text a section falls back to - lives in
``config/blueprint_rules.json`` and is validated here at load time.

That separation is what keeps this module honest about the deterministic/AI
boundary. A language model writes the prose inside a section; it never decides
that a section exists, that a company code is in scope, that an interface is
needed or that a role has to be built. Those come from this file and from the
project request, so "add a section", "make integrations optional" or "reword the
fallback text" is a JSON edit, not a code change.

Three validations here are worth naming, because each one turns a silent wrong
answer into a startup error:

* every section named in the configuration must be one the engine knows, and
  every section the engine knows must be configured - a half-configured document
  would silently drop a heading;
* ``required_inputs`` and ``derives_from`` may only name real fields of the
  project request, so a typo cannot make a section permanently unreachable;
* ``depends_on`` may only name sections that exist and never the section itself,
  because that graph is what the staleness reporting walks.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.blueprint import (
    SECTION_ORDER,
    BlueprintProjectSchema,
    ContentKind,
    SectionKey,
)

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "blueprint_rules.json"

#: The field names of the project request, used to validate the configuration.
PROJECT_FIELDS: frozenset[str] = frozenset(BlueprintProjectSchema.model_fields)


class PlaceholderDefaults(BaseModel):
    """What a template placeholder becomes when the project supplied nothing.

    A template that renders ``covering {modules}`` when no module was entered
    must not print ``covering``. A sentence with a hole in it is worse than a
    generic one, because a reader cannot tell whether something was lost.
    """

    model_config = {"extra": "allow"}

    modules: str = "the modules named in the project request"
    primary_module: str = "the lead SAP module"
    countries: str = "the countries named in the project request"
    locations: str = "the sites named in the project request"
    company_codes: str = "the company codes named in the project request"
    plants: str = "the plants named in the project request"
    purchasing_organizations: str = "the purchasing organisations named in the project request"
    systems: str = "the systems named in the project request"
    integrations: str = "the integrations named in the project request"
    data_sources: str = "the data sources named in the project request"
    user_groups: str = "the user groups named in the project request"
    objectives: str = "the business objectives named in the project request"
    primary_objective: str = "the lead business objective"
    timeline: str = "the timeline recorded for this project"
    constraints: str = "the constraints recorded for this project"

    def value_for(self, key: str) -> str:
        """Return the configured default for ``key``, or a readable fallback."""
        value = getattr(self, key, None)
        if isinstance(value, str) and value:
            return value
        extra = (self.model_extra or {}).get(key)
        if isinstance(extra, str) and extra:
            return extra
        return key.replace("_", " ")


class GenerationSettings(BaseModel):
    """Identifier scheme, size limits and the defaults a new section starts from."""

    description: str = ""
    id_prefix: str = Field(default="BP", min_length=1, max_length=10)
    section_id_template: str = "{prefix}-{code}"
    custom_section_id_template: str = "{prefix}-CUS-{number:03d}"
    item_id_template: str = "{prefix}-{code}-{number:03d}"
    id_number_start: int = Field(default=1, ge=0)
    max_custom_sections: int = Field(default=20, ge=0, le=100)
    max_items_per_section: int = Field(default=40, ge=1, le=200)
    max_title_chars: int = Field(default=200, ge=20)
    max_detail_chars: int = Field(default=3000, ge=20)
    max_narrative_chars: int = Field(default=20000, ge=100)
    min_narrative_chars: int = Field(default=40, ge=0)
    max_items_per_ai_section: int = Field(default=12, ge=1, le=100)
    default_owner: str = "Unassigned"
    default_status: str = "draft"
    placeholder_defaults: PlaceholderDefaults = Field(default_factory=PlaceholderDefaults)

    def model_post_init(self, _context: object) -> None:
        if self.min_narrative_chars > self.max_narrative_chars:
            raise ValueError(
                "generation.min_narrative_chars is greater than generation.max_narrative_chars"
            )
        if self.max_items_per_ai_section > self.max_items_per_section:
            raise ValueError(
                "generation.max_items_per_ai_section exceeds generation.max_items_per_section"
            )
        for name, template, sample in (
            ("section_id_template", self.section_id_template, {"prefix": "BP", "code": "SCOPE"}),
            (
                "custom_section_id_template",
                self.custom_section_id_template,
                {"prefix": "BP", "number": 1},
            ),
            (
                "item_id_template",
                self.item_id_template,
                {"prefix": "BP", "code": "SCP", "number": 1},
            ),
        ):
            try:
                template.format(**sample)
            except (KeyError, IndexError, ValueError) as exc:
                raise ValueError(
                    f"generation.{name} is not a usable format string: {exc}"
                ) from exc

    def build_section_id(self, code: str) -> str:
        """Render one canonical section identifier, e.g. ``BP-SCOPE``."""
        return self.section_id_template.format(prefix=self.id_prefix, code=code)

    def build_custom_section_id(self, number: int) -> str:
        """Render one custom section identifier, e.g. ``BP-CUS-001``."""
        return self.custom_section_id_template.format(prefix=self.id_prefix, number=number)

    def build_item_id(self, code: str, number: int) -> str:
        """Render one item identifier, e.g. ``BP-ORG-003``."""
        return self.item_id_template.format(prefix=self.id_prefix, code=code, number=number)


class ReadinessSettings(BaseModel):
    """How the completeness and approval percentages are computed."""

    description: str = ""
    decimals: int = Field(default=1, ge=0, le=4)
    #: Whether a section waiting for a project input counts towards completeness.
    #: It does not by default: a heading with nothing under it is not written.
    count_needs_input_as_complete: bool = False


class DerivationSpec(BaseModel):
    """One project field whose values become items of a section.

    This is the mechanism behind the module's central rule: an organisational
    unit, an integration, a migration source or a role exists in the blueprint
    **because the project request named it**, never because a model thought it
    plausible.
    """

    field: str
    category: str = ""
    detail_template: str = ""
    reference_template: str = ""
    owner: str = ""
    rating: str = ""

    def model_post_init(self, _context: object) -> None:
        if self.field not in PROJECT_FIELDS:
            raise ValueError(
                f"derives_from names '{self.field}', which is not a field of the project "
                f"request. Known fields: {sorted(PROJECT_FIELDS)}"
            )


class TemplateItem(BaseModel):
    """One item used when no model drafted the section."""

    title: str = Field(min_length=2)
    detail: str = ""
    category: str = ""
    reference: str = ""
    owner: str = ""
    rating: str = ""


class SectionSpec(BaseModel):
    """One blueprint section: how it is titled, filled, limited and templated."""

    title: str = Field(min_length=2, max_length=200)
    section_code: str = Field(min_length=2, max_length=10)
    content_kind: ContentKind = ContentKind.LIST
    description: str = ""
    guidance: str = ""
    #: Project fields that must be non-empty before this section can be written.
    required_inputs: list[str] = Field(default_factory=list)
    derives_from: list[DerivationSpec] = Field(default_factory=list)
    #: Section keys whose content this section describes. Used for staleness.
    depends_on: list[str] = Field(default_factory=list)
    #: False for the factual sections: a model writes their narrative but may
    #: never add a row to them.
    allow_ai_items: bool = True
    min_items: int = Field(default=0, ge=0)
    max_items: int = Field(default=25, ge=0)
    item_code: str = Field(min_length=2, max_length=10)
    template_narrative: str = Field(min_length=10)
    template_items: list[TemplateItem] = Field(default_factory=list)

    def model_post_init(self, _context: object) -> None:
        if self.min_items > self.max_items:
            raise ValueError(
                f"section '{self.title}': min_items ({self.min_items}) is greater than "
                f"max_items ({self.max_items})"
            )
        unknown = [name for name in self.required_inputs if name not in PROJECT_FIELDS]
        if unknown:
            raise ValueError(
                f"section '{self.title}': required_inputs names unknown project fields "
                f"{unknown}. A typo here would make the section permanently unreachable."
            )

    @property
    def is_derived(self) -> bool:
        """True when the section's items come from the project request."""
        return bool(self.derives_from)

    @property
    def derived_fields(self) -> list[str]:
        """The project fields whose values become items of this section."""
        return [spec.field for spec in self.derives_from]


class ReportingSettings(BaseModel):
    """The standing statements printed on every response and every export."""

    disclaimer: str = ""
    ai_note: str = ""
    review_note: str = ""


class BlueprintConfig(BaseModel):
    """The complete, validated Blueprint Generator configuration."""

    config_version: str
    description: str = ""
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    readiness: ReadinessSettings = Field(default_factory=ReadinessSettings)
    sections: dict[str, SectionSpec]
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        expected = [item.value for item in SECTION_ORDER]
        missing = [name for name in expected if name not in self.sections]
        if missing:
            raise ValueError(f"configuration is missing blueprint sections: {missing}")
        unknown = [name for name in self.sections if name not in expected]
        if unknown:
            raise ValueError(
                f"configuration declares sections the engine does not know: {unknown}. "
                f"Add them to SectionKey in app/schemas/blueprint.py first."
            )

        codes = {name: spec.section_code.upper() for name, spec in self.sections.items()}
        if len(set(codes.values())) != len(codes):
            raise ValueError(
                f"two sections share a section_code, which would collide in the "
                f"identifiers: {codes}"
            )
        item_codes = {name: spec.item_code.upper() for name, spec in self.sections.items()}
        if len(set(item_codes.values())) != len(item_codes):
            raise ValueError(
                f"two sections share an item_code, which would collide in the item "
                f"identifiers: {item_codes}"
            )

        for name, spec in self.sections.items():
            for dependency in spec.depends_on:
                if dependency == name:
                    raise ValueError(f"section '{name}' declares itself as a dependency")
                if dependency not in self.sections:
                    raise ValueError(
                        f"section '{name}' depends on '{dependency}', which is not a "
                        f"configured section"
                    )

    # -- helpers ---------------------------------------------------------
    def spec(self, section: SectionKey | str) -> SectionSpec:
        """Return one section specification."""
        name = section.value if isinstance(section, SectionKey) else str(section)
        if name not in self.sections:
            raise ConfigurationError(f"Unknown blueprint section: {name}")
        return self.sections[name]

    def title(self, section: SectionKey | str) -> str:
        """Return the human title of a section."""
        return self.spec(section).title

    def dependents_of(self, section_key: str) -> list[str]:
        """Return the sections that describe ``section_key``.

        This is the reverse of ``depends_on`` and is what makes an edit to the
        scope section able to say which other sections have just gone stale.
        """
        return [
            name
            for name in (item.value for item in SECTION_ORDER)
            if section_key in self.sections[name].depends_on
        ]

    def methodology(self) -> dict[str, Any]:
        """Describe, in plain language, how a blueprint is produced."""
        derived = [
            name
            for name in (item.value for item in SECTION_ORDER)
            if self.sections[name].is_derived and not self.sections[name].allow_ai_items
        ]
        return {
            "deterministic": [
                "Which sections exist, what they are called and the order they appear in.",
                "Which project inputs each section requires, and whether they were supplied.",
                "The organisational structure, module list, integration register, interface "
                "list, migration sources and security roles - each computed from the project "
                "request, never drafted.",
                "The section and item identifiers and their numbering.",
                "Every size limit, every field length check and every repair of drafted text.",
                "The completeness and approval percentages.",
                "Every approval, version snapshot and version comparison.",
                "The staleness reporting that says which section describes another section "
                "that has since changed.",
            ],
            "ai_generated": [
                "The narrative of each section, and the wording of the items in the sections "
                "that allow drafted items.",
            ],
            "factual_sections_ai_cannot_add_to": derived,
            "identifier_templates": {
                "section": self.generation.section_id_template,
                "custom_section": self.generation.custom_section_id_template,
                "item": self.generation.item_id_template,
            },
            "section_count": len(self.sections),
            "review_note": self.reporting.review_note,
        }


def load_blueprint_config(path: Path | str | None = None) -> BlueprintConfig:
    """Load and validate the Blueprint Generator configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Blueprint Generator configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Blueprint Generator configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = BlueprintConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Blueprint Generator configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded blueprint generator configuration v%s (%d sections)",
        config.config_version,
        len(config.sections),
    )
    return config


@lru_cache(maxsize=1)
def get_blueprint_config() -> BlueprintConfig:
    """Return the cached default configuration."""
    return load_blueprint_config()
