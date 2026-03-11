# prompts/__init__.py
# Re-exports for convenient importing from the prompts package.
# All prompt engineering lives in this folder — nothing else does.

from prompts.system_prompt import SYSTEM_PROMPT
from prompts.roast_prompt import build_roast_prompt

__all__ = ["SYSTEM_PROMPT", "build_roast_prompt"]
