"""Process a saved retrieval run with per-case failure isolation."""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from time import monotonic

from backend.adapters.local_embeddings import EmbeddingCache, Encoder, FastEmbedEncoder
from backend.adapters.run_store import RunStore
from backend.domain.datasets import ReferenceChunk
from backend.domain.matching import candidate_pairs, relevant_texts
from backend.domain.predictions import PredictedChunk
from backend.domain.retrieval_scoring import score_retrieval

EncoderFactory = Callable[[str, Path, Path | None, bool], Encoder]


def process_run(
    run_id: str, data_dir: Path, encoder_factory: EncoderFactory = FastEmbedEncoder
) -> None:
    store = RunStore(data_dir)
    if not store.claim(run_id):
        return
    config = store.config(run_id)
    try:
        model_path = Path(config["model_path"]) if config["model_path"] else None
        encoder = encoder_factory(
            config["model_name"], data_dir / "models", model_path, config["offline"]
        )
        store.set_model_id(run_id, encoder.model_id)
        cache = EmbeddingCache(data_dir)
    except Exception as exc:
        store.fail_pending(run_id, f"model_unavailable:{type(exc).__name__}")
        store.finish(run_id)
        return

    try:
        for case_id in store.pending_case_ids(run_id):
            if store.cancellation_requested(run_id):
                break
            start = monotonic()
            try:
                item = store.input_for_case(run_id, case_id)
                if item["reference_chunks"] is None:
                    store.record_case(
                        run_id, case_id, "not_applicable", elapsed_ms=(monotonic() - start) * 1000
                    )
                    continue
                if item["contexts"] is None:
                    raise ValueError("missing_contexts")
                reference = [ReferenceChunk(**chunk) for chunk in item["reference_chunks"]]
                predicted = [PredictedChunk(**chunk) for chunk in item["contexts"]]
                vectors = cache.vectors(encoder, relevant_texts(reference, predicted))
                pairs = candidate_pairs(reference, predicted, vectors, config["threshold"])
                score = score_retrieval(
                    reference, predicted, pairs, encoder.model_id, config["threshold"]
                )
                store.record_case(
                    run_id,
                    case_id,
                    "success",
                    score=asdict(score),
                    elapsed_ms=(monotonic() - start) * 1000,
                )
            except Exception as exc:
                store.record_case(
                    run_id,
                    case_id,
                    "failed",
                    error=f"scoring_error:{type(exc).__name__}",
                    elapsed_ms=(monotonic() - start) * 1000,
                )
    except Exception as exc:
        store.fail_pending(run_id, f"worker_error:{type(exc).__name__}")
    finally:
        store.finish(run_id)
