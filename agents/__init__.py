"""Expose .agents/verify_bundle helpers under the `agents` package."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_VERIFY_PATH = Path(__file__).resolve().parent.parent / ".agents" / "verify_bundle.py"
_SPEC = importlib.util.spec_from_file_location("_clearbuy_verify_bundle", _VERIFY_PATH)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

verify_bundle_dict = _MOD.verify_bundle_dict
verify_api_payload = _MOD.verify_api_payload
compute_constraints_hash = _MOD.compute_constraints_hash
infer_placement_mode = _MOD.infer_placement_mode
handle_hook_stdin = _MOD.handle_hook_stdin

__all__ = [
    "verify_bundle_dict",
    "verify_api_payload",
    "compute_constraints_hash",
    "infer_placement_mode",
    "handle_hook_stdin",
]
