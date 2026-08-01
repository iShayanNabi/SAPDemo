"""Guided demonstration support shared by the API and the Streamlit pages."""

from app.services.demo.catalog import (
    DEMO_MODULES,
    DemoModuleSpec,
    describe_modules,
    get_module_spec,
    load_module_demo,
)

__all__ = [
    "DEMO_MODULES",
    "DemoModuleSpec",
    "describe_modules",
    "get_module_spec",
    "load_module_demo",
]
