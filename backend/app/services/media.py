"""Crop-health photo analysis and voice: safe file validation, then provider calls.

Images: size limit, magic-byte check (JPEG / PNG / WebP only, whatever the declared type), Pillow decode with a
pixel limit (decompression-bomb guard), verify(), single frame only, dimension limits, re-decode to RGB, downscale.
Only the SHA-256 and the advisory result are stored; the photo itself is not kept.
Audio: size limit and magic-byte check (WAV, OGG/Opus, FLAC, MP4/M4A, WebM) before any provider sees it.
"""

from __future__ import annotations

import hashlib
import io
import uuid
import warnings

import numpy as np
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainValidationError, NotFoundError
from app.domain.crop_catalog import group_and_part
from app.domain.crop_health_report import build_report
from app.domain.crop_health_validation import MIN_PER_CLASS, MIN_RECALL, validation_for
from app.domain.crop_profiles import context_for
from app.models.crop import Crop, CropCycle
from app.models.engagement import CropHealthAnalysis
from app.models.farm import Farm, FarmPlot
from app.providers.speech.base import Language, SpeechAudio, SpeechToTextProvider, TextToSpeechProvider
from app.providers.vision.base import CropHealthClassifier, measurement_text
from app.repositories.engagement import EngagementRepository
from app.schemas.assistant import CropHealthOut, CropValidationOut, CropValidationReport, TranscriptOut

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
MIN_SIDE, MAX_SIDE = 64, 8000
ANALYSIS_SIDE = 768  # the vision model needs detail; the colour heuristic downsizes further itself
MAX_AUDIO_BYTES = 2 * 1024 * 1024
HEURISTIC_DISCLAIMER = (
    "Colour measurements only, from a simple analysis that has NOT been validated on labelled crop images; it gives "
    "no health label. It is not a diagnosis. Confirm with an agriculture officer before spraying or treating."
)
VISION_DISCLAIMER = (
    "Advisory result from a general-purpose AI vision model running on the Harvestique server. It describes what it "
    "sees but is NOT a validated plant-disease classifier and can be wrong. It is not a diagnosis. Confirm with an "
    "agriculture officer before spraying or treating."
)


def image_kind(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def audio_kind(data: bytes) -> str | None:
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if data[:4] == b"OggS":
        return "audio/ogg"
    if data[:4] == b"fLaC":
        return "audio/flac"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "audio/webm"
    return None


def decode_image(data: bytes) -> np.ndarray:
    """Validate and decode an uploaded photo into an RGB array no larger than ANALYSIS_SIDE. Raises 422."""
    if not data:
        raise DomainValidationError("The file is empty", code="empty_file")
    if len(data) > MAX_IMAGE_BYTES:
        raise DomainValidationError("The photo is larger than 5 MB", code="file_too_large")
    kind = image_kind(data)
    if kind is None:
        raise DomainValidationError("Only JPEG, PNG or WebP photos are accepted", code="unsupported_file_type")
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                if probe.format != kind:
                    raise DomainValidationError(
                        "The file content does not match its image type", code="unsupported_file_type"
                    )
                if getattr(probe, "n_frames", 1) != 1:
                    raise DomainValidationError("Animated images are not accepted", code="unsupported_file_type")
                w, h = probe.size
                if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE:
                    raise DomainValidationError(
                        f"Photo sides must be between {MIN_SIDE} and {MAX_SIDE} pixels", code="bad_dimensions"
                    )
                probe.verify()
            with Image.open(io.BytesIO(data)) as img:
                rgb = img.convert("RGB")
                rgb.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE))
                return np.asarray(rgb, dtype=np.uint8)
    except DomainValidationError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise DomainValidationError("The photo could not be read safely", code="invalid_image") from exc


class CropHealthService:
    def __init__(self, *, session: Session, repo: EngagementRepository, classifier: CropHealthClassifier) -> None:
        self._session = session
        self._repo = repo
        self._classifier = classifier

    def analyze(
        self,
        owner_id: uuid.UUID,
        data: bytes,
        cycle_id: uuid.UUID | None,
        language: str,
        crop_id: uuid.UUID | None = None,
    ) -> CropHealthOut:
        crop: Crop | None = None
        if cycle_id is not None:
            crop = self._require_cycle(owner_id, cycle_id).crop
        elif crop_id is not None:
            crop = self._session.get(Crop, crop_id)
            if crop is None or not crop.is_active:
                raise NotFoundError("Crop not found")
        context = (
            context_for(
                crop.name,
                category=crop.category.value,
                group=crop.crop_group.value if crop.crop_group else None,
                local_name=crop.local_name,
                aliases=list(crop.aliases or []),
                scientific=crop.scientific_name,
            )
            if crop is not None
            else None
        )
        rgb = decode_image(data)
        result = self._classifier.assess(rgb, language, context)
        validation = validation_for(crop.name) if crop is not None else None
        row = CropHealthAnalysis(
            owner_id=owner_id,
            crop_cycle_id=cycle_id,
            image_sha256=hashlib.sha256(data).hexdigest(),
            width=int(rgb.shape[1]),
            height=int(rgb.shape[0]),
            label=result.label,
            probabilities=result.probabilities,
            features={
                **result.features,
                "quality_flags": result.quality_flags,
                **({"validation": validation} if validation is not None else {}),
                # structured, evidence-based report with the visual condition score (or why it is withheld)
                "analysis": build_report(result, language, validation, crop.name if crop else None),
            },
            model_name=result.model_name or self._classifier.name,
            model_version=result.model_version or self._classifier.version,
        )
        self._repo.add(row)
        self._session.commit()
        return self._out(row, result.explanation, result.advice)

    def history(self, owner_id: uuid.UUID, cycle_id: uuid.UUID | None) -> list[CropHealthOut]:
        if cycle_id is not None:
            self._require_cycle(owner_id, cycle_id)
        from app.domain.vision import TEXT

        out = []
        for r in self._repo.analyses(owner_id, cycle_id, limit=50):
            explanation, advice = TEXT["en"][r.label]
            if r.features.get("mode") == "measurements_only":
                explanation, advice = measurement_text(r.features, r.features.get("quality_flags", []), "en")
            if r.features.get("ai_description"):
                explanation = f"{explanation}\nWhat the AI saw (may be wrong): {r.features['ai_description']}"
            out.append(self._out(r, explanation, advice))
        return out

    def validation_report(self) -> CropValidationReport:
        """Every active catalogue crop with its group, main part and measured validation status."""
        crops = self._session.scalars(select(Crop).where(Crop.is_active.is_(True)).order_by(Crop.name)).all()
        out = []
        for c in crops:
            group, part = group_and_part(c.name, c.category.value, c.crop_group.value if c.crop_group else None)
            out.append(
                CropValidationOut(
                    crop_id=c.id,
                    name=c.name,
                    local_name=c.local_name,
                    crop_group=group,
                    main_part=part,
                    validation=validation_for(c.name),
                )
            )
        verdicts = [str(o.validation["verdict"]) for o in out]
        summary = {
            "catalogue_crops": len(out),
            "health_evaluated": sum(bool(o.validation["health_evaluation_completed"]) for o in out),
            "identification_tested": sum(bool(o.validation["crop_identification_tested"]) for o in out),
            "reliable": verdicts.count("reliable"),
            "not_reliable": verdicts.count("not_reliable"),
            "insufficient_evidence": verdicts.count("insufficient_evidence"),
        }
        rule = (
            f"'reliable' needs at least {MIN_PER_CLASS} labelled field photos per class (healthy and problem) and "
            f"both recalls at least {MIN_RECALL:.0%}. Every crop can be photographed; coverage is not accuracy."
        )
        return CropValidationReport(crops=out, summary=summary, rule=rule)

    def _out(self, row: CropHealthAnalysis, explanation: str, advice: str) -> CropHealthOut:
        features = dict(row.features)
        flags = list(features.pop("quality_flags", []))
        return CropHealthOut(
            disclaimer=VISION_DISCLAIMER if row.model_name == "ollama-vision" else HEURISTIC_DISCLAIMER,
            id=row.id,
            crop_cycle_id=row.crop_cycle_id,
            label=row.label,
            probabilities=row.probabilities,
            features=features,
            quality_flags=flags,
            explanation=explanation,
            advice=advice,
            model_name=row.model_name,
            model_version=row.model_version,
            created_at=row.created_at,
        )

    def _require_cycle(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> CropCycle:
        cycle = self._session.get(CropCycle, cycle_id)
        plot = self._session.get(FarmPlot, cycle.plot_id) if cycle else None
        farm = self._session.get(Farm, plot.farm_id) if plot else None
        if cycle is None or farm is None or farm.owner_id != owner_id:
            raise NotFoundError("Crop cycle not found")
        return cycle


class SpeechService:
    def __init__(self, *, stt: SpeechToTextProvider, tts: TextToSpeechProvider) -> None:
        self._stt = stt
        self._tts = tts

    def transcribe(self, data: bytes, language: Language) -> TranscriptOut:
        if not data:
            raise DomainValidationError("The recording is empty", code="empty_file")
        if len(data) > MAX_AUDIO_BYTES:
            raise DomainValidationError("The recording is larger than 2 MB", code="file_too_large")
        media = audio_kind(data)
        if media is None:
            raise DomainValidationError(
                "Unsupported audio format (use WAV, OGG, FLAC, M4A or WebM)", code="unsupported_file_type"
            )
        t = self._stt.transcribe(data, media, language)
        return TranscriptOut(text=t.text, language=t.language, provider=t.provider)

    def speak(self, text: str, language: Language) -> SpeechAudio:
        return self._tts.synthesize(text, language)
