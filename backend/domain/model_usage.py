"""Token counts and provenance for calls visible to this application."""

import json
from functools import lru_cache
from typing import Any

from tokenizers import Tokenizer, models, pre_tokenizers


@lru_cache(maxsize=1)
def _tokenizer() -> Tokenizer:
    alphabet = pre_tokenizers.ByteLevel.alphabet()
    tokenizer = Tokenizer(models.BPE(vocab={char: i for i, char in enumerate(alphabet)}, merges=[]))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    return tokenizer


def estimate_tokens(text: str) -> int | None:
    try:
        return len(_tokenizer().encode(text).ids)
    except Exception:
        return None


def model_call_usage(
    messages: list[dict[str, str]], content: str | None, usage: dict[str, int] | None
) -> dict[str, Any]:
    if usage is not None:
        return {
            "input_tokens": usage["input_tokens"],
            "input_source": "actual",
            "output_tokens": usage["output_tokens"],
            "output_source": "actual",
            "tokenizer": None,
        }
    input_count = estimate_tokens(json.dumps(messages, ensure_ascii=False))
    output_count = estimate_tokens(content) if content is not None else None
    return {
        "input_tokens": input_count,
        "input_source": "estimated" if input_count is not None else "unknown",
        "output_tokens": output_count,
        "output_source": "estimated" if output_count is not None else "unknown",
        "tokenizer": "bytelevel-v1",
    }


def embedding_usage(texts: list[str]) -> dict[str, Any]:
    counts = [estimate_tokens(text) for text in texts]
    known = all(count is not None for count in counts)
    return {
        "input_tokens": sum(count for count in counts if count is not None) if known else None,
        "input_source": "estimated" if known else "unknown",
        "output_tokens": None,
        "output_source": "not_applicable",
        "tokenizer": "bytelevel-v1",
    }
