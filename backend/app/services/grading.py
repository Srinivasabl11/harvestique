"""Produce quality grading (A/B/C) of a recorded harvest: AI photo proposal, farmer review, confirmed grade.

The confirmed grade becomes the lot's `expected_grade`, which pooling uses to match buyers' minimum grades and which
buyers see. It is the farmer's own indicative grade; the hub's measured quality check, made when produce is received,
decides acceptance, so a grading is locked once any produce of the harvest reached a hub.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import ConflictError, DomainValidationError, NotFoundError
from app.core.ratelimit import HourlyLimit
from app.domain import produce_grading as pg
from app.domain.crop_profiles import context_for
from app.models.crop import CropCycle
from app.models.intelligence import HarvestActual, InventoryLot, ProduceGrading
from app.providers.vision.produce import ProduceGrader
from app.repositories.intelligence import ActualRepository, PredictionRepository
from app.schemas.grading import GradeConfirmIn, GradingProposalOut, ProduceGradingOut
from app.schemas.pooling import LotUpdate
from app.services.media import decode_image

PROPOSAL_TEXT = {
    "en": {
        "rated": "Every check was rated from the photo. Review each one against your produce, change what is wrong, "
        "then confirm.",
        "partial": "The photo showed only some checks. Rate the open ones yourself: {checks}.",
        "low_confidence": "The AI was not sure about this photo, so it rated nothing. Take a clearer photo or rate the "
        "checks yourself.",
        "nothing_rated": "The AI could not rate any check from this photo. Take a clearer photo or rate the checks "
        "yourself.",
        "not_produce": "The photo does not seem to show harvested produce. Photograph the produce itself (a crate, "
        "heap or handful) in daylight.",
        "poor_photo": "The photo is too unclear to judge quality. Take a sharp photo in daylight.",
        "not_close_up": "The produce is too far away to see each piece. Take a closer photo.",
        "crop_mismatch": "The photo may not show {crop}. Check that it is the right produce.",
        "too_dark": "The photo is too dark. Take it in daylight.",
        "blurry": "The photo is blurred. Hold the phone steady and tap the produce to focus.",
        "no_ai": "The AI photo check is not available on this server. Rate the checks yourself.",
        "timeout": "The AI photo check took too long. Try again later, or rate the checks yourself.",
        "unavailable": "The AI photo check could not be reached. Try again later, or rate the checks yourself.",
        "busy": "The AI photo check is busy. Try again in a few minutes, or rate the checks yourself.",
        "invalid_response": "The AI gave an answer that could not be checked safely, so it was not used. Rate the "
        "checks yourself.",
    },
    "kn": {
        "rated": "ಫೋಟೋದಿಂದ ಎಲ್ಲಾ ಪರಿಶೀಲನೆಗಳಿಗೆ ಮಟ್ಟ ನೀಡಲಾಗಿದೆ. ನಿಮ್ಮ ಉತ್ಪನ್ನದೊಂದಿಗೆ ಹೋಲಿಸಿ, ತಪ್ಪಾದುದನ್ನು ಬದಲಿಸಿ, ನಂತರ ಖಚಿತಪಡಿಸಿ.",
        "partial": "ಫೋಟೋದಲ್ಲಿ ಕೆಲವು ಪರಿಶೀಲನೆಗಳು ಮಾತ್ರ ಕಂಡವು. ಉಳಿದವುಗಳಿಗೆ ನೀವೇ ಮಟ್ಟ ನೀಡಿ: {checks}.",
        "low_confidence": "AI ಗೆ ಈ ಫೋಟೋ ಬಗ್ಗೆ ಖಚಿತತೆ ಇರಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಯಾವುದಕ್ಕೂ ಮಟ್ಟ ನೀಡಿಲ್ಲ. ಸ್ಪಷ್ಟ ಫೋಟೋ ತೆಗೆಯಿರಿ ಅಥವಾ ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "nothing_rated": "ಈ ಫೋಟೋದಿಂದ AI ಯಾವುದೇ ಪರಿಶೀಲನೆಗೆ ಮಟ್ಟ ನೀಡಲು ಆಗಲಿಲ್ಲ. ಸ್ಪಷ್ಟ ಫೋಟೋ ತೆಗೆಯಿರಿ ಅಥವಾ ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "not_produce": "ಫೋಟೋದಲ್ಲಿ ಕೊಯ್ದ ಉತ್ಪನ್ನ ಕಾಣುತ್ತಿಲ್ಲ. ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ಉತ್ಪನ್ನದ (ಕ್ರೇಟ್, ರಾಶಿ ಅಥವಾ ಹಿಡಿ) ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "poor_photo": "ಗುಣಮಟ್ಟ ನಿರ್ಣಯಿಸಲು ಫೋಟೋ ಸ್ಪಷ್ಟವಾಗಿಲ್ಲ. ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ಸ್ಪಷ್ಟ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "not_close_up": "ಪ್ರತಿ ತುಂಡು ಕಾಣಲು ಉತ್ಪನ್ನ ತುಂಬಾ ದೂರದಲ್ಲಿದೆ. ಹತ್ತಿರದ ಫೋಟೋ ತೆಗೆಯಿರಿ.",
        "crop_mismatch": "ಫೋಟೋದಲ್ಲಿ {crop} ಇಲ್ಲದಿರಬಹುದು. ಸರಿಯಾದ ಉತ್ಪನ್ನವೇ ಎಂದು ಪರಿಶೀಲಿಸಿ.",
        "too_dark": "ಫೋಟೋ ತುಂಬಾ ಕತ್ತಲಾಗಿದೆ. ಹಗಲು ಬೆಳಕಿನಲ್ಲಿ ತೆಗೆಯಿರಿ.",
        "blurry": "ಫೋಟೋ ಮಸುಕಾಗಿದೆ. ಫೋನ್ ಅಲುಗಾಡದಂತೆ ಹಿಡಿದು ಉತ್ಪನ್ನದ ಮೇಲೆ ಟ್ಯಾಪ್ ಮಾಡಿ ಫೋಕಸ್ ಮಾಡಿ.",
        "no_ai": "ಈ ಸರ್ವರ್‌ನಲ್ಲಿ AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಲಭ್ಯವಿಲ್ಲ. ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "timeout": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ತುಂಬಾ ಸಮಯ ತೆಗೆದುಕೊಂಡಿತು. ನಂತರ ಪ್ರಯತ್ನಿಸಿ, ಅಥವಾ ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "unavailable": "AI ಫೋಟೋ ಪರಿಶೀಲನೆಯನ್ನು ತಲುಪಲು ಆಗಲಿಲ್ಲ. ನಂತರ ಪ್ರಯತ್ನಿಸಿ, ಅಥವಾ ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "busy": "AI ಫೋಟೋ ಪರಿಶೀಲನೆ ಕಾರ್ಯನಿರತವಾಗಿದೆ. ಕೆಲವು ನಿಮಿಷಗಳ ನಂತರ ಪ್ರಯತ್ನಿಸಿ, ಅಥವಾ ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
        "invalid_response": "AI ನೀಡಿದ ಉತ್ತರವನ್ನು ಸುರಕ್ಷಿತವಾಗಿ ಪರಿಶೀಲಿಸಲು ಆಗಲಿಲ್ಲ, ಆದ್ದರಿಂದ ಬಳಸಿಲ್ಲ. ನೀವೇ ಮಟ್ಟ ನೀಡಿ.",
    },
}
STATUS_TEXT = {
    "en": {
        "not_graded": "Not graded yet. Rate each check yourself, or start with a photo of the produce.",
        "needs_review": "An AI proposal is waiting for your review. Nothing is final until you confirm.",
        "graded": "Graded by you. Buyers see this grade for the lot; the hub's quality check decides acceptance.",
        "locked": "Produce from this harvest reached a collection hub, so the grade can no longer be changed; the "
        "hub's measured check now applies.",
        "downgrade_committed": "This lot already has {kg} kg committed to buyer orders. If an order needs a higher "
        "grade, tell the buyer before delivery: the hub rejects produce below the order's minimum grade.",
    },
    "kn": {
        "not_graded": "ಇನ್ನೂ ಗ್ರೇಡ್ ಮಾಡಿಲ್ಲ. ಪ್ರತಿ ಪರಿಶೀಲನೆಗೆ ನೀವೇ ಮಟ್ಟ ನೀಡಿ, ಅಥವಾ ಉತ್ಪನ್ನದ ಫೋಟೋದಿಂದ ಆರಂಭಿಸಿ.",
        "needs_review": "AI ಪ್ರಸ್ತಾವನೆ ನಿಮ್ಮ ಪರಿಶೀಲನೆಗಾಗಿ ಕಾಯುತ್ತಿದೆ. ನೀವು ಖಚಿತಪಡಿಸುವವರೆಗೆ ಏನೂ ಅಂತಿಮವಲ್ಲ.",
        "graded": "ನೀವು ಗ್ರೇಡ್ ಮಾಡಿದ್ದೀರಿ. ಖರೀದಿದಾರರು ಈ ಗ್ರೇಡ್ ನೋಡುತ್ತಾರೆ; ಸ್ವೀಕಾರವನ್ನು ಕೇಂದ್ರದ ಗುಣಮಟ್ಟ ಪರಿಶೀಲನೆ ನಿರ್ಧರಿಸುತ್ತದೆ.",
        "locked": "ಈ ಕೊಯ್ಲಿನ ಉತ್ಪನ್ನ ಸಂಗ್ರಹ ಕೇಂದ್ರ ತಲುಪಿದೆ, ಆದ್ದರಿಂದ ಗ್ರೇಡ್ ಬದಲಿಸಲು ಆಗುವುದಿಲ್ಲ; ಈಗ ಕೇಂದ್ರದ ಪರಿಶೀಲನೆ ಅನ್ವಯಿಸುತ್ತದೆ.",
        "downgrade_committed": "ಈ ಲಾಟ್‌ನಿಂದ ಈಗಾಗಲೇ {kg} ಕೆಜಿ ಖರೀದಿದಾರರ ಆರ್ಡರ್‌ಗಳಿಗೆ ಬದ್ಧವಾಗಿದೆ. ಆರ್ಡರ್‌ಗೆ ಹೆಚ್ಚಿನ ಗ್ರೇಡ್ ಬೇಕಿದ್ದರೆ, "
        "ಪೂರೈಕೆಗೆ ಮೊದಲು ಖರೀದಿದಾರರಿಗೆ ತಿಳಿಸಿ: ಕನಿಷ್ಠ ಗ್ರೇಡ್‌ಗಿಂತ ಕಡಿಮೆ ಉತ್ಪನ್ನವನ್ನು ಕೇಂದ್ರ ತಿರಸ್ಕರಿಸುತ್ತದೆ.",
    },
}


class GradingService:
    def __init__(
        self,
        *,
        session: Session,
        grader: ProduceGrader,
        update_lot: Any,  # PoolService.update_lot: re-offers a regraded lot to short pools
        clock: Clock,
        photo_limit: HourlyLimit | None = None,
    ) -> None:
        self._session = session
        self._grader = grader
        self._update_lot = update_lot
        self._clock = clock
        self._limit = photo_limit
        self._cycles = PredictionRepository(session)
        self._actuals = ActualRepository(session)

    # ------------------------------------------------------------------ API

    def get(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, language: str) -> ProduceGradingOut:
        cycle, actual = self._harvest(owner_id, cycle_id, lock=False)
        return self._out(cycle, actual, self._row(actual.id), language)

    def propose_from_photo(
        self, owner_id: uuid.UUID, cycle_id: uuid.UUID, data: bytes, language: str
    ) -> ProduceGradingOut:
        rgb = decode_image(data)  # 422 for anything that is not a safe JPEG / PNG / WebP
        cycle, actual = self._harvest(owner_id, cycle_id, lock=False)
        self._require_unlocked(actual)
        if self._limit is not None:
            self._limit.check(owner_id)
        crop = cycle.crop
        profile = pg.profile_for(self._group(cycle))
        context = context_for(
            crop.name,
            category=crop.category.value,
            group=crop.crop_group.value if crop.crop_group else None,
            local_name=crop.local_name,
            aliases=list(crop.aliases or []),
            scientific=crop.scientific_name,
        )
        # the model call can take a minute: no row lock is held meanwhile
        proposal = self._grader.propose(rgb, profile, context)
        cycle, actual = self._harvest(owner_id, cycle_id, lock=True)
        self._require_unlocked(actual)
        row = self._row(actual.id) or self._new_row(actual, owner_id, profile)
        grade, _ = pg.grade_for(row.profile, proposal.levels) if proposal.status == "proposed" else (None, [])
        row.proposal_status = proposal.status
        row.proposal_reason = proposal.reason
        row.proposed_levels = dict(proposal.levels)
        row.proposed_grade = grade
        row.proposal_details = {
            "confidence": proposal.confidence,
            "description": proposal.description,
            "produce_seen": proposal.produce_seen,
            "model": f"{proposal.model_name} {proposal.model_version}".strip(),
            "image_sha256": hashlib.sha256(data).hexdigest(),
        }
        row.proposed_at = self._clock.now()
        self._session.commit()
        return self._out(cycle, actual, row, language)

    def confirm(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, payload: GradeConfirmIn) -> ProduceGradingOut:
        cycle, actual = self._harvest(owner_id, cycle_id, lock=True)
        self._require_unlocked(actual)
        profile = pg.profile_for(self._group(cycle))
        try:
            levels = pg.clean_levels(profile, payload.levels)
        except ValueError as exc:
            raise DomainValidationError(str(exc), code="unknown_check", details={"field": "levels"}) from exc
        criteria_grade, missing = pg.grade_for(profile, levels)
        if criteria_grade is None:
            # no definitive grade without evidence for every check
            raise DomainValidationError(
                pg.missing_text(profile, missing, payload.language),
                code="checks_missing",
                details={"missing": missing},
            )
        grade = payload.grade or criteria_grade
        if pg.GRADE_RANK[grade] < pg.GRADE_RANK[criteria_grade]:
            raise DomainValidationError(
                f"Your ratings support grade {criteria_grade.value} at best. To give grade {grade.value}, change the "
                "ratings that are wrong.",
                code="grade_above_criteria",
                details={"criteria_grade": criteria_grade.value},
            )
        if grade != criteria_grade and payload.reason is None:
            raise DomainValidationError(
                f"Say why the grade is lower than the {criteria_grade.value} your ratings support.",
                code="reason_required",
                details={"field": "reason"},
            )
        row = self._row(actual.id) or self._new_row(actual, owner_id, profile)
        if row.profile != profile:  # the crop's group changed since the proposal: its ratings do not apply
            row.profile, row.proposed_levels, row.proposed_grade = profile, None, None
        proposed = row.proposed_levels or {}
        row.levels = levels
        row.criteria_grade = criteria_grade
        row.grade = grade
        row.grade_source = (
            "manual" if not proposed else "photo_corrected" if self._corrected(proposed, levels) else "photo_confirmed"
        )
        row.override_reason = payload.reason if grade != criteria_grade else None
        row.confirmed_at = self._clock.now()
        row.confirmed_by = owner_id
        row.criteria_version = pg.CRITERIA_VERSION
        self._session.flush()
        lot = self._cycles_lot(cycle.id)
        warnings: list[str] = []
        if lot is not None:
            before = lot.expected_grade
            if pg.GRADE_RANK[grade] > pg.GRADE_RANK[before] and lot.committed_kg > 0:
                warnings.append(
                    STATUS_TEXT[pg.lang_of(payload.language)]["downgrade_committed"].format(
                        kg=f"{lot.committed_kg.normalize():f}"
                    )
                )
            self._session.commit()
            if grade != before:
                self._update_lot(owner_id, lot.id, LotUpdate(expected_grade=grade))
        else:
            self._session.commit()
        out = self._out(cycle, actual, row, payload.language)
        out.warnings = warnings + out.warnings
        return out

    # ------------------------------------------------------------ internals

    def _harvest(self, owner_id: uuid.UUID, cycle_id: uuid.UUID, *, lock: bool) -> tuple[CropCycle, HarvestActual]:
        cycle = self._cycles.lock_cycle(cycle_id, owner_id) if lock else self._owned_cycle(owner_id, cycle_id)
        if cycle is None:
            raise NotFoundError("Crop cycle not found")
        actual = self._actuals.for_cycle(cycle.id)
        if actual is None:
            raise ConflictError(
                "Record the weighed harvest first; the grade belongs to a recorded harvest.",
                code="harvest_not_recorded",
            )
        return cycle, actual

    def _owned_cycle(self, owner_id: uuid.UUID, cycle_id: uuid.UUID) -> CropCycle | None:
        from app.models.farm import Farm, FarmPlot

        stmt = (
            select(CropCycle)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(CropCycle.id == cycle_id, Farm.owner_id == owner_id)
        )
        return self._session.scalar(stmt)

    def _require_unlocked(self, actual: HarvestActual) -> None:
        if self._actuals.batches_received(actual.id):
            raise ConflictError(
                "Produce from this harvest already reached a collection hub, so its grade can no longer be changed. "
                "The hub's measured quality check applies.",
                code="grading_locked",
            )

    def _row(self, actual_id: uuid.UUID) -> ProduceGrading | None:
        return self._session.scalar(select(ProduceGrading).where(ProduceGrading.harvest_actual_id == actual_id))

    def _new_row(self, actual: HarvestActual, owner_id: uuid.UUID, profile: str) -> ProduceGrading:
        row = ProduceGrading(
            harvest_actual_id=actual.id, owner_id=owner_id, profile=profile, criteria_version=pg.CRITERIA_VERSION
        )
        self._session.add(row)
        return row

    def _cycles_lot(self, cycle_id: uuid.UUID) -> InventoryLot | None:
        return self._session.scalar(select(InventoryLot).where(InventoryLot.crop_cycle_id == cycle_id))

    @staticmethod
    def _group(cycle: CropCycle) -> str:
        from app.domain.crop_catalog import group_and_part

        crop = cycle.crop
        return group_and_part(crop.name, crop.category.value, crop.crop_group.value if crop.crop_group else None)[0]

    @staticmethod
    def _corrected(proposed: dict[str, Any], levels: dict[str, int]) -> bool:
        return any(k in levels and levels[k] != v for k, v in proposed.items())

    def _proposal_out(self, row: ProduceGrading, crop_name: str, language: str) -> GradingProposalOut | None:
        if row.proposal_status is None or row.proposed_at is None:
            return None
        lang = pg.lang_of(language)
        levels = {k: int(v) for k, v in (row.proposed_levels or {}).items()}
        open_checks = [a.id for a in pg.attributes(row.profile) if a.id not in levels]
        reason = row.proposal_reason or "unavailable"
        titles = {a.id: a.title[lang] for a in pg.attributes(row.profile)}
        template = PROPOSAL_TEXT[lang].get(reason, PROPOSAL_TEXT[lang]["unavailable"])
        details = row.proposal_details or {}
        return GradingProposalOut(
            status=row.proposal_status,
            reason=reason,
            message=template.format(checks=", ".join(titles[c] for c in open_checks), crop=crop_name),
            levels=levels,
            open_checks=open_checks if row.proposal_status in ("proposed", "needs_more_evidence") else [],
            proposed_grade=row.proposed_grade,
            confidence=details.get("confidence"),
            description=str(details.get("description") or ""),
            model=str(details.get("model") or ""),
            proposed_at=row.proposed_at,
        )

    def _out(
        self, cycle: CropCycle, actual: HarvestActual, row: ProduceGrading | None, language: str
    ) -> ProduceGradingOut:
        lang = pg.lang_of(language)
        profile = row.profile if row is not None else pg.profile_for(self._group(cycle))
        locked = bool(self._actuals.batches_received(actual.id))
        lot = self._cycles_lot(cycle.id)
        if row is not None and row.grade is not None:
            status = "graded"
        elif row is not None and row.proposal_status in ("proposed", "needs_more_evidence"):
            status = "needs_review"
        else:
            status = "not_graded"
        warnings = [STATUS_TEXT[lang]["locked"]] if locked else []
        proposed = (row.proposed_levels or {}) if row is not None else {}
        levels = {k: int(v) for k, v in (row.levels or {}).items()} if row is not None and row.levels else None
        return ProduceGradingOut(
            crop_cycle_id=cycle.id,
            harvest_actual_id=actual.id,
            crop_name=cycle.crop.name,
            harvested_kg=float(actual.quantity_kg),
            status=status,
            status_text=STATUS_TEXT[lang][status],
            criteria=pg.criteria(profile, lang),
            proposal=self._proposal_out(row, cycle.crop.name, lang) if row is not None else None,
            levels=levels,
            criteria_grade=row.criteria_grade if row is not None else None,
            grade=row.grade if row is not None else None,
            grade_text=pg.grade_text(row.grade, lang) if row is not None and row.grade is not None else None,
            grade_source=row.grade_source if row is not None else None,
            corrected_checks=sorted(k for k, v in proposed.items() if levels and k in levels and levels[k] != v),
            override_reason=row.override_reason if row is not None else None,
            confirmed_at=row.confirmed_at if row is not None else None,
            locked=locked,
            lot_expected_grade=lot.expected_grade if lot is not None else None,
            warnings=warnings,
        )
