"""Process retrieval and answer scoring from an immutable prediction batch."""

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from time import monotonic
from typing import Any

import httpx
from opentelemetry import context, trace

from backend.adapters.answer_model import AnswerModelError, evaluate_answer_metric
from backend.adapters.local_embeddings import EmbeddingCache, Encoder, FastEmbedEncoder
from backend.adapters.model_store import OnlineModelStore
from backend.adapters.run_store import RunStore
from backend.adapters.trace_store import TraceStore
from backend.adapters.usage_store import UsageStore
from backend.domain.answer_prompts import AnswerMetric, AnswerSample, applicability
from backend.domain.datasets import ReferenceChunk
from backend.domain.matching import candidate_pairs, relevant_texts
from backend.domain.model_usage import embedding_usage, model_call_usage
from backend.domain.predictions import PredictedChunk
from backend.domain.retrieval_scoring import score_retrieval
from backend.domain.runs import CaseStatus
from backend.tracing import attributes, business_span, fail, tracer

EncoderFactory = Callable[[str, Path, Path | None, bool], Encoder]
ClientFactory = Callable[[], httpx.Client]
ANSWER_METRICS: tuple[AnswerMetric, ...] = ("faithfulness", "relevance", "correctness")


def _score_retrieval_case(
    item: dict[str, Any],
    config: dict[str, Any],
    encoder: Encoder,
    cache: EmbeddingCache,
    on_call: Callable[[list[str]], None] | None = None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    if item["reference_chunks"] is None:
        return "not_applicable", None, None
    if item["contexts"] is None:
        return "failed", None, "missing_contexts"
    reference = [ReferenceChunk(**chunk) for chunk in item["reference_chunks"]]
    predicted = [PredictedChunk(**chunk) for chunk in item["contexts"]]
    with business_span("retrieval.embed") as span:
        attributes(span, **{"model.id": encoder.model_id})
        try:
            vectors = cache.vectors(encoder, relevant_texts(reference, predicted), on_call)
        except Exception:
            fail(span, "model_error")
            raise
    with business_span("retrieval.match") as span:
        attributes(span, **{"model.id": encoder.model_id})
        try:
            pairs = candidate_pairs(reference, predicted, vectors, config["threshold"])
            score = score_retrieval(
                reference, predicted, pairs, encoder.model_id, config["threshold"]
            )
        except Exception:
            fail(span, "scoring_error")
            raise
    return "success", asdict(score), None


def _score_answer_case(
    store: RunStore,
    run_id: str,
    case_id: str,
    item: dict[str, Any],
    config: dict[str, Any],
    client: httpx.Client | None,
    token: str | None,
    setup_error: str | None,
    usage_store: UsageStore,
) -> list[str]:
    sample = AnswerSample(
        item["question"],
        item["answer"],
        item["reference_answer"],
        tuple(chunk["text"] for chunk in item["contexts"]) if item["contexts"] else None,
    )
    statuses: list[str] = []
    existing = store.answer_metric_statuses(run_id, case_id)
    for metric in ANSWER_METRICS:
        if store.cancellation_requested(run_id):
            break
        if metric in existing:
            statuses.append(existing[metric])
            continue

        def record_answer_call(
            messages: list[dict[str, str]],
            content: str | None,
            usage: dict[str, int] | None,
            current_metric: AnswerMetric = metric,
        ) -> None:
            token_usage = model_call_usage(messages, content, usage)
            attributes(
                trace.get_current_span(),
                **{
                    "token.input": token_usage["input_tokens"],
                    "token.output": token_usage["output_tokens"],
                },
            )
            usage_store.record(
                "run",
                run_id,
                "answer_scoring",
                f"{case_id}:{current_metric}",
                config["model_name"],
                token_usage,
            )

        result: dict[str, Any] = {
            "status": "not_applicable",
            "score": None,
            "reason": None,
            "raw_response": None,
            "error": None,
            "usage": None,
            "model_name": config["model_name"],
            "prompt_version": config["prompt_version"],
            "criteria": config["criteria"][metric],
        }
        missing = applicability(metric, sample)
        if missing:
            result["reason"] = missing
        elif setup_error or client is None:
            result["status"] = "failed"
            result["error"] = setup_error or "model_unavailable"
        else:
            try:
                with business_span("answer.score") as span:
                    attributes(span, **{"metric": metric, "model.id": config["model_name"]})
                    try:
                        scored = evaluate_answer_metric(
                            client,
                            config["base_url"],
                            config["model_name"],
                            token,
                            config["timeout_seconds"],
                            metric,
                            config["criteria"][metric],
                            sample,
                            record_answer_call,
                        )
                    except Exception as exc:
                        fail(span, str(exc) if isinstance(exc, AnswerModelError) else "model_error")
                        raise
                    attributes(span, **{"status": "success"})
                    if scored.usage:
                        attributes(
                            span,
                            **{
                                "token.input": scored.usage["input_tokens"],
                                "token.output": scored.usage["output_tokens"],
                            },
                        )
                result.update(
                    {
                        "status": "success",
                        "score": scored.score,
                        "reason": scored.reason,
                        "raw_response": scored.raw_response,
                        "usage": scored.usage,
                    }
                )
            except AnswerModelError as exc:
                result["status"] = "failed"
                result["error"] = str(exc)
            except Exception as exc:
                result["status"] = "failed"
                result["error"] = f"model_error:{type(exc).__name__}"
        with business_span("answer.persist") as span:
            attributes(
                span,
                **{
                    "run.id": run_id,
                    "case.id": case_id,
                    "metric": metric,
                    "status": result["status"],
                },
            )
            if result["error"]:
                fail(span, result["error"])
            store.record_answer_metric(run_id, case_id, metric, result)
        statuses.append(result["status"])
    return statuses


def process_run(
    run_id: str,
    data_dir: Path,
    encoder_factory: EncoderFactory = FastEmbedEncoder,
    client_factory: ClientFactory = httpx.Client,
) -> None:
    store = RunStore(data_dir)
    usage_store = UsageStore(data_dir)
    traces = TraceStore(data_dir)
    if not store.claim(run_id):
        return
    config = store.config(run_id)
    mode = config.get("mode", "retrieval")
    encoder: Encoder | None = None
    cache: EmbeddingCache | None = None
    retrieval_setup_error: str | None = None
    reused_scores = store.reusable_retrieval_scores(run_id)
    needs_encoder = mode in {"retrieval", "both"} and any(
        case_id not in reused_scores for case_id in store.retrieval_case_ids(run_id)
    )
    if needs_encoder:
        try:
            model_path = Path(config["model_path"]) if config["model_path"] else None
            encoder = encoder_factory(
                config["model_name"], data_dir / "models", model_path, config["offline"]
            )
            store.set_model_id(run_id, encoder.model_id)
            cache = EmbeddingCache(data_dir)
            if reused_scores:
                source_id = config["reuse_retrieval_from_run_id"]
                if encoder.model_id != store.get_run(source_id)["model_id"]:
                    reused_scores = {}
        except Exception as exc:
            retrieval_setup_error = f"model_unavailable:{type(exc).__name__}"
    elif reused_scores:
        source_id = config["reuse_retrieval_from_run_id"]
        source_model_id = store.get_run(source_id)["model_id"]
        if source_model_id:
            store.set_model_id(run_id, source_model_id)

    with ExitStack() as stack:
        client: httpx.Client | None = None
        token: str | None = None
        answer_setup_error: str | None = None
        answer_config = config.get("answer")
        if answer_config:
            try:
                token = OnlineModelStore(data_dir).token(answer_config["judge_model_id"])
                client = stack.enter_context(client_factory())
            except Exception as exc:
                answer_setup_error = f"model_unavailable:{type(exc).__name__}"
        try:
            for case_id in store.pending_case_ids(run_id):

                def record_embedding_call(texts: list[str], current_case_id: str = case_id) -> None:
                    if encoder is not None:
                        token_usage = embedding_usage(texts)
                        attributes(
                            trace.get_current_span(),
                            **{
                                "token.input": token_usage["input_tokens"],
                            },
                        )
                        usage_store.record(
                            "run",
                            run_id,
                            "embedding",
                            current_case_id,
                            encoder.model_id,
                            token_usage,
                        )

                if store.cancellation_requested(run_id):
                    break
                case_span = tracer().start_span("run.case")
                trace_token = context.attach(trace.set_span_in_context(case_span))
                attributes(case_span, **{"run.id": run_id, "case.id": case_id})
                traces.record("run_case", f"{run_id}:{case_id}", case_span)
                start = monotonic()
                try:
                    item = store.input_for_case(run_id, case_id)
                    retrieval_status = "not_applicable"
                    retrieval_score = None
                    retrieval_error = retrieval_setup_error
                    if mode in {"retrieval", "both"}:
                        if case_id in reused_scores:
                            retrieval_status = "success"
                            retrieval_score = reused_scores[case_id]
                            retrieval_error = None
                        elif item["reference_chunks"] is None:
                            retrieval_status = "not_applicable"
                            retrieval_error = None
                        elif encoder is not None and cache is not None:
                            try:
                                retrieval_status, retrieval_score, retrieval_error = (
                                    _score_retrieval_case(
                                        item,
                                        config,
                                        encoder,
                                        cache,
                                        record_embedding_call,
                                    )
                                )
                            except Exception as exc:
                                retrieval_status = "failed"
                                retrieval_error = f"scoring_error:{type(exc).__name__}"
                        else:
                            retrieval_status = "failed"
                    answer_statuses = (
                        _score_answer_case(
                            store,
                            run_id,
                            case_id,
                            item,
                            answer_config,
                            client,
                            token,
                            answer_setup_error,
                            usage_store,
                        )
                        if answer_config
                        else []
                    )
                    status: CaseStatus
                    if retrieval_status == "success" or "success" in answer_statuses:
                        status = "success"
                    elif retrieval_status == "failed" or "failed" in answer_statuses:
                        status = "failed"
                    else:
                        status = "not_applicable"
                    with business_span("run.persist") as persist_span:
                        attributes(
                            persist_span, **{"run.id": run_id, "case.id": case_id, "status": status}
                        )
                        store.record_case(
                            run_id,
                            case_id,
                            status,
                            score=retrieval_score,
                            error=retrieval_error,
                            elapsed_ms=(monotonic() - start) * 1000,
                        )
                    attributes(
                        case_span, **{"status": status, "elapsed.ms": (monotonic() - start) * 1000}
                    )
                    if status == "failed":
                        fail(case_span, retrieval_error or "metric_failed")
                except Exception as exc:
                    fail(case_span, f"scoring_error:{type(exc).__name__}")
                    store.record_case(
                        run_id,
                        case_id,
                        "failed",
                        error=f"scoring_error:{type(exc).__name__}",
                        elapsed_ms=(monotonic() - start) * 1000,
                    )
                finally:
                    context.detach(trace_token)
                    case_span.end()
        except Exception as exc:
            store.fail_pending(run_id, f"worker_error:{type(exc).__name__}")
        finally:
            store.finish(run_id)
