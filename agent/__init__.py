"""Dataset-agnostic spatial-marker / cell-type validator agent.

The agent *logic* lives here and never changes per dataset. Everything
dataset-specific (label vocabulary, marker KB, adjacency, prompts) is supplied
via a config dict loaded from configs/*.yaml.
"""
from .loop import predict
from .providers import make_client
from .tools import load_kb, TOOLS, dispatch
from .schema import prediction_schema

__all__ = ["predict", "make_client", "load_kb", "TOOLS", "dispatch", "prediction_schema"]
