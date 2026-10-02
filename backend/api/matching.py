"""Preview local chunk similarity without external model calls."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.adapters.local_embeddings import EmbeddingCache, FastEmbedEncoder, ModelUnavailable
from backend.config import Settings
from backend.domain.matching import candidate_pairs, relevant_texts
from backend.domain.retrieval_scoring import score_retrieval


class ChunkInput(BaseModel):
    text: str = Field(min_length=1)
    document_id: str = Field(min_length=1)


class PreviewRequest(BaseModel):
    model_name: str = Field(default="BAAI/bge-small-zh-v1.5", min_length=1)
    model_path: str | None = None
    offline: bool = False
    threshold: float = Field(default=0.8, ge=-1, le=1)
    reference_chunks: list[ChunkInput] = Field(min_length=1, max_length=100)
    predicted_chunks: list[ChunkInput] = Field(min_length=1, max_length=100)


class CandidateResponse(BaseModel):
    reference_index: int
    predicted_index: int
    similarity: float | None
    candidate: bool
    reason: str


class SelectedMatchResponse(BaseModel):
    predicted_index: int
    reference_index: int
    similarity: float


class EdgeDecisionResponse(BaseModel):
    reference_index: int
    predicted_index: int
    similarity: float | None
    candidate: bool
    selected: bool
    reason: str


class KScoreResponse(BaseModel):
    k: int
    precision: float
    ap: float
    ndcg: float
    matches: list[SelectedMatchResponse]
    decisions: list[EdgeDecisionResponse]


class PreviewResponse(BaseModel):
    model_id: str
    threshold: float
    pairs: list[CandidateResponse]
    match_rule_version: str
    gain_rule_version: str
    scores: list[KScoreResponse]


def create_matching_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api/v1/matching", tags=["matching"])
    cache = EmbeddingCache(settings.data_dir)

    @router.post("/preview", response_model=PreviewResponse)
    def preview(request: PreviewRequest) -> PreviewResponse:
        try:
            encoder = FastEmbedEncoder(
                request.model_name,
                settings.data_dir / "models",
                Path(request.model_path).expanduser().resolve() if request.model_path else None,
                request.offline,
            )
            vectors = cache.vectors(
                encoder, relevant_texts(request.reference_chunks, request.predicted_chunks)
            )
            pairs = candidate_pairs(
                request.reference_chunks, request.predicted_chunks, vectors, request.threshold
            )
            scoring = score_retrieval(
                request.reference_chunks,
                request.predicted_chunks,
                pairs,
                encoder.model_id,
                request.threshold,
            )
        except (ModelUnavailable, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PreviewResponse(
            model_id=encoder.model_id,
            threshold=request.threshold,
            pairs=[CandidateResponse(**vars(pair)) for pair in pairs],
            match_rule_version=scoring.match_rule_version,
            gain_rule_version=scoring.gain_rule_version,
            scores=[
                KScoreResponse(
                    k=item.k,
                    precision=item.precision,
                    ap=item.ap,
                    ndcg=item.ndcg,
                    matches=[SelectedMatchResponse(**vars(match)) for match in item.matches],
                    decisions=[EdgeDecisionResponse(**vars(edge)) for edge in item.decisions],
                )
                for item in scoring.scores.values()
            ],
        )

    return router
