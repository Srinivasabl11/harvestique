"""AI Farm Assistant: controlled, user-scoped tools over existing services.

Safety properties (each is tested):
* only the tools below exist; each lists the roles allowed to call it and validates its arguments;
* every tool calls an existing service with the CALLER's user id, so it can only see the caller's data;
* no tool reads or writes pools, orders, allocations or inventory reservations; the assistant cannot decide or
  change allocation quantities (such requests are refused);
* the write tools (`create_reminder`, `record_expense`) run only on an explicit confirmation call, never from chat
  directly: chat only PROPOSES them;
* answers about the farmer's data are built from tool results by templates. A local LLM (Ollama), when available, may
  (a) pick a tool when the keyword rules do not understand a question - only a read-only tool from the caller's
  allowed list is accepted; (b) give a short, labelled GENERAL answer that contains no numbers and no farm data;
  (c) optionally reword a tool answer, used only if every number in it appears in the tool results (grounding).
* follow-up questions use the earlier turns the app sends back; the server keeps no chat memory.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select

from app.core.clock import Clock
from app.core.enums import (
    DataKind,
    EstimateBasis,
    ExpenseCategory,
    ParticipationStatus,
    ReminderStatus,
    ReminderType,
    UserRole,
    WeatherStatus,
)
from app.core.errors import AppError, ConflictError, DomainValidationError, NotFoundError, PermissionDeniedError
from app.domain.assistant.estimate import Inputs, conversation_inputs, has_numbers, inr
from app.domain.assistant.grounding import grounded
from app.domain.assistant.intents import (
    KANNADA,
    PERSONAL,
    Intent,
    Recognised,
    expense_summary_slots,
    is_follow_up,
    local_due,
    normalise,
    question_scope,
    recognise,
)
from app.domain.assistant.kannada import english_question, gloss
from app.domain.assistant.templates import (
    CATEGORY_KN,
    DISCLAIMER,
    GENERAL_AI_DISCLAIMER,
    GENERAL_IN_ENGLISH_KN,
    MIXED_DISCLAIMER,
    render,
    screen_name,
)
from app.domain.crop_catalog import group_and_part
from app.domain.market import PriceQuote
from app.models.crop import Crop, CropCycle
from app.models.farm import Farm, FarmPlot
from app.models.farm_records import FarmExpense
from app.models.planning import CropPlan, CropPlanItem
from app.providers.llm.base import LLMMessage, LLMProvider, LLMRequest
from app.repositories.engagement import EngagementRepository
from app.schemas.assistant import (
    AssistantRequest,
    AssistantResponse,
    ProposedAction,
    SourceRef,
    ToolCallOut,
    ToolInfo,
    ToolRequest,
    ToolResultOut,
)
from app.schemas.auth import CurrentUser
from app.schemas.engagement import ReminderCreate
from app.schemas.farm_records import ExpenseCreate
from app.schemas.planning import CalcItem, CalcRequest, CostIn, PriceRangeIn, YieldRangeIn
from app.services.crop_plans import CropPlanService
from app.services.engagement import ReminderService
from app.services.farm_records import ExpenseService
from app.services.farms import FarmService
from app.services.inventory import InventoryService
from app.services.market_prices import MarketPriceService
from app.services.marketplace import MarketplaceService
from app.services.planning import PlanningService
from app.services.predictions import PredictionService
from app.services.weather import WeatherService

logger = logging.getLogger(__name__)
FARMER, BUYER, ADMIN = UserRole.FARMER, UserRole.BUYER, UserRole.ADMIN
INTENT_TOOL = {
    Intent.WEATHER: "weather_summary",
    Intent.HARVEST_PREDICTION: "harvest_prediction",
    Intent.FARM_RISK: "farm_risk",
    Intent.REMINDERS_LIST: "list_reminders",
    Intent.INVENTORY: "inventory_summary",
    Intent.BUYER_OPPORTUNITIES: "buyer_opportunities",
    Intent.SUPPLY_REQUESTS: "my_supply_requests",
    Intent.MY_ORDERS: "my_orders",
    Intent.MARKET_SUPPLY: "market_supply",
    Intent.INCOME_PLANS: "income_plans",
    Intent.EXPENSE_SUMMARY: "expense_summary",
    Intent.FARM_SUMMARY: "farm_summary",
}
TOOL_INTENT = {tool: intent for intent, tool in INTENT_TOOL.items()}
# a follow-up ("and tomorrow?", "what about ragi?") repeats one of these with the new details
FOLLOWABLE = frozenset(INTENT_TOOL)
PERIOD_EN = {
    "this_month": " this month",
    "last_month": " last month",
    "this_year": " this year",
    "all": " in total",
}
# screens each account type has (keys match the app's allowlist); anything else is refused, never guessed
NAV_FOR_ROLE: dict[UserRole, frozenset[str]] = {
    UserRole.FARMER: frozenset(
        {"back", "home", "my_farm", "market", "harvest", "reminders", "crop_health", "planning", "notifications"}
    ),
    UserRole.BUYER: frozenset({"back", "home", "market", "demands", "orders", "reminders", "notifications"}),
    UserRole.ADMIN: frozenset({"back", "notifications"}),
}
PERIOD_KN = {"this_month": " ಈ ತಿಂಗಳು", "last_month": " ಕಳೆದ ತಿಂಗಳು", "this_year": " ಈ ವರ್ಷ"}


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FarmArgs(_Args):
    farm_id: uuid.UUID | None = None


class WeatherArgs(FarmArgs):
    day: Literal["today", "tomorrow"] | None = None


class CycleArgs(_Args):
    crop_cycle_id: uuid.UUID | None = None


class NoArgs(_Args):
    pass


class ExpenseArgs(_Args):
    farm_id: uuid.UUID | None = None
    crop_cycle_id: uuid.UUID | None = None
    category: ExpenseCategory | None = None
    date_from: date | None = None
    date_to: date | None = None


class RecordExpenseArgs(ExpenseCreate):
    """record_expense: an expense on one of the caller's farms (the expense service checks ownership and dates)."""

    farm_id: uuid.UUID


@dataclass
class Facts:
    """A tool's result: what to say (template key + values), the raw data and where it came from."""

    key: str
    values: dict[str, Any]
    data: Any
    sources: list[SourceRef] = field(default_factory=list)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    roles: frozenset[UserRole]
    args: type[BaseModel]
    run: Callable[[CurrentUser, Any, str], Facts]
    writes: bool = False


class AssistantService:
    def __init__(
        self,
        *,
        clock: Clock,
        llm: LLMProvider,
        farms: FarmService,
        weather: WeatherService,
        predictions: PredictionService,
        inventory: InventoryService,
        reminders: ReminderService,
        marketplace: MarketplaceService,
        plans: CropPlanService,
        engagement_repo: EngagementRepository,
        expenses: ExpenseService,
        llm_intents: bool = True,
        llm_general_answers: bool = True,
        llm_general_answers_kannada: bool = False,
        llm_rewording: bool = False,
        planning: PlanningService | None = None,
        market_prices: MarketPriceService | None = None,
    ) -> None:
        self._clock = clock
        self._llm = llm
        self._farms = farms
        self._weather = weather
        self._predictions = predictions
        self._inventory = inventory
        self._reminders = reminders
        self._market = marketplace
        self._plans = plans
        self._repo = engagement_repo
        self._expenses = expenses
        self._llm_intents = llm_intents
        self._llm_general = llm_general_answers
        self._llm_general_kn = llm_general_answers_kannada
        self._llm_reword = llm_rewording
        self._planning = planning or PlanningService()  # stateless calculator
        self._market_prices = market_prices  # AGMARKNET prices (None: farmers are asked for a price)
        self.tools: dict[str, Tool] = {t.name: t for t in self._registry()}

    # ================================================================ public
    def list_tools(self, user: CurrentUser) -> list[ToolInfo]:
        return [
            ToolInfo(name=t.name, description=t.description, writes=t.writes, roles=sorted(r.value for r in t.roles))
            for t in self.tools.values()
            if user.role in t.roles
        ]

    def voice_chat(self, user: CurrentUser, req: AssistantRequest) -> AssistantResponse:
        """A spoken question: the reply also carries the transcript as the server read it (shown in the app's
        "Voice details", so a wrong answer can be traced to the recogniser or to the server)."""
        reply = self.chat(user, req, voice=True)
        return reply.model_copy(update={"normalised": normalise(reply.heard or req.message)})

    def chat(self, user: CurrentUser, req: AssistantRequest, *, voice: bool = False) -> AssistantResponse:
        """Understand one question (rules, then the previous turn, then the local model), run at most one read-only
        tool or propose one confirmed write, and answer from the result. Voice uses the same path and the same
        confirmations as typed questions."""
        today = self._clock.now().date()
        rec = recognise(req.message, req.language, today=today)
        understood: Literal["rules", "alternative", "context", "local_model"] = "rules"
        heard: str | None = None
        if rec.intent is Intent.UNKNOWN:
            # the phone's recogniser offers other readings of the same speech; a clear rule match on one of them is
            # safer than letting a model guess what a misheard first transcript meant
            for alt in req.alternatives:
                alt_rec = recognise(alt, req.language, today=today)
                if alt_rec.intent is not Intent.UNKNOWN:
                    rec, understood, heard = alt_rec, "alternative", alt
                    req = req.model_copy(update={"message": alt})
                    break
        lang = rec.language
        if rec.intent is Intent.NAVIGATE:
            return self._navigate(user, rec, lang, understood, heard)
        if rec.intent is Intent.INCOME_PLANS and not PLAN_WORDS.search(req.message) and self._find_crop(req.message):
            rec = Recognised(Intent.CROP_ESTIMATE, 0.8, lang, "crop_named")
        # "for example 20 kg and ₹50,000" after an estimate is part of that estimate, not a new question (it was
        # answered by the general model with invented figures, or sent to past expenses for "ಖರ್ಚು")
        if (
            rec.intent in ESTIMATE_FOLLOW_UPS
            and self._previous_intent(req) is Intent.CROP_ESTIMATE
            and (rec.intent is Intent.CROP_ESTIMATE or has_numbers(req.message) or self._find_crop(req.message))
        ):
            rec, understood = Recognised(Intent.CROP_ESTIMATE, 0.8, lang, "context"), "context"
        previous = self._previous_intent(req)
        if rec.intent is Intent.CROP_STATEMENT and previous in (
            Intent.CROP_ESTIMATE,
            Intent.CROP_SUITABILITY,
            Intent.CROP_RECOMMENDATION,
        ):
            # "I am growing mango" right after a question that needed a crop answers THAT question; it must not
            # start over (it used to get "sorry, I did not understand" again)
            rec, understood = Recognised(previous, 0.8, lang, "context"), "context"
        elif (
            previous is Intent.CROP_RECOMMENDATION
            and rec.intent in (Intent.UNKNOWN, Intent.CROP_STATEMENT)
            and (soil_and_water(req.message) != (None, None))
        ):
            rec, understood = Recognised(Intent.CROP_RECOMMENDATION, 0.8, lang, "context"), "context"
        if rec.intent in (Intent.CROP_STATEMENT, Intent.CROP_RECOMMENDATION):
            if user.role is not FARMER:
                return self._reply(rec, lang, render("not_for_role", lang), understood=understood, heard=heard)
            if rec.intent is Intent.CROP_STATEMENT:
                return self._crop_statement(user, req, rec, lang, understood, heard)
            return self._recommend(user, req, rec, lang, understood, heard)
        if rec.intent in (Intent.CROP_ESTIMATE, Intent.CROP_SUITABILITY):
            if user.role is not FARMER:
                return self._reply(rec, lang, render("not_for_role", lang), understood=understood, heard=heard)
            if rec.intent is Intent.CROP_ESTIMATE:
                return self._estimate(user, req, rec, lang, understood, heard)
            return self._suitability(user, req, rec, lang, understood, heard)
        context: dict[str, Any] = {"farm_id": req.farm_id, "crop_cycle_id": req.crop_cycle_id}
        mentioned = self._mentions(user, req.message)
        for k, v in mentioned.items():
            if context.get(k) is None:
                context[k] = v
        scope = question_scope(req.message)
        general = False
        ai_ready = self._llm_general and self._llm.is_available()
        if rec.intent is Intent.UNKNOWN:
            previous = self._previous_intent(req)
            if previous in FOLLOWABLE and (is_follow_up(req.message) or mentioned):
                assert previous is not None
                rec, understood = self._follow_up(previous, req.message, lang, today), "context"
            elif lang == "kn":
                # the small local model routes Kannada unreliably (it picked unrelated tools): about the asker's own
                # records -> ask back in Kannada; anything else -> labelled general answer
                general = ai_ready and not PERSONAL.search(req.message)
            elif self._llm_intents and self._llm.is_available():
                picked = self._llm_pick(user, req)
                if isinstance(picked, Intent):
                    rec, understood = self._follow_up(picked, req.message, lang, today), "local_model"
                else:  # "general", "none" or no usable answer: answer it as a general question
                    general = ai_ready
        elif rec.intent in INTENT_TOOL and scope == "general" and not mentioned and ai_ready:
            # "what is a rain shadow?" mentions rain but is not about the asker's farm: no tool, no records
            rec, general = Recognised(Intent.GENERAL, 0.6, lang, "general_form"), True
        elif rec.intent is Intent.CROP_HEALTH_HELP and ai_ready:
            general = True  # general advice about the symptom, plus how to check their own crop with a photo

        calls: list[ToolCallOut] = []
        proposed: ProposedAction | None = None
        tool_name = INTENT_TOOL.get(rec.intent)
        if rec.intent in (Intent.BUYER_OPPORTUNITIES, Intent.MARKET_SUPPLY) and user.role is BUYER:
            tool_name = "market_supply"
        if rec.intent in (Intent.SUPPLY_REQUESTS, Intent.MY_ORDERS) and user.role is BUYER:
            tool_name = "my_orders"
        facts: Facts
        answer_kind: Literal["records", "general_ai", "mixed", "guidance"] = "guidance"
        reply_lang = lang
        disclaimer = DISCLAIMER[lang]
        if tool_name is not None:
            tool = self.tools[tool_name]
            args = {k: v for k, v in context.items() if k in tool.args.model_fields and v is not None}
            if rec.intent is Intent.EXPENSE_SUMMARY:
                args.update(self._expense_slot_args(rec))
            if rec.intent is Intent.WEATHER and (day := weather_day(req.message)) is not None:
                args["day"] = day
            facts, call = self._safe_run(user, tool, args, lang)
            calls.append(call)
            answer_kind = "records" if call.ok else "guidance"
            answer = render(facts.key, lang, **facts.values)
            llm_used = False
            if answer_kind == "records":
                answer, llm_used = self._maybe_reword(answer, facts, lang)
            advice = self._general_answer(req, "en") if call.ok and scope == "mixed" and ai_ready else None
            if advice is not None and advice != UNCLEAR:
                # "how can I reduce MY fertilizer costs?": the records answer first, then labelled general advice
                label = (
                    "ಸಾಮಾನ್ಯ ಸಲಹೆ (AI, ನಿಮ್ಮ ದಾಖಲೆಗಳಿಂದ ಅಲ್ಲ; ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ)"
                    if lang == "kn"
                    else ("General advice (AI, not from your records)")
                )
                answer = f"{answer}\n\n{label}: {advice}"
                answer_kind, llm_used, disclaimer = "mixed", True, MIXED_DISCLAIMER[lang]
                facts.sources = [*facts.sources, *self._ai_source()]
        else:
            llm_used = False
            if rec.intent is Intent.REMINDER_CREATE:
                facts, proposed = self._propose_reminder(rec, lang, req)
            elif rec.intent is Intent.EXPENSE_RECORD:
                facts, proposed = self._propose_expense(user, rec, lang, context)
            elif general and (text := self._general_answer(req, lang)) == UNCLEAR:
                facts = Facts("unclear", {}, None)  # garbled or fragmentary text: ask again, never guess
            elif general and text is not None:
                if rec.intent is Intent.CROP_HEALTH_HELP:
                    text = f"{text}\n\n{render('crop_health', 'en')}"
                facts, answer_kind, llm_used = (
                    Facts("general_ai", {"text": text}, None, self._ai_source()),
                    "general_ai",
                    True,
                )
                if lang == "kn" and not self._llm_general_kn:
                    reply_lang, disclaimer = "en", GENERAL_IN_ENGLISH_KN  # small local models write garbled Kannada
                else:
                    disclaimer = GENERAL_AI_DISCLAIMER[lang]
            else:
                key = {
                    Intent.CROP_HEALTH_HELP: "crop_health",
                    Intent.ALLOCATION_REQUEST: "allocation_refused",
                    Intent.HELP: "help",
                }.get(rec.intent, "unknown")
                if key == "unknown" and not self._llm.is_available():
                    key = "unknown_no_ai"  # general questions need the local model, which is not running
                facts = Facts(key, {}, None)
            answer = facts.values["text"] if facts.key == "general_ai" else render(facts.key, lang, **facts.values)
        return AssistantResponse(
            language="kn" if reply_lang == "kn" else "en",
            intent=rec.intent.value,
            confidence=rec.confidence,
            answer=answer,
            requires_confirmation=proposed is not None,
            proposed_action=proposed,
            tool_calls=calls,
            sources=facts.sources,
            disclaimer=disclaimer,
            llm_used=llm_used,
            understood_by=understood,
            answer_kind=answer_kind,
            heard=heard,
        )

    def _navigate(
        self,
        user: CurrentUser,
        rec: Recognised,
        lang: str,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
    ) -> AssistantResponse:
        target = str(rec.slots.get("target"))
        allowed = target in NAV_FOR_ROLE.get(user.role, frozenset())
        key = "navigate" if allowed else "navigate_unavailable"
        return AssistantResponse(
            language="kn" if lang == "kn" else "en",
            intent=rec.intent.value,
            confidence=rec.confidence,
            answer=render(key, lang, screen=screen_name(target, lang)),
            requires_confirmation=False,
            proposed_action=None,
            tool_calls=[],
            sources=[],
            disclaimer="",
            llm_used=False,
            understood_by=understood,
            answer_kind="guidance",
            heard=heard,
            navigate_to=target if allowed else None,
        )

    def call_tool(self, user: CurrentUser, name: str, req: ToolRequest) -> ToolResultOut:
        """Direct tool execution (used for confirmed actions and by the voice screen). Validated before running."""
        tool = self.tools.get(name)
        if tool is None:
            raise NotFoundError("Unknown assistant tool", code="unknown_tool")
        if user.role not in tool.roles:
            raise PermissionDeniedError("This tool is not available for your account type")
        if tool.writes and not req.confirm:
            raise ConflictError(
                "This action changes data; repeat the call with confirm=true", code="confirmation_required"
            )
        try:
            args = tool.args.model_validate(req.args)
        except ValidationError as exc:
            raise DomainValidationError(
                "Invalid tool arguments",
                code="invalid_tool_args",
                details={"errors": json.loads(exc.json(include_url=False))},
            ) from exc
        facts = tool.run(user, args, req.language)
        return ToolResultOut(
            tool=name,
            ok=True,
            answer=render(facts.key, req.language, **facts.values),
            data=facts.data,
            sources=facts.sources,
        )

    # ================================================================ tools
    def _registry(self) -> list[Tool]:
        return [
            Tool(
                "weather_summary",
                "Weather forecast and recent weather for one of your farms",
                frozenset({FARMER}),
                WeatherArgs,
                self._t_weather,
            ),
            Tool(
                "harvest_prediction",
                "Latest stored harvest prediction for your crops (does not create a new one)",
                frozenset({FARMER}),
                CycleArgs,
                self._t_prediction,
            ),
            Tool("farm_risk", "Risk report for one of your farms", frozenset({FARMER}), FarmArgs, self._t_risk),
            Tool(
                "list_reminders", "Your pending reminders", frozenset({FARMER, BUYER, ADMIN}), NoArgs, self._t_reminders
            ),
            Tool(
                "create_reminder",
                "Add a reminder (only after you confirm)",
                frozenset({FARMER, BUYER}),
                ReminderCreate,
                self._t_create_reminder,
                writes=True,
            ),
            Tool(
                "inventory_summary",
                "Your virtual harvest inventory totals",
                frozenset({FARMER}),
                NoArgs,
                self._t_inventory,
            ),
            Tool(
                "buyer_opportunities",
                "Open buyer demands for crops you grow (no prices)",
                frozenset({FARMER}),
                NoArgs,
                self._t_opportunities,
            ),
            Tool(
                "my_supply_requests",
                "Supply requests waiting for your answer",
                frozenset({FARMER}),
                NoArgs,
                self._t_requests,
            ),
            Tool("my_orders", "Your orders and their status", frozenset({BUYER}), NoArgs, self._t_orders),
            Tool(
                "farm_summary",
                "How many farms, plots and acres you have and which crops are planned or growing",
                frozenset({FARMER}),
                NoArgs,
                self._t_farms,
            ),
            Tool(
                "market_supply",
                "Future supply on offer from opted-in farms (estimates)",
                frozenset({BUYER, ADMIN}),
                NoArgs,
                self._t_market,
            ),
            Tool(
                "income_plans",
                "Your income plans and the estimated net income of your latest plan with crops",
                frozenset({FARMER}),
                NoArgs,
                self._t_plans,
            ),
            Tool(
                "expense_summary",
                "Expenses you recorded (all farms or one; by category and period)",
                frozenset({FARMER}),
                ExpenseArgs,
                self._t_expenses,
            ),
            Tool(
                "record_expense",
                "Record an expense on one of your farms (only after you confirm)",
                frozenset({FARMER}),
                RecordExpenseArgs,
                self._t_record_expense,
                writes=True,
            ),
        ]

    def _t_weather(self, user: CurrentUser, args: WeatherArgs, lang: str) -> Facts:
        farm = self._pick_farm(user, args.farm_id, need_coordinates=True)
        if farm is None:
            return Facts("no_farm", {}, None)
        if farm.latitude is None or farm.longitude is None:
            return Facts("weather_unavailable", {"farm": farm.name, "reason": "the farm has no location set"}, None)
        w = self._weather.farm_weather(user.user_id, farm.id, 7)
        src = [
            SourceRef(name="Open-Meteo forecast", kind=DataKind.ESTIMATE),
            SourceRef(name="Open-Meteo archive (reanalysis)", kind=DataKind.MEASURED),
        ]
        if not w.forecast:
            return Facts("weather_unavailable", {"farm": farm.name, "reason": w.note}, w.model_dump(mode="json"), src)
        if args.day is not None:
            # "tomorrow" is the farm's (IST) tomorrow; the answer says when the forecast was fetched and whether it is
            # an older saved copy, so a stale forecast is never presented as live
            local_today = (self._clock.now() + IST).date()
            wanted = local_today + timedelta(days=1 if args.day == "tomorrow" else 0)
            day = next((d for d in w.forecast if d.day == wanted), None)
            if day is not None:
                fetched = (w.fetched_at + IST).strftime("%d %b %H:%M") if w.fetched_at else "?"
                return Facts(
                    "weather_day",
                    {
                        "farm": farm.name,
                        "when": DAY_WORDS[args.day][lang == "kn"],
                        "date": wanted.strftime("%d %b"),
                        "tmin": _n(day.tmin_c),
                        "tmax": _n(day.tmax_c),
                        "rain": _n(day.rain_mm),
                        "fetched": fetched,
                        "status": FRESHNESS[w.status][lang == "kn"],
                    },
                    w.model_dump(mode="json"),
                    src,
                )
        rain = sum((d.rain_mm for d in w.forecast), Decimal(0))
        tmax = max(d.tmax_c for d in w.forecast)
        source = f"Open-Meteo ({w.status.value})"
        return Facts(
            "weather",
            {"farm": farm.name, "rain": _n(rain), "days": len(w.forecast), "tmax": _n(tmax), "source": source},
            w.model_dump(mode="json"),
            src,
        )

    def _t_prediction(self, user: CurrentUser, args: CycleArgs, lang: str) -> Facts:
        cycles = self._repo.active_cycles(user.user_id)
        if args.crop_cycle_id is not None:
            cycles = [(c, f) for c, f in cycles if c.id == args.crop_cycle_id]
            if not cycles:
                raise NotFoundError("Crop cycle not found")
        if not cycles:
            return Facts("no_cycle", {}, None)
        cycle, _farm = cycles[0]
        page = self._predictions.list_for_cycle(user.user_id, cycle.id, limit=1, offset=0)
        crop = cycle.crop.name
        if not page.items:
            return Facts("no_prediction", {"crop": crop}, None)
        latest = (
            max(page.items, key=lambda p: p.version) if page.total <= 1 else self._latest(user, cycle.id, page.total)
        )
        src = [SourceRef(name=s.name, kind=s.kind) for s in latest.sources if s.used]
        if latest.quantity_kg is None:
            return Facts("prediction_insufficient", {"crop": crop}, latest.model_dump(mode="json"), src)
        q = latest.quantity_kg
        return Facts(
            "prediction",
            {
                "crop": crop,
                "p10": _n(q.p10),
                "p50": _n(q.p50),
                "p90": _n(q.p90),
                "conf": _n(latest.confidence.score),
                "level": latest.confidence.level.value,
                "start": latest.timing.start_p50.isoformat(),
            },
            latest.model_dump(mode="json"),
            src,
        )

    def _t_risk(self, user: CurrentUser, args: FarmArgs, lang: str) -> Facts:
        farm = self._pick_farm(user, args.farm_id, need_coordinates=False)
        if farm is None:
            return Facts("no_farm", {}, None)
        r = self._predictions.farm_risk(user.user_id, farm.id)
        if r.overall_score is None:
            return Facts("risk_unknown", {"farm": farm.name}, r.model_dump(mode="json"))
        assessed = sum(1 for v in r.worst_by_category.values() if v is not None)
        return Facts(
            "risk",
            {"farm": farm.name, "level": r.overall_level, "score": _n(r.overall_score), "assessed": assessed},
            r.model_dump(mode="json"),
            [SourceRef(name="Farm Risk Engine", kind=DataKind.ESTIMATE)],
        )

    def _t_reminders(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        page = self._reminders.list_reminders(user.user_id, ReminderStatus.PENDING, limit=5, offset=0)
        items = "".join(f"\n• {r.title} ({r.due_at.date().isoformat()})" for r in page.items)
        return Facts("reminders", {"n": page.total, "items": items}, page.model_dump(mode="json"))

    def _t_create_reminder(self, user: CurrentUser, args: ReminderCreate, lang: str) -> Facts:
        out = self._reminders.create(user.user_id, args, source="assistant")
        return Facts(
            "reminder_created",
            {"title": out.title, "when": out.due_at.strftime("%Y-%m-%d %H:%M")},
            out.model_dump(mode="json"),
        )

    def _t_inventory(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        page = self._inventory.list_lots(user.user_id, limit=100, offset=0)
        avail = sum((lot.available_kg for lot in page.items), Decimal(0))
        committed = sum((lot.committed_kg for lot in page.items), Decimal(0))
        return Facts(
            "inventory",
            {"n": page.total, "available": _n(avail), "committed": _n(committed)},
            page.model_dump(mode="json"),
            [SourceRef(name="Virtual inventory (p10)", kind=DataKind.ESTIMATE)],
        )

    def _t_opportunities(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        ops = self._market.opportunities(user.user_id)
        items = "".join(f"\n• {o.crop_name}: {_n(o.quantity_kg)} kg, {o.window_start}–{o.window_end}" for o in ops[:5])
        return Facts("opportunities", {"n": len(ops), "items": items}, [o.model_dump(mode="json") for o in ops])

    def _t_requests(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        page = self._market.participations(user.user_id, ParticipationStatus.PENDING, limit=10, offset=0)
        items = "".join(f"\n• {p.crop_name}: {_n(p.quantity_kg)} kg" for p in page.items)
        return Facts("requests", {"n": page.total, "items": items}, page.model_dump(mode="json"))

    def _t_orders(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        page = self._market.list_orders(user, None, limit=10, offset=0)
        items = "".join(
            f"\n• {o.crop_name} {_n(o.ordered_kg)} kg: {o.status.value.replace('_', ' ')}" for o in page.items
        )
        return Facts("orders", {"n": page.total, "items": items}, page.model_dump(mode="json"))

    def _t_market(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        rows = self._market.supply_summary()
        items = "".join(f"\n• {r.crop_name}: {_n(r.available_kg)} kg from {r.lots} lots" for r in rows) or "\n• —"
        return Facts(
            "market_supply",
            {"items": items},
            [r.model_dump(mode="json") for r in rows],
            [SourceRef(name="Opted-in lots (p10)", kind=DataKind.ESTIMATE)],
        )

    def _t_farms(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        farms = list(self._farms.list_owned(user.user_id, include_archived=False, limit=100, offset=0).items)
        if not farms:
            return Facts("no_farm", {}, None)
        plots = self._repo.session.scalar(
            select(func.count())
            .select_from(FarmPlot)
            .where(FarmPlot.farm_id.in_([f.id for f in farms]), FarmPlot.is_active.is_(True))
        )
        cycles = self._repo.active_cycles(user.user_id)
        names = sorted({c.crop.name for c, _farm in cycles})
        return Facts(
            "farm_summary",
            {
                "farms": str(len(farms)),
                "plots": str(plots or 0),
                "acres": _n(sum((Decimal(f.total_area_acres) for f in farms), Decimal(0))),
                "crops": str(len(cycles)),
                "crop_list": (": " + ", ".join(names)) if names else "",
            },
            {"farms": [{"id": str(f.id), "name": f.name} for f in farms], "crops": names},
            [SourceRef(name="Your farm records", kind=DataKind.MEASURED)],
        )

    def _t_plans(self, user: CurrentUser, args: NoArgs, lang: str) -> Facts:
        page = self._plans.list_owned(user.user_id, farm_id=None, limit=20, offset=0)
        if not page.items:
            return Facts("plans", {"n": 0, "items": ""}, page.model_dump(mode="json"))
        with_crops = [p for p in page.items if p.item_count > 0]
        if not with_crops:
            names = "".join(f"\n• {p.name}" for p in page.items[:5])
            return Facts("plans_empty", {"n": page.total, "items": names}, page.model_dump(mode="json"))
        latest = max(with_crops, key=lambda p: p.updated_at)
        ev = self._plans.evaluate(user.user_id, latest.id)
        m = ev.totals.margin
        values = {
            "plan": latest.name,
            "crops": latest.item_count,
            "expected": _n(m.expected),
            "low": _n(m.low),
            "high": _n(m.high),
        }
        data = {
            "plans": page.model_dump(mode="json"),
            "evaluated_plan_id": str(latest.id),
            "totals": ev.totals.model_dump(mode="json"),
        }
        return Facts(
            "plan_result", values, data, [SourceRef(name="Income planner (your inputs)", kind=DataKind.ESTIMATE)]
        )

    def _t_expenses(self, user: CurrentUser, args: ExpenseArgs, lang: str) -> Facts:
        if args.farm_id is not None:
            farm_ids = [args.farm_id]  # the expense service answers 404 for a farm that is not the caller's
        else:
            farms = self._farms.list_owned(user.user_id, include_archived=True, limit=100, offset=0)
            if not farms.items:
                return Facts("no_farm", {}, None)
            farm_ids = [f.id for f in farms.items]
        rows = []
        for farm_id in farm_ids:
            offset = 0
            while True:  # every page: a total must not silently stop at the first 100 entries
                page = self._expenses.list_for_farm(
                    user.user_id,
                    farm_id,
                    crop_cycle_id=args.crop_cycle_id,
                    category=args.category,
                    date_from=args.date_from,
                    date_to=args.date_to,
                    limit=100,
                    offset=offset,
                )
                rows.extend(page.items)
                offset += len(page.items)
                if not page.items or offset >= page.total:
                    break
        what = self._category_words(args.category, lang)
        when = self._period_words(args.date_from, args.date_to, lang)
        if not rows:
            return Facts("expenses_none", {"what": what, "when": when}, [])
        total = sum((e.amount for e in rows), Decimal(0))
        by_cat: dict[str, Decimal] = {}
        for e in rows:
            by_cat[e.category.value] = by_cat.get(e.category.value, Decimal(0)) + e.amount
        top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:3]
        items = "" if args.category else "".join(f"\n• {self._category_label(c, lang)}: {_n(a)}" for c, a in top)
        return Facts(
            "expenses",
            {
                "total": _n(total),
                "n": len(rows),
                "entries": "1 entry" if len(rows) == 1 else f"{len(rows)} entries",
                "what": what,
                "when": when,
                "items": items,
            },
            [e.model_dump(mode="json") for e in rows[:50]],
            [SourceRef(name="Expenses you recorded", kind=DataKind.MEASURED)],
        )

    def _t_record_expense(self, user: CurrentUser, args: RecordExpenseArgs, lang: str) -> Facts:
        payload = ExpenseCreate(**args.model_dump(exclude={"farm_id"}))
        out = self._expenses.create(user.user_id, args.farm_id, payload)
        values = {
            "amount": _n(out.amount),
            "category": self._category_label(out.category.value, lang),
            "date": out.expense_date.isoformat(),
        }
        return Facts("expense_created", values, out.model_dump(mode="json"))

    # =============================================================== helpers
    def _safe_run(self, user: CurrentUser, tool: Tool, raw: dict[str, Any], lang: str) -> tuple[Facts, ToolCallOut]:
        shown = {k: str(v) for k, v in raw.items()}
        if user.role not in tool.roles:
            return Facts("not_for_role", {}, None), ToolCallOut(
                tool=tool.name, args=shown, ok=False, error_code="permission_denied"
            )
        try:
            facts = tool.run(user, tool.args.model_validate(raw), lang)
            return facts, ToolCallOut(tool=tool.name, args=shown, ok=True)
        except AppError as exc:
            if isinstance(exc, NotFoundError):
                return Facts("unknown", {}, None), ToolCallOut(
                    tool=tool.name, args=shown, ok=False, error_code=exc.code
                )
            return Facts("tool_failed", {}, None), ToolCallOut(
                tool=tool.name, args=shown, ok=False, error_code=exc.code
            )

    def _propose_reminder(
        self, rec: Recognised, lang: str, req: AssistantRequest
    ) -> tuple[Facts, ProposedAction | None]:
        when = rec.slots.get("date")
        if not isinstance(when, date):
            return Facts("reminder_need_date", {}, None), None
        due = local_due(when, int(rec.slots.get("hour", 9)))  # type: ignore[call-overload]
        if due < self._clock.now() - timedelta(minutes=1):
            return Facts("reminder_need_date", {}, None), None
        kind = rec.slots.get("reminder_type", ReminderType.CUSTOM)
        args = ReminderCreate(
            reminder_type=kind if isinstance(kind, ReminderType) else ReminderType.CUSTOM,
            title=str(rec.slots.get("title") or "Reminder"),
            due_at=due,
            farm_id=req.farm_id,
            crop_cycle_id=req.crop_cycle_id,
        )
        when_s = due.strftime("%Y-%m-%d %H:%M")
        action = ProposedAction(
            tool="create_reminder",
            args=args.model_dump(mode="json", exclude_none=True),
            summary=f"{args.title} — {when_s}",
        )
        return Facts("reminder_confirm", {"title": args.title, "when": when_s}, None), action

    def _propose_expense(
        self, user: CurrentUser, rec: Recognised, lang: str, context: dict[str, Any]
    ) -> tuple[Facts, ProposedAction | None]:
        if user.role is not FARMER:
            return Facts("not_for_role", {}, None), None
        amount = rec.slots.get("amount")
        if amount is None:
            return Facts("expense_need_amount", {}, None), None
        value = Decimal(str(amount))
        category = rec.slots.get("category")
        if not isinstance(category, ExpenseCategory):
            return Facts("expense_need_category", {"amount": _n(value)}, None), None
        farm = self._pick_farm(user, context.get("farm_id"), need_coordinates=False)
        if farm is None:
            return Facts("no_farm", {}, None), None
        when = rec.slots.get("date")
        try:
            args = RecordExpenseArgs(
                farm_id=farm.id,
                crop_cycle_id=context.get("crop_cycle_id"),
                category=category,
                amount=value,
                expense_date=when if isinstance(when, date) else self._clock.now().date(),
                description=str(rec.slots.get("description") or "")[:255] or None,
            )
        except ValidationError:  # e.g. zero or too many decimals: ask again rather than guess
            return Facts("expense_need_amount", {}, None), None
        values = {
            "amount": _n(value),
            "category": self._category_label(category.value, lang),
            "date": args.expense_date.isoformat(),
            "farm": farm.name,
        }
        action = ProposedAction(
            tool="record_expense",
            args=args.model_dump(mode="json", exclude_none=True),
            summary=f"{_n(value)} INR · {category.value} · {args.expense_date.isoformat()} · {farm.name}",
        )
        return Facts("expense_confirm", values, None), action

    def _mentions(self, user: CurrentUser, text: str) -> dict[str, uuid.UUID]:
        """A crop or farm the farmer named ('ragi', 'Green Acres') -> that record's id. Only the caller's own
        records are searched, so a name can never reach someone else's data."""
        if user.role is not FARMER:
            return {}
        low = f" {' '.join(text.lower().split())} "
        found: dict[str, uuid.UUID] = {}
        for cycle, farm in self._repo.active_cycles(user.user_id):
            names = [cycle.crop.name, cycle.crop.local_name]
            if any(n and f" {n.lower()}" in low for n in names):
                found = {"crop_cycle_id": cycle.id, "farm_id": farm.id}
                break
        if "farm_id" not in found:
            for f in self._farms.list_owned(user.user_id, include_archived=False, limit=100, offset=0).items:
                if f" {f.name.lower()}" in low:
                    found["farm_id"] = f.id
                    break
        return found

    @staticmethod
    def _previous_intent(req: AssistantRequest) -> Intent | None:
        for turn in reversed(req.history):
            if turn.role == "assistant" and turn.intent:
                try:
                    return Intent(turn.intent)
                except ValueError:
                    return None
        return None

    @staticmethod
    def _follow_up(intent: Intent, text: str, lang: str, today: date) -> Recognised:
        slots = expense_summary_slots(text, today) if intent is Intent.EXPENSE_SUMMARY else {}
        return Recognised(intent, 0.5, lang, "context", slots)

    @staticmethod
    def _expense_slot_args(rec: Recognised) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if isinstance(rec.slots.get("category"), ExpenseCategory):
            out["category"] = rec.slots["category"]
        if isinstance(rec.slots.get("from"), date):
            out["date_from"] = rec.slots["from"]
        if isinstance(rec.slots.get("to"), date):
            out["date_to"] = rec.slots["to"]
        return out

    @staticmethod
    def _category_label(value: str, lang: str) -> str:
        return CATEGORY_KN.get(value, value) if lang == "kn" else value.replace("_", " ")

    @staticmethod
    def _category_words(category: ExpenseCategory | None, lang: str) -> str:
        if category is None:
            return ""
        return f" ({CATEGORY_KN[category.value]})" if lang == "kn" else f" on {category.value}"

    def _period_words(self, start: date | None, end: date | None, lang: str) -> str:
        today = self._clock.now().date()
        if start is None:
            return PERIOD_EN["all"] if lang == "en" else ""
        first = today.replace(day=1)
        end = end or today
        if start == first and end == today:
            key = "this_month"
        elif end == first - timedelta(days=1) and start == end.replace(day=1):
            key = "last_month"
        elif start == today.replace(month=1, day=1) and end == today:
            key = "this_year"
        else:
            days = (end - start).days + 1
            return f" in the last {days} days" if lang == "en" else f" ಕಳೆದ {days} ದಿನಗಳಲ್ಲಿ"
        return PERIOD_EN[key] if lang == "en" else PERIOD_KN[key]

    def _llm_pick(self, user: CurrentUser, req: AssistantRequest) -> Intent | str | None:
        """Ask the local model which READ-ONLY tool fits. Anything outside the allowed list is ignored."""
        allowed = {n: t for n, t in self.tools.items() if user.role in t.roles and not t.writes and n in TOOL_INTENT}
        catalogue = "\n".join(f"- {n}: {t.description}" for n, t in allowed.items())
        system = (
            "You route a farmer's message to ONE tool of a farm app. Reply with JSON only, like "
            '{"tool": "weather_summary"}. Use a tool name from the list; "general" for a general farming question '
            'that needs no personal data (how to grow, pests in general, practices); or "none" if unclear.\n'
            f"Tools:\n{catalogue}"
        )
        messages = [LLMMessage("system", system)]
        messages += [LLMMessage(turn.role, turn.text[:300]) for turn in req.history[-4:]]
        messages.append(LLMMessage("user", req.message))
        try:
            out = self._llm.generate(
                LLMRequest(messages=tuple(messages), temperature=0.0, max_tokens=30, json_mode=True)
            )
            choice = json.loads(out.text).get("tool")
        except (AppError, ValueError, AttributeError):
            return None
        if choice == "general" and self._llm_general:
            return "general"
        if isinstance(choice, str) and choice in allowed:
            return TOOL_INTENT[choice]
        return None

    def _general_answer(self, req: AssistantRequest, lang: str) -> str | None:
        """A friendly general answer from the local model (any topic, not only farming). It has NO access to the
        asker's records, so sentences that state facts about "your farm / your expenses ..." are removed; numbers
        are allowed but marked approximate. Kannada is written only when that is enabled (see settings)."""
        write_kn = lang == "kn" and self._llm_general_kn
        system = (
            "You are Harvestique's friendly assistant for farmers and buyers in Karnataka, India. Answer the "
            "question helpfully and concisely, in at most 5 short sentences, in "
            f"{'Kannada' if write_kn else 'simple English'}. You may answer questions on any topic. "
            "You cannot see this person's farm records: never state or guess their own expenses, yields, orders, "
            "weather or crop condition. If you give doses, quantities, prices or timings, say they are typical or "
            "approximate and should be checked locally (product label, Raitha Samparka Kendra or agriculture "
            "officer). For how to use this app's screens, suggest the in-app user manual (Help). If you are not "
            "sure, say so. If the message is not a clear question or request (a fragment, filler words or garbled "
            "speech), reply with only the word UNCLEAR."
        )
        messages = [LLMMessage("system", system)]
        messages += [LLMMessage(turn.role, turn.text[:300]) for turn in req.history[-4:]]
        understood_as: str | None = None
        question = req.message
        if KANNADA.search(req.message) and not write_kn:
            # the local model misreads Kannada when it answers it directly; translating first (glossary terms
            # replaced, simple "what is X" without a model) is far more reliable, and the user SEES the reading
            understood_as = self._to_english(req.message)
            if understood_as is None:
                return None
            question = understood_as
        messages.append(LLMMessage("user", question))
        try:
            out = self._llm.generate(LLMRequest(messages=tuple(messages), temperature=0.3, max_tokens=220))
            text = out.text.strip()
            if text.upper().strip(" .!\"'") == "UNCLEAR":
                return UNCLEAR
            if not write_kn and KANNADA.search(text):
                retry = (
                    *messages,
                    LLMMessage("assistant", text),
                    LLMMessage("user", "Please give that answer in simple English only."),
                )
                text = self._llm.generate(LLMRequest(messages=retry, temperature=0.2, max_tokens=220)).text.strip()
        except AppError:
            return None
        if (not write_kn and KANNADA.search(text)) or OTHER_SCRIPTS.search(text):
            logger.info("general answer dropped: wrong language or mixed scripts")
            return None  # read aloud with the wrong voice or unreadable: better to say nothing than garble
        answer = checked_general_answer(text)
        if answer is not None and understood_as is not None:
            answer = f'{UNDERSTOOD_AS}: "{understood_as}"\n\n{answer}'
        return answer

    def _to_english(self, text: str) -> str | None:
        """A Kannada question in English: glossary 'what is X' first, otherwise the local model translates the
        glossed text. None when no usable translation comes back."""
        if (direct := english_question(text)) is not None:
            return direct
        system = "Translate the user's Kannada message into English. Reply with the English translation only."
        try:
            out = self._llm.generate(
                LLMRequest(
                    messages=(LLMMessage("system", system), LLMMessage("user", gloss(text))),
                    temperature=0.0,
                    max_tokens=60,
                )
            )
        except AppError:
            return None
        english = out.text.strip().strip('"').splitlines()[0].strip() if out.text.strip() else ""
        if not english or KANNADA.search(english) or OTHER_SCRIPTS.search(english) or len(english) > 300:
            return None
        return english

    # ------------------------------------------------------------ responses, estimates, suitability
    def _reply(
        self,
        rec: Recognised,
        lang: str,
        answer: str,
        *,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
        kind: Literal["records", "general_ai", "mixed", "guidance"] = "guidance",
        calls: list[ToolCallOut] | None = None,
        sources: list[SourceRef] | None = None,
        disclaimer: str = "",
        llm_used: bool = False,
    ) -> AssistantResponse:
        return AssistantResponse(
            language="kn" if lang == "kn" else "en",
            intent=rec.intent.value,
            confidence=rec.confidence,
            answer=answer,
            requires_confirmation=False,
            proposed_action=None,
            tool_calls=calls or [],
            sources=sources or [],
            disclaimer=disclaimer,
            llm_used=llm_used,
            understood_by=understood,
            answer_kind=kind,
            heard=heard,
        )

    def _find_crop(self, text: str) -> Crop | None:
        """The catalogue crop named in the question (English name or Kannada name, longest match wins)."""
        norm = normalise(text)
        best: Crop | None = None
        best_len = 0
        for crop in self._repo.session.scalars(select(Crop).where(Crop.is_active.is_(True))):
            names = (crop.name, crop.local_name or "", *(crop.aliases or []))  # "finger millet" -> Ragi
            for name in (normalise(x) for x in names):
                if not name or len(name) <= best_len:
                    continue
                pattern = rf"\b{re.escape(name)}(s|es)?\b" if name.isascii() else rf"(^|\s){re.escape(name)}"
                if re.search(pattern, norm):
                    best, best_len = crop, len(name)
        return best

    def _context_crop(self, req: AssistantRequest) -> Crop | None:
        """The newest crop the person named earlier in this conversation (their own messages only)."""
        for turn in reversed(req.history):
            if turn.role == "user" and (crop := self._find_crop(turn.text)) is not None:
                return crop
        return None

    def _crop_records(self, user: CurrentUser, crop: Crop) -> list[str]:
        """'<plot> (<farm>, <status>)' for each of the farmer's own active cycles of this crop."""
        rows = self._repo.session.execute(
            select(FarmPlot.name, Farm.name, CropCycle.status)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(
                Farm.owner_id == user.user_id,
                CropCycle.crop_id == crop.id,
                CropCycle.status.in_(("planned", "growing")),
            )
        ).all()
        return [f"{plot} ({farm}, {status})" for plot, farm, status in rows]

    def _crop_statement(
        self,
        user: CurrentUser,
        req: AssistantRequest,
        rec: Recognised,
        lang: str,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
    ) -> AssistantResponse:
        """'I am growing mango': confirm the crop, check it against the farmer's OWN records (never adds or claims a
        record), and say what can be asked next. The crop is then used as context by later questions."""
        kn = lang == "kn"
        crop = self._find_crop(req.message)
        if crop is None:
            return self._reply(rec, lang, STATEMENT_TEXT["need_crop"][kn], understood=understood, heard=heard)
        label = (crop.local_name or crop.name) if kn else crop.name
        records = self._crop_records(user, crop)
        call = ToolCallOut(tool="farm_crops", args={"crop": crop.name}, ok=True)
        if records:
            found = STATEMENT_TEXT["recorded"][kn].format(crop=label, records="; ".join(records))
        else:
            found = STATEMENT_TEXT["not_recorded"][kn].format(crop=label)
        answer = f"{STATEMENT_TEXT['noted'][kn].format(crop=label)} {found} {STATEMENT_TEXT['next'][kn]}"
        return self._reply(
            rec,
            lang,
            answer,
            understood=understood,
            heard=heard,
            kind="records",
            calls=[call],
            sources=[SourceRef(name="Your farm records", kind=DataKind.MEASURED)],
            disclaimer=DISCLAIMER[lang],
        )

    def _recommend(
        self,
        user: CurrentUser,
        req: AssistantRequest,
        rec: Recognised,
        lang: str,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
    ) -> AssistantResponse:
        """'What crops are best to grow on my farm?': a SHORTLIST from the farmer's own farm record (place, soil,
        water source; or what they told me in this conversation), today's season and the catalogue's season and
        water needs. It names its evidence and asks for what is missing; it never invents prices or yields."""
        kn = lang == "kn"
        farms = list(self._farms.list_owned(user.user_id, include_archived=False, limit=100, offset=0).items)
        call = ToolCallOut(tool="crop_recommendation", args={}, ok=True)
        if not farms:
            return self._reply(
                rec, lang, RECOMMEND_TEXT["no_farm"][kn], understood=understood, heard=heard, calls=[call]
            )
        farm = farms[0]
        plots = list(
            self._repo.session.scalars(
                select(FarmPlot).where(FarmPlot.farm_id.in_([f.id for f in farms]), FarmPlot.is_active.is_(True))
            )
        )
        soils = sorted({p.soil_type.value for p in plots if p.soil_type})
        waters = sorted({p.irrigation_type.value for p in plots if p.irrigation_type})
        # what the farmer told me since asking (e.g. "red soil, borewell") counts for this conversation only
        topic = [req.message]
        for i in range(len(req.history) - 1, 0, -1):
            turn = req.history[i]
            if turn.role == "assistant" and turn.intent == Intent.CROP_RECOMMENDATION.value:
                if req.history[i - 1].role == "user":
                    topic.insert(0, req.history[i - 1].text)
            elif turn.role == "assistant":
                break
        for text in topic:
            soil, water = soil_and_water(text)
            soils = [soil] if soil else soils
            waters = [water] if water else waters
        mentioned = [c for c in (self._find_crop(t) for t in topic) if c is not None]
        grown = [c.crop.name for c, _farm in self._repo.active_cycles(user.user_id)]
        season = season_now((self._clock.now() + IST).date().month)
        rainfed = bool(waters) and all(w == "rainfed" for w in waters)
        limit = Decimal(400) if rainfed else (None if waters else Decimal(500))
        catalogue = self._repo.session.scalars(select(Crop).where(Crop.is_active.is_(True))).all()
        picks = []
        for c in catalogue:
            group, _part = group_and_part(c.name, c.category.value, c.crop_group.value if c.crop_group else None)
            if group in NOT_FIELD_GROUPS or c.typical_duration_days >= 365:  # perennials are not a season's choice
                continue
            if c.season is None or c.season.value not in (season, "year_round"):
                continue
            if limit is not None and (c.water_need_mm is None or Decimal(c.water_need_mm) > limit):
                continue
            picks.append(c)
        picks.sort(key=lambda c: (c.season.value != season if c.season else True, c.water_need_mm or 0, c.name))
        picks = picks[:6]
        place = ", ".join(x for x in (farm.village, farm.district, farm.state) if x) or UNKNOWN_WORD[kn]
        soil_txt = ", ".join(soils) or UNKNOWN_WORD[kn]
        water_txt = ", ".join(waters) or UNKNOWN_WORD[kn]
        call = call.model_copy(
            update={
                "args": {
                    "farm": str(farm.id),
                    "season": season,
                    "soil": soil_txt if soils else "",
                    "water": water_txt if waters else "",
                }
            }
        )

        def name(c: Crop) -> str:
            return (c.local_name or c.name) if kn else c.name

        lines = [RECOMMEND_TEXT["title"][kn].format(farm=farm.name, place=place, season=SEASON_WORDS[season][kn])]
        for c in picks:
            when = SEASON_WORDS[c.season.value][kn] if c.season else ""
            lines.append(
                RECOMMEND_TEXT["item"][kn].format(
                    crop=name(c),
                    season=when,
                    days=c.typical_duration_days,
                    water=_n(c.water_need_mm) if c.water_need_mm else "?",
                )
            )
        if not picks:
            lines.append(RECOMMEND_TEXT["none"][kn])
        lines.append(RECOMMEND_TEXT["basis"][kn].format(place=place, soil=soil_txt, water=water_txt))
        if limit is not None:
            lines.append(RECOMMEND_TEXT["water_rule"][kn].format(mm=_n(limit)))
        if soils:
            lines.append(RECOMMEND_TEXT["soil_note"][kn])
        already = sorted(
            {name(c) for c in mentioned}
            | {(c.local_name or c.name) if kn else c.name for c in catalogue if c.name in grown}
        )
        if already:
            lines.append(RECOMMEND_TEXT["already"][kn].format(crops=", ".join(already)))
        missing = [RECOMMEND_TEXT[k][kn] for k, v in (("ask_soil", soils), ("ask_water", waters)) if not v]
        if missing:
            lines.append(RECOMMEND_TEXT["ask"][kn].format(missing=RECOMMEND_TEXT["and"][kn].join(missing)))
        lines.append(RECOMMEND_TEXT["not_advice"][kn])
        return self._reply(
            rec,
            lang,
            "\n".join(lines),
            understood=understood,
            heard=heard,
            kind="records",
            calls=[call],
            sources=[
                SourceRef(name="Your farm records", kind=DataKind.MEASURED),
                SourceRef(name="Crop catalogue seasons and water needs", kind=DataKind.ASSUMPTION),
            ],
            disclaimer=DISCLAIMER[lang],
        )

    def _saved_item(self, user: CurrentUser, crop: Crop) -> CropPlanItem | None:
        """The farmer's own most recent plan line for this crop (their entered yield, price and costs)."""
        return self._repo.session.scalars(
            select(CropPlanItem)
            .join(CropPlan, CropPlan.id == CropPlanItem.plan_id)
            .where(CropPlan.owner_id == user.user_id, CropPlanItem.crop_id == crop.id)
            .order_by(CropPlanItem.updated_at.desc())
            .limit(1)
        ).first()

    def _estimate_messages(self, req: AssistantRequest) -> list[str]:
        """The person's messages in the current estimate conversation, oldest first, ending with this one. Earlier
        messages count only while every assistant reply after them was part of the estimate."""
        turns = list(req.history)
        users: list[str] = []
        i = len(turns) - 1
        while i >= 1 and turns[i].role == "assistant" and turns[i].intent == Intent.CROP_ESTIMATE.value:
            if turns[i - 1].role != "user":
                break
            users.insert(0, turns[i - 1].text)
            i -= 2
        return [*users, req.message]

    def _recorded_cost(self, user: CurrentUser, crop: Crop) -> tuple[Decimal, str, int] | None:
        """Cost per acre from the farmer's OWN recorded expenses for this crop (latest season with expenses):
        (per acre, sowing date, number of entries). Local, real data; may be incomplete for a running season."""
        row = self._repo.session.execute(
            select(
                CropCycle.area_acres, CropCycle.sowing_date, func.sum(FarmExpense.amount), func.count(FarmExpense.id)
            )
            .join(FarmExpense, FarmExpense.crop_cycle_id == CropCycle.id)
            .join(FarmPlot, FarmPlot.id == CropCycle.plot_id)
            .join(Farm, Farm.id == FarmPlot.farm_id)
            .where(Farm.owner_id == user.user_id, CropCycle.crop_id == crop.id)
            .group_by(CropCycle.id, CropCycle.area_acres, CropCycle.sowing_date)
            .order_by(CropCycle.sowing_date.desc())
            .limit(1)
        ).first()
        if row is None or not row[0]:
            return None
        return Decimal(row[2]) / Decimal(row[0]), row[1].strftime("%d %b %Y"), int(row[3])

    def _estimate(
        self,
        user: CurrentUser,
        req: AssistantRequest,
        rec: Recognised,
        lang: str,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
    ) -> AssistantResponse:
        """Income / cost / profit for a crop on some acres. Inputs, in order of preference:
        * what the person said in this conversation (newest wins; unclear numbers are asked about);
        * their saved income plan;
        * price: the latest AGMARKNET mandi price near the farm (source, market, date and age shown);
        * cost: their own recorded expenses for this crop;
        * harvest: the catalogue's reference yield (labelled, never 'your farm').
        Anything still missing is asked for; nothing is guessed. Arithmetic runs in the income calculator."""
        kn = lang == "kn"
        messages = self._estimate_messages(req)
        crop, start = None, 0
        for idx in range(len(messages) - 1, -1, -1):  # the newest named crop; a different crop starts afresh
            if (found := self._find_crop(messages[idx])) is not None:
                if crop is None:
                    crop, start = found, idx
                elif found.id != crop.id:
                    break
                else:
                    start = idx
        if crop is not None:
            messages = messages[start:]
        else:
            crop = self._context_crop(req)  # a crop the farmer named earlier in this conversation
        inputs = conversation_inputs(messages)
        label = ((crop.local_name or crop.name) if kn else crop.name) if crop is not None else None

        def reply(text: str, kind: Literal["records", "guidance"] = "guidance", **kw: Any) -> AssistantResponse:
            return self._reply(rec, lang, text, understood=understood, heard=heard, kind=kind, **kw)

        if inputs.unclear:
            return reply(estimate_unclear(inputs, lang))
        acres = inputs.acres
        item = self._saved_item(user, crop) if crop is not None else None
        missing: list[str] = []
        if acres is None:
            missing.append(ASK["acres"][kn])
        harvest: tuple[Decimal, Decimal, Decimal] | None = None
        h_basis = ""
        if inputs.harvest_kg is not None:
            per = _per_acre(inputs.harvest_kg, inputs.harvest_scope, acres)
            if per is None:
                missing.append(ASK["harvest_scope"][kn].format(x=inr(inputs.harvest_kg), acres=_n(acres or 1)))
            else:
                harvest, h_basis = (per, per, per), ("actual" if inputs.harvest_actual else "said")
        elif item is not None:
            harvest, h_basis = (item.yield_low_kg, item.yield_expected_kg, item.yield_high_kg), "plan"
        elif crop is not None and crop.reference_yield_kg_per_acre:
            ref = Decimal(crop.reference_yield_kg_per_acre)
            cv = Decimal(crop.reference_yield_cv or Decimal("0.25"))
            harvest, h_basis = (ref * (1 - cv), ref, ref * (1 + cv)), "catalogue"
        price: tuple[Decimal, Decimal, Decimal] | None = None
        p_basis, price_note = "", ""
        quote: PriceQuote | None = None
        if inputs.price_per_kg is not None:
            price, p_basis = (inputs.price_per_kg,) * 3, "said"
        elif item is not None:
            price, p_basis = (item.price_low, item.price_expected, item.price_high), "plan"
        elif crop is not None and self._market_prices is not None and inputs.income is None:
            farm = self._pick_farm(user, None, need_coordinates=False)
            result = self._market_prices.quote(
                crop.name, state=getattr(farm, "state", None), district=getattr(farm, "district", None)
            )
            if result.quote is not None:
                quote = result.quote
                price, p_basis = quote.per_kg(), "market"
            else:
                key = "off" if not result.live else ("failed" if result.refresh_failed else "none")
                price_note = MARKET_NOTE[key][kn].format(crop=label)
        cost_per_acre: Decimal | None = None
        c_basis = ""
        if inputs.cost is not None:
            cost_per_acre = _per_acre(inputs.cost, inputs.cost_scope, acres)
            c_basis = BASIS_WORDS["said"][kn]
            if cost_per_acre is None:
                missing.append(ASK["cost_scope"][kn].format(x=inr(inputs.cost), acres=_n(acres or 1)))
        elif item is not None:
            cost_per_acre = sum(
                (
                    item.seed_cost,
                    item.fertilizer_cost,
                    item.pesticide_cost,
                    item.irrigation_cost,
                    item.machinery_cost,
                    item.other_cost,
                    item.labour_person_days * item.labour_wage,
                ),
                Decimal(0),
            )
            c_basis = BASIS_WORDS["plan"][kn]
        elif crop is not None and (recorded := self._recorded_cost(user, crop)) is not None:
            cost_per_acre = recorded[0]
            c_basis = BASIS_WORDS["records"][kn].format(sown=recorded[1], n=recorded[2])
        income_total: Decimal | None = None
        if inputs.income is not None:
            per = _per_acre(inputs.income, inputs.income_scope, acres)
            if per is None:
                missing.append(ASK["income_scope"][kn].format(x=inr(inputs.income), acres=_n(acres or 1)))
            elif acres is not None:
                income_total = per * acres
        if harvest is None and income_total is None and inputs.income is None:
            missing.append(ASK["crop_or_harvest"][kn] if crop is None else ASK["harvest"][kn])
        if price is None and income_total is None and inputs.income is None:
            missing.append(ASK["price"][kn])
        if missing and cost_per_acre is None and inputs.cost is None:
            missing.append(ASK["cost"][kn])  # ask everything still needed in one question
        if missing or acres is None:
            text = estimate_missing(missing, label, lang)
            if price_note:
                text += " " + price_note
            if harvest is not None and h_basis == "catalogue":
                text += " " + ESTIMATE_TEXT["catalogue_note"][kn].format(
                    low=inr(harvest[0]), high=inr(harvest[2]), basis=BASIS_WORDS["catalogue"][kn]
                )
            return reply(text)
        cost_total = cost_per_acre * acres if cost_per_acre is not None else None
        lines = [ESTIMATE_TEXT["title"][kn].format(acres=_n(acres), crop=f" {label}" if label else "")]
        calc_call: ToolCallOut | None = None
        production: Decimal | None = None
        if income_total is not None and (harvest is None or price is None):
            lines.append(
                ESTIMATE_TEXT["income_said"][kn].format(income=inr(income_total), basis=BASIS_WORDS["said"][kn])
            )
            profit_low = profit = income_total - cost_total if cost_total is not None else None
        else:
            assert harvest is not None and price is not None
            calc_call = ToolCallOut(
                tool="income_calculator", args={"crop": crop.name if crop else "", "acres": str(acres)}, ok=True
            )
            try:
                result_plan = self._planning.calculate(
                    CalcRequest(
                        available_land_acres=acres,
                        items=[
                            CalcItem(
                                crop_name=crop.name if crop else "Crop",
                                sowing_date=self._clock.now().date(),
                                duration_days=crop.typical_duration_days if crop else 120,
                                area_acres=acres,
                                yield_per_acre_kg=YieldRangeIn(low=harvest[0], expected=harvest[1], high=harvest[2]),
                                price_per_kg=PriceRangeIn(low=price[0], expected=price[1], high=price[2]),
                                cost=CostIn(other_per_acre=cost_per_acre or Decimal(0)),
                                estimate_basis=EstimateBasis.OWN_RECORDS
                                if h_basis in ("said", "actual", "plan")
                                else EstimateBasis.ASSUMPTION,
                            )
                        ],
                    )
                )
            except (AppError, ValidationError):
                calc_call = calc_call.model_copy(update={"ok": False, "error_code": "calculation_failed"})
                return reply(render("tool_failed", lang), calls=[calc_call])
            t, it = result_plan.totals, result_plan.items[0]
            production = it.production_kg.expected
            ranged_h = harvest[0] != harvest[2]
            per_text = (
                f"{inr(harvest[0])}\u2013{inr(harvest[2])} ({ESTIMATE_TEXT['expected'][kn]} {inr(harvest[1])})"
                if ranged_h
                else inr(harvest[1])
            )
            lines.append(
                ESTIMATE_TEXT["harvest"][kn].format(
                    per=per_text, basis=BASIS_WORDS[h_basis][kn], acres=_n(acres), total=inr(production)
                )
            )
            if quote is not None:
                lines.append(_market_line(quote, kn))
            revenue = (
                f"₹{inr(t.revenue.low)}\u2013₹{inr(t.revenue.high)} ({ESTIMATE_TEXT['expected'][kn]} ₹{inr(t.revenue.expected)})"
                if t.revenue.low != t.revenue.high
                else f"₹{inr(t.revenue.expected)}"
            )
            lines.append(
                ESTIMATE_TEXT["income"][kn].format(
                    kg=inr(production), price=inr(price[1]), basis=BASIS_WORDS[p_basis][kn], revenue=revenue
                )
            )
            income_total = t.revenue.expected
            profit = income_total - cost_total if cost_total is not None else None
            profit_low = t.margin.low if cost_total is not None else None
            if crop is not None and crop.reference_yield_kg_per_acre and h_basis in ("said", "actual"):
                ref = Decimal(crop.reference_yield_kg_per_acre)
                cv = Decimal(crop.reference_yield_cv or Decimal("0.25"))
                low, high = ref * (1 - cv), ref * (1 + cv)
                if harvest[1] < low / 10 or harvest[1] > high * 3:  # e.g. "20 kg" for an acre of tomato
                    key = "actual_low" if h_basis == "actual" and harvest[1] < low else "check_unit"
                    lines.append(
                        ESTIMATE_TEXT[key][kn].format(per=inr(harvest[1]), crop=label, low=inr(low), high=inr(high))
                    )
        if cost_total is None:
            lines.append(ESTIMATE_TEXT["need_cost"][kn])
        else:
            lines.append(
                ESTIMATE_TEXT["cost"][kn].format(
                    per=inr(cost_per_acre or Decimal(0)), acres=_n(acres), total=inr(cost_total), basis=c_basis
                )
            )
            assert profit is not None
            lines.append(
                ESTIMATE_TEXT["profit"][kn].format(
                    income=inr(income_total), cost=inr(cost_total), profit=_money_signed(profit, kn)
                )
            )
            if production:
                per_kg = cost_total / production
                lines.append(ESTIMATE_TEXT["break_even"][kn].format(kg=inr(per_kg), quintal=inr(per_kg * 100)))
            if calc_call is not None and profit_low is not None and profit_low != profit:
                lines.append(ESTIMATE_TEXT["pessimistic"][kn].format(low=_money_signed(profit_low, kn)))
        lines.append(ESTIMATE_TEXT["risks"][kn])
        lines.append(ESTIMATE_TEXT["not_guarantee"][kn])
        sources = [SourceRef(name="Income calculator (your numbers)", kind=DataKind.ESTIMATE)]
        if quote is not None:
            sources.append(SourceRef(name="AGMARKNET mandi prices (data.gov.in)", kind=DataKind.MEASURED))
        if h_basis == "catalogue":
            sources.append(SourceRef(name="Catalogue reference yield (not your farm)", kind=DataKind.ASSUMPTION))
        return reply(
            "\n".join(lines),
            kind="records",
            calls=[calc_call] if calc_call else [],
            sources=sources,
            disclaimer=DISCLAIMER[lang],
        )

    def _suitability(
        self,
        user: CurrentUser,
        req: AssistantRequest,
        rec: Recognised,
        lang: str,
        understood: Literal["rules", "alternative", "context", "local_model"],
        heard: str | None,
    ) -> AssistantResponse:
        """'Can I grow carrots on my farm?': the crop's catalogue needs + what is recorded about the farm (place, soil,
        irrigation) + labelled general advice. Never a yes/no verdict; missing farm details are asked for."""
        kn = lang == "kn"
        crop = self._find_crop(req.message) or self._context_crop(req)  # "is it suitable?" after "I grow mango"
        if crop is None:
            return self._reply(rec, lang, render("suitability_need_crop", lang), understood=understood, heard=heard)
        label = (crop.local_name or crop.name) if kn else crop.name
        farms = list(self._farms.list_owned(user.user_id, include_archived=False, limit=100, offset=0).items)
        crop_line = render(
            "suitability_crop",
            lang,
            crop=label,
            season=crop.season.value.replace("_", " ") if crop.season else UNKNOWN_WORD[kn],
            days=crop.typical_duration_days,
            water=_n(crop.water_need_mm) if crop.water_need_mm is not None else UNKNOWN_WORD[kn],
        )
        missing: list[str] = []
        place = ""
        soils: list[str] = []
        if not farms:
            farm_line = render("no_farm", lang)
            missing.append(MISSING["farm"][kn])
        else:
            farm = farms[0]
            plots = list(
                self._repo.session.scalars(
                    select(FarmPlot).where(FarmPlot.farm_id.in_([f.id for f in farms]), FarmPlot.is_active.is_(True))
                )
            )
            soils = sorted({p.soil_type.value for p in plots if p.soil_type})
            irrigation = sorted({p.irrigation_type.value for p in plots if p.irrigation_type})
            place = ", ".join(x for x in (farm.village, farm.district, farm.state) if x)
            if not soils:
                missing.append(MISSING["soil"][kn])
            if not irrigation:
                missing.append(MISSING["irrigation"][kn])
            if not place and farm.latitude is None:
                missing.append(MISSING["location"][kn])
            farm_line = render(
                "suitability_farm",
                lang,
                farm=farm.name,
                place=place or UNKNOWN_WORD[kn],
                soils=", ".join(soils) or UNKNOWN_WORD[kn],
                irrigation=", ".join(irrigation) or UNKNOWN_WORD[kn],
            )
        answer = f"{crop_line} {farm_line}"
        if missing:
            answer += " " + render("suitability_missing", lang, missing=", ".join(missing))
        answer += " " + render("suitability_no_verdict", lang)
        kind: Literal["records", "general_ai", "mixed", "guidance"] = "records"
        sources = [SourceRef(name="Crop catalogue and your farm records", kind=DataKind.MEASURED)]
        llm_used = False
        if self._llm_general and self._llm.is_available():
            question = (
                f"What growing conditions does {crop.name} need (soil type and pH, temperature, season, water)? "
                f"The farmer's plots have {', '.join(soils) or 'unknown'} soil in {place or 'Karnataka, India'}. "
                "Say which conditions they should check. Do not promise that it will grow well there."
            )
            advice = self._general_answer(
                AssistantRequest(message=question[:1000], language="en", history=[], alternatives=[]), "en"
            )
            if advice is not None and advice != UNCLEAR:
                answer += f"\n\n{ADVICE_LABEL[kn]}: {advice}"
                kind, llm_used = "mixed", True
                sources = [*sources, *self._ai_source()]
        return self._reply(
            rec,
            lang,
            answer,
            understood=understood,
            heard=heard,
            kind=kind,
            sources=sources,
            llm_used=llm_used,
            disclaimer=MIXED_DISCLAIMER[lang] if llm_used else DISCLAIMER[lang],
        )

    def _ai_source(self) -> list[SourceRef]:
        model = getattr(self._llm, "model", None) or self._llm.name
        return [SourceRef(name=f"Local AI model ({model})", kind="ai_general")]

    def _pick_farm(self, user: CurrentUser, farm_id: uuid.UUID | None, *, need_coordinates: bool) -> Any:
        page = self._farms.list_owned(user.user_id, include_archived=False, limit=100, offset=0)
        if farm_id is not None:
            match = [f for f in page.items if f.id == farm_id]
            if not match:
                raise NotFoundError("Farm not found")
            return match[0]
        candidates = [f for f in page.items if f.latitude is not None] if need_coordinates else list(page.items)
        chosen = candidates or list(page.items)
        return chosen[0] if chosen else None

    def _latest(self, user: CurrentUser, cycle_id: uuid.UUID, total: int) -> Any:
        page = self._predictions.list_for_cycle(user.user_id, cycle_id, limit=min(total, 100), offset=0)
        return max(page.items, key=lambda p: p.version)

    def _maybe_reword(self, answer: str, facts: Facts, lang: str) -> tuple[str, bool]:
        if (
            not self._llm_reword
            or facts.key in ("unknown", "allocation_refused", "reminder_confirm", "not_for_role")
            or not self._llm.is_available()
        ):
            return answer, False
        values = [*facts.values.values(), answer]
        system = (
            "You reword farm assistant answers for farmers. Use ONLY the facts given. Do not add any number, date, "
            "price, weather value or quantity that is not in the facts. Keep it under 80 words. "
            f"Answer in {'Kannada' if lang == 'kn' else 'English'}."
        )
        try:
            out = self._llm.generate(
                LLMRequest(
                    messages=(
                        LLMMessage("system", system),
                        LLMMessage(
                            "user",
                            f"Facts: {json.dumps(facts.values, default=str, ensure_ascii=False)}\nDraft answer: {answer}",
                        ),
                    ),
                    temperature=0.1,
                    max_tokens=200,
                )
            )
        except AppError:
            return answer, False
        if grounded(out.text, values):
            return out.text.strip(), True
        logger.info("LLM answer rejected by the grounding check")
        return answer, False


UNDERSTOOD_AS = "ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡ ಪ್ರಶ್ನೆ / Understood as"
UNCLEAR = "\x00unclear"  # sentinel from _general_answer: the model judged the message garbled or fragmentary
# scripts other than Latin/Kannada (the local models drift into them mid-sentence); such answers are dropped
OTHER_SCRIPTS = re.compile("[\u0900-\u0c7f\u0d00-\u0dff\u0e00-\u0e7f]")
IST = timedelta(hours=5, minutes=30)
DAY_WORDS = {"today": ("today", "ಇಂದು"), "tomorrow": ("tomorrow", "ನಾಳೆ")}
FRESHNESS = {
    WeatherStatus.FRESH: ("latest forecast", "ಇತ್ತೀಚಿನ ಮುನ್ಸೂಚನೆ"),
    WeatherStatus.STALE: ("older saved forecast, may be out of date", "ಹಳೆಯ ಉಳಿಸಿದ ಮುನ್ಸೂಚನೆ, ಹಳತಾಗಿರಬಹುದು"),
    WeatherStatus.UNAVAILABLE: ("not available", "ಲಭ್ಯವಿಲ್ಲ"),
}
MISSING = {
    "farm": ("your farm (add it in My Farm)", "ನಿಮ್ಮ ಜಮೀನು (ನನ್ನ ಜಮೀನು ವಿಭಾಗದಲ್ಲಿ ಸೇರಿಸಿ)"),
    "soil": ("the soil type of your plots (a soil test helps)", "ನಿಮ್ಮ ಪ್ಲಾಟ್‌ಗಳ ಮಣ್ಣಿನ ಪ್ರಕಾರ (ಮಣ್ಣು ಪರೀಕ್ಷೆ ಸಹಾಯಕ)"),
    "irrigation": ("the water source / irrigation", "ನೀರಿನ ಮೂಲ / ನೀರಾವರಿ"),
    "location": ("the farm location", "ಜಮೀನಿನ ಸ್ಥಳ"),
}
UNKNOWN_WORD = ("not recorded", "ದಾಖಲಾಗಿಲ್ಲ")
ADVICE_LABEL = ("General advice (AI, not from your records)", "ಸಾಮಾನ್ಯ ಸಲಹೆ (AI, ನಿಮ್ಮ ದಾಖಲೆಗಳಿಂದ ಅಲ್ಲ; ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ)")
_WEATHER_DAY = (
    ("tomorrow", re.compile(r"\btomorrow\b|ನಾಳೆ")),
    ("today", re.compile(r"\btoday\b|\bnow\b|ಇಂದು|ಇವತ್ತು|ಈಗ")),
)


PLAN_WORDS = re.compile(r"\bplans?\b|planner|ಯೋಜನೆ|ಪ್ಲಾನ್")
ESTIMATE_FOLLOW_UPS = frozenset(
    {
        Intent.UNKNOWN,
        Intent.CROP_ESTIMATE,
        Intent.EXPENSE_SUMMARY,
        Intent.INCOME_PLANS,
        Intent.HARVEST_PREDICTION,
        Intent.CROP_STATEMENT,
    }
)
BASIS_WORDS = {
    "said": ("you said", "ನೀವು ಹೇಳಿದ್ದು"),
    "plan": ("your saved plan", "ನಿಮ್ಮ ಉಳಿಸಿದ ಯೋಜನೆ"),
    "catalogue": ("catalogue estimate, not your farm", "ಕ್ಯಾಟಲಾಗ್ ಅಂದಾಜು, ನಿಮ್ಮ ಜಮೀನಿನದಲ್ಲ"),
    "actual": ("what you harvested", "ನೀವು ಕೊಯ್ಲು ಮಾಡಿದ್ದು"),
    "market": ("latest market price", "ಇತ್ತೀಚಿನ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ"),
    "records": (
        "your recorded expenses for this crop, season sown {sown}, {n} entries; may be incomplete",
        "ಈ ಬೆಳೆಗೆ ನೀವು ದಾಖಲಿಸಿದ ಖರ್ಚು, {sown} ಬಿತ್ತನೆಯ ಹಂಗಾಮು, {n} ನಮೂದುಗಳು; ಅಪೂರ್ಣವಾಗಿರಬಹುದು",
    ),
}
MARKET_NOTE = {
    "off": (
        "Live market prices are not switched on in this app (a free data.gov.in API key is needed), so I need your expected price.",
        "ಈ ಆ್ಯಪ್‌ನಲ್ಲಿ ನೇರ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಇನ್ನೂ ಸಕ್ರಿಯವಾಗಿಲ್ಲ (ಉಚಿತ data.gov.in API ಕೀ ಬೇಕು), ಆದ್ದರಿಂದ ನಿಮ್ಮ ನಿರೀಕ್ಷಿತ ಬೆಲೆ ಹೇಳಿ.",
    ),
    "failed": (
        "The government market-price service did not answer just now and no recent {crop} price is stored.",
        "ಸರ್ಕಾರಿ ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಸೇವೆ ಈಗ ಉತ್ತರಿಸಲಿಲ್ಲ ಮತ್ತು ಇತ್ತೀಚಿನ {crop} ಬೆಲೆ ಉಳಿಸಿಲ್ಲ.",
    ),
    "none": (
        "No {crop} price was reported in your district, state or nearby states in the last 30 days (AGMARKNET).",
        "ಕಳೆದ 30 ದಿನಗಳಲ್ಲಿ ನಿಮ್ಮ ಜಿಲ್ಲೆ, ರಾಜ್ಯ ಅಥವಾ ನೆರೆ ರಾಜ್ಯಗಳಲ್ಲಿ {crop} ಬೆಲೆ ವರದಿಯಾಗಿಲ್ಲ (AGMARKNET).",
    ),
}
ASK = {
    "acres": ("how many acres", "ಎಷ್ಟು ಎಕರೆ"),
    "crop_or_harvest": ("the crop, or your expected harvest in kg", "ಬೆಳೆ ಯಾವುದು, ಅಥವಾ ನಿರೀಕ್ಷಿತ ಇಳುವರಿ (ಕೆಜಿ)"),
    "harvest": ("your expected harvest in kg per acre", "ಎಕರೆಗೆ ನಿರೀಕ್ಷಿತ ಇಳುವರಿ (ಕೆಜಿ)"),
    "price": ("the selling price per kg", "ಕೆಜಿಗೆ ಮಾರಾಟ ಬೆಲೆ"),
    "cost": ("your cost (per acre or in total)", "ನಿಮ್ಮ ಖರ್ಚು (ಎಕರೆಗೆ ಅಥವಾ ಒಟ್ಟು)"),
    "harvest_scope": ("whether {x} kg is per acre or for all {acres} acres", "{x} ಕೆಜಿ ಎಕರೆಗೆಯೇ ಅಥವಾ ಎಲ್ಲಾ {acres} ಎಕರೆಗೆ ಒಟ್ಟೇ"),
    "cost_scope": (
        "whether ₹{x} is the cost per acre or for all {acres} acres",
        "₹{x} ಎಕರೆಗೆ ಖರ್ಚೇ ಅಥವಾ ಎಲ್ಲಾ {acres} ಎಕರೆಗೆ ಒಟ್ಟೇ",
    ),
    "income_scope": (
        "whether ₹{x} is the income per acre or for all {acres} acres",
        "₹{x} ಎಕರೆಗೆ ಆದಾಯವೇ ಅಥವಾ ಎಲ್ಲಾ {acres} ಎಕರೆಗೆ ಒಟ್ಟೇ",
    ),
}
UNCLEAR_ASK = {
    "mass": ("is {x} the harvest (per acre or in total)?", "{x} ಇಳುವರಿಯೇ (ಎಕರೆಗೆ ಅಥವಾ ಒಟ್ಟು)?"),
    "money": ("is {x} your cost, your income, or the price per kg?", "{x} ನಿಮ್ಮ ಖರ್ಚೇ, ಆದಾಯವೇ, ಅಥವಾ ಕೆಜಿಗೆ ಬೆಲೆಯೇ?"),
    "plain": ("is {x} a price, a cost, an income or a quantity?", "{x} ಬೆಲೆಯೇ, ಖರ್ಚೇ, ಆದಾಯವೇ ಅಥವಾ ಪ್ರಮಾಣವೇ?"),
    "input": (
        "is {x} the seed, seedlings or fertiliser you used? For the income I need your harvest (kg) and price.",
        "{x} ನೀವು ಬಳಸಿದ ಬೀಜ, ಸಸಿ ಅಥವಾ ಗೊಬ್ಬರವೇ? ಆದಾಯಕ್ಕೆ ನಿಮ್ಮ ಇಳುವರಿ (ಕೆಜಿ) ಮತ್ತು ಬೆಲೆ ಬೇಕು.",
    ),
}
ESTIMATE_TEXT = {
    "title": ("Calculation for {acres} acre(s){crop}:", "{acres} ಎಕರೆ{crop} ಲೆಕ್ಕ:"),
    "expected": ("expected", "ನಿರೀಕ್ಷಿತ"),
    "harvest": (
        "• Harvest: {per} kg per acre ({basis}) × {acres} acre(s) = {total} kg",
        "• ಇಳುವರಿ: ಎಕರೆಗೆ {per} ಕೆಜಿ ({basis}) × {acres} ಎಕರೆ = {total} ಕೆಜಿ",
    ),
    "income": (
        "• Income: {kg} kg × ₹{price} per kg ({basis}) = {revenue}",
        "• ಆದಾಯ: {kg} ಕೆಜಿ × ಕೆಜಿಗೆ ₹{price} ({basis}) = {revenue}",
    ),
    "income_said": ("• Income: ₹{income} ({basis})", "• ಆದಾಯ: ₹{income} ({basis})"),
    "cost": (
        "• Cost: ₹{per} per acre × {acres} acre(s) = ₹{total} ({basis})",
        "• ಖರ್ಚು: ಎಕರೆಗೆ ₹{per} × {acres} ಎಕರೆ = ₹{total} ({basis})",
    ),
    "profit": ("• Profit: ₹{income} − ₹{cost} = {profit}", "• ಲಾಭ: ₹{income} − ₹{cost} = {profit}"),
    "pessimistic": (
        "If the harvest is at the low end and costs run 10% over, the result would be about {low}.",
        "ಇಳುವರಿ ಕಡಿಮೆ ಮತ್ತು ಖರ್ಚು 10% ಹೆಚ್ಚಾದರೆ ಫಲಿತಾಂಶ ಸುಮಾರು {low}.",
    ),
    "need_cost": (
        "To work out the profit, tell me your cost (per acre or in total).",
        "ಲಾಭ ಲೆಕ್ಕ ಹಾಕಲು ನಿಮ್ಮ ಖರ್ಚು ಹೇಳಿ (ಎಕರೆಗೆ ಅಥವಾ ಒಟ್ಟು).",
    ),
    "check_unit": (
        "Please check: {per} kg per acre is far from the usual {low}–{high} kg for {crop} (1 quintal = 100 kg).",
        "ದಯವಿಟ್ಟು ಪರಿಶೀಲಿಸಿ: ಎಕರೆಗೆ {per} ಕೆಜಿ, {crop} ಸಾಮಾನ್ಯ {low}–{high} ಕೆಜಿಗಿಂತ ತುಂಬಾ ಬೇರೆ (1 ಕ್ವಿಂಟಾಲ್ = 100 ಕೆಜಿ).",
    ),
    "market": (
        "• Market price: ₹{modal} per quintal (modal; range ₹{low}\u2013₹{high}) at {markets}, {place}, reported {date}{age}. Source: AGMARKNET (data.gov.in), wholesale APMC price.",
        "• ಮಾರುಕಟ್ಟೆ ಬೆಲೆ: ಕ್ವಿಂಟಾಲ್‌ಗೆ ₹{modal} (ಸಾಮಾನ್ಯ; ವ್ಯಾಪ್ತಿ ₹{low}\u2013₹{high}), {markets}, {place}, ವರದಿ ದಿನಾಂಕ {date}{age}. ಮೂಲ: AGMARKNET (data.gov.in), ಎಪಿಎಂಸಿ ಸಗಟು ಬೆಲೆ.",
    ),
    "market_fresh": (" (latest)", " (ಇತ್ತೀಚಿನದು)"),
    "market_many": ("{n} markets (median)", "{n} ಮಾರುಕಟ್ಟೆಗಳ ಮಧ್ಯಮ ಬೆಲೆ"),
    "market_old": (" ({days} days old; today's price may differ)", " ({days} ದಿನಗಳ ಹಿಂದಿನದು; ಇಂದಿನ ಬೆಲೆ ಬೇರೆಯಾಗಿರಬಹುದು)"),
    "market_nearby": (
        "no report from your district or state; nearest available",
        "ನಿಮ್ಮ ಜಿಲ್ಲೆ ಅಥವಾ ರಾಜ್ಯದ ವರದಿ ಇಲ್ಲ; ಹತ್ತಿರದ ಲಭ್ಯ",
    ),
    "break_even": (
        "• Break-even price: ₹{kg} per kg (₹{quintal} per quintal); selling below this is a loss.",
        "• ನಷ್ಟವಿಲ್ಲದ ಕನಿಷ್ಠ ಬೆಲೆ: ಕೆಜಿಗೆ ₹{kg} (ಕ್ವಿಂಟಾಲ್‌ಗೆ ₹{quintal}); ಇದಕ್ಕಿಂತ ಕಡಿಮೆ ಮಾರಿದರೆ ನಷ್ಟ.",
    ),
    "actual_low": (
        "Note: {per} kg per acre is far below the usual {low}\u2013{high} kg for {crop}; the calculation uses what you actually harvested.",
        "ಗಮನಿಸಿ: ಎಕರೆಗೆ {per} ಕೆಜಿ, {crop} ಸಾಮಾನ್ಯ {low}\u2013{high} ಕೆಜಿಗಿಂತ ತುಂಬಾ ಕಡಿಮೆ; ಲೆಕ್ಕದಲ್ಲಿ ನೀವು ನಿಜವಾಗಿ ಕೊಯ್ಲು ಮಾಡಿದ್ದನ್ನೇ ಬಳಸಲಾಗಿದೆ.",
    ),
    "risks": (
        "Risks and assumptions: market prices change daily and differ between markets; APMC prices are wholesale, before commission, transport and grading losses unless you included them in your cost; the harvest depends on weather, pests and variety.",
        "ಅಪಾಯಗಳು ಮತ್ತು ಊಹೆಗಳು: ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಪ್ರತಿದಿನ ಬದಲಾಗುತ್ತದೆ ಮತ್ತು ಮಾರುಕಟ್ಟೆಗಳ ನಡುವೆ ಬೇರೆ ಇರುತ್ತದೆ; ಎಪಿಎಂಸಿ ಬೆಲೆ ಸಗಟು ಬೆಲೆ, ಕಮಿಷನ್, ಸಾಗಣೆ ಮತ್ತು ವಿಂಗಡಣೆ ನಷ್ಟ ಸೇರಿಲ್ಲ (ನಿಮ್ಮ ಖರ್ಚಿನಲ್ಲಿ ಸೇರಿಸದಿದ್ದರೆ); ಇಳುವರಿ ಹವಾಮಾನ, ಕೀಟ ಮತ್ತು ತಳಿಯ ಮೇಲೆ ಅವಲಂಬಿತ.",
    ),
    "catalogue_note": (
        "Harvest I would use: {low}–{high} kg per acre ({basis}).",
        "ಬಳಸುವ ಇಳುವರಿ: ಎಕರೆಗೆ {low}–{high} ಕೆಜಿ ({basis}).",
    ),
    "not_guarantee": (
        "This is a calculation from these numbers, not a guarantee.",
        "ಇದು ಈ ಸಂಖ್ಯೆಗಳಿಂದ ಮಾಡಿದ ಲೆಕ್ಕ, ಖಾತರಿ ಅಲ್ಲ.",
    ),
}


def _market_line(q: PriceQuote, kn: bool) -> str:
    """Where the price came from: market(s), place, reporting date and age. Never presented as today's price
    unless it was reported in the last few days."""
    age = ESTIMATE_TEXT["market_fresh"][kn] if q.fresh else ESTIMATE_TEXT["market_old"][kn].format(days=q.age_days)
    many = len(q.markets) > 3
    markets = ESTIMATE_TEXT["market_many"][kn].format(n=len(q.markets)) if many else ", ".join(q.markets)
    if q.variety and q.variety.lower() not in ("other", q.commodity.lower()):
        markets = f"{markets} ({q.variety})"
    place = q.place if q.scope != "nearby" else f"{ESTIMATE_TEXT['market_nearby'][kn]}: {q.place}"
    return ESTIMATE_TEXT["market"][kn].format(
        modal=inr(q.modal_per_quintal),
        low=inr(q.min_per_quintal),
        high=inr(q.max_per_quintal),
        markets=markets,
        place=place,
        date=q.arrival_date.strftime("%d %b %Y"),
        age=age,
    )


def _money_signed(value: Decimal, kn: bool) -> str:
    """₹1,50,000 for a profit; a minus sign, the amount and "(a loss)" for a loss."""
    if value < 0:
        return f"\u2212₹{inr(-value)} ({'ನಷ್ಟ' if kn else 'a loss'})"
    return f"₹{inr(value)}"


def _per_acre(value: Decimal, scope: str | None, acres: Decimal | None) -> Decimal | None:
    """A per-acre figure; None when it is not said whether the number is per acre or for the whole area."""
    if scope == "acre" or (acres is not None and acres == 1):
        return value
    if scope == "total" and acres:
        return value / acres
    return None


def estimate_unclear(inputs: Inputs, lang: str) -> str:
    kn = lang == "kn"
    asks = " ".join(UNCLEAR_ASK[u.kind][kn].format(x=u.text) for u in inputs.unclear)
    if kn:
        return f"ಈ ಸಂಖ್ಯೆಗಳ ಅರ್ಥ ತಿಳಿಸಿ: {asks} ಉದಾಹರಣೆಗೆ ಹೇಳಿ: 'ಎಕರೆಗೆ 20 ಕ್ವಿಂಟಾಲ್ ಇಳುವರಿ, ಒಟ್ಟು ಖರ್ಚು 50000' ಅಥವಾ 'ಕೆಜಿಗೆ 20 ರೂಪಾಯಿ'."
    return (
        f"I need to know what your numbers mean: {asks} For example say: 'harvest 20 quintal per acre, total cost "
        "50000' or 'price 20 rupees per kg'."
    )


def estimate_missing(missing: list[str], crop: str | None, lang: str) -> str:
    kn = lang == "kn"
    what = (f"{crop} " if crop else "") + ("ಲೆಕ್ಕಕ್ಕೆ" if kn else "")
    if kn:
        return f"{what} ನನಗೆ ಇನ್ನೂ ಬೇಕು: {', '.join(missing)}. ನಾನು ಬೆಲೆ, ಇಳುವರಿ ಅಥವಾ ಖರ್ಚನ್ನು ಊಹಿಸುವುದಿಲ್ಲ.".strip()
    subject = f"the {crop} estimate" if crop else "the estimate"
    return f"For {subject} I still need: {', '.join(missing)}. I do not guess prices, harvests or costs."


STATEMENT_TEXT = {
    "need_crop": (
        "Which crop are you growing? Say, for example: 'I am growing mango on my farm.'",
        "ನೀವು ಯಾವ ಬೆಳೆ ಬೆಳೆಯುತ್ತಿದ್ದೀರಿ? ಉದಾಹರಣೆಗೆ: 'ನಾನು ನನ್ನ ಜಮೀನಿನಲ್ಲಿ ಮಾವು ಬೆಳೆಯುತ್ತಿದ್ದೇನೆ.'",
    ),
    "noted": ("Noted: you are growing {crop}.", "ಸರಿ, ನೀವು {crop} ಬೆಳೆಯುತ್ತಿದ್ದೀರಿ."),
    "recorded": ("Your records show {crop} on: {records}.", "ನಿಮ್ಮ ದಾಖಲೆಗಳಲ್ಲಿ {crop}: {records}."),
    "not_recorded": (
        "{crop} is not in your records yet: add it in My Farm (plot, then add crop) so weather, harvest and price "
        "tools can use it.",
        "{crop} ಇನ್ನೂ ನಿಮ್ಮ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ: ಹವಾಮಾನ, ಕೊಯ್ಲು ಮತ್ತು ಬೆಲೆ ಮಾಹಿತಿಗೆ ಬಳಸಲು 'ನನ್ನ ಜಮೀನು' ವಿಭಾಗದಲ್ಲಿ (ಪ್ಲಾಟ್, ನಂತರ ಬೆಳೆ ಸೇರಿಸಿ) ಸೇರಿಸಿ.",
    ),
    "next": (
        "You can ask next, for example: 'Is it suitable for my farm?', 'What would be my profit per acre?', or check a "
        "leaf photo in Crop health.",
        "ಮುಂದೆ ಕೇಳಬಹುದು, ಉದಾಹರಣೆಗೆ: 'ನನ್ನ ಜಮೀನಿಗೆ ಅದು ಸೂಕ್ತವೇ?', 'ಎಕರೆಗೆ ಲಾಭ ಎಷ್ಟು?', ಅಥವಾ 'ಬೆಳೆ ಆರೋಗ್ಯ'ದಲ್ಲಿ ಎಲೆಯ ಫೋಟೋ ಪರಿಶೀಲಿಸಿ.",
    ),
}
RECOMMEND_TEXT = {
    "no_farm": (
        "To suggest crops I need your farm: add your farm in My Farm (place, and if you know them, soil type and water "
        "source).",
        "ಬೆಳೆ ಸಲಹೆಗೆ ನಿಮ್ಮ ಜಮೀನಿನ ಮಾಹಿತಿ ಬೇಕು: 'ನನ್ನ ಜಮೀನು' ವಿಭಾಗದಲ್ಲಿ ಜಮೀನು ಸೇರಿಸಿ (ಸ್ಥಳ, ಗೊತ್ತಿದ್ದರೆ ಮಣ್ಣು ಮತ್ತು ನೀರಿನ ಮೂಲ). (add your farm)",
    ),
    "title": (
        "Crops to consider for {farm} ({place}) in the {season} season:",
        "{farm} ({place}) ಗೆ {season} ಹಂಗಾಮಿನಲ್ಲಿ ಪರಿಗಣಿಸಬಹುದಾದ ಬೆಳೆಗಳು:",
    ),
    "item": (
        "• {crop}: {season}, about {days} days, water about {water} mm",
        "• {crop}: {season}, ಸುಮಾರು {days} ದಿನ, ನೀರು ಸುಮಾರು {water} ಮಿ.ಮೀ.",
    ),
    "none": (
        "• No catalogue crop fits these limits; ask your Raitha Samparka Kendra.",
        "• ಈ ಮಿತಿಗಳಿಗೆ ಹೊಂದುವ ಬೆಳೆ ಪಟ್ಟಿಯಲ್ಲಿಲ್ಲ; ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರವನ್ನು ಕೇಳಿ.",
    ),
    "basis": (
        "Based on: your farm record (place {place}; soil: {soil}; water: {water}), today's season and the crop "
        "catalogue's seasons and water needs. Not based on soil tests, market prices or yields.",
        "ಆಧಾರ: ನಿಮ್ಮ ಜಮೀನಿನ ದಾಖಲೆ (ಸ್ಥಳ {place}; ಮಣ್ಣು: {soil}; ನೀರು: {water}), ಇಂದಿನ ಹಂಗಾಮು ಮತ್ತು ಬೆಳೆ ಪಟ್ಟಿಯ ಹಂಗಾಮು ಹಾಗೂ "
        "ನೀರಿನ ಅಗತ್ಯ. ಮಣ್ಣು ಪರೀಕ್ಷೆ, ಮಾರುಕಟ್ಟೆ ಬೆಲೆ ಅಥವಾ ಇಳುವರಿ ಆಧಾರವಲ್ಲ.",
    ),
    "water_rule": (
        "Only crops needing about {mm} mm of water or less are listed (catalogue values), because no irrigation is "
        "known.",
        "ನೀರಾವರಿ ತಿಳಿದಿಲ್ಲದ ಕಾರಣ ಸುಮಾರು {mm} ಮಿ.ಮೀ. ಅಥವಾ ಕಡಿಮೆ ನೀರು ಬೇಕಾದ ಬೆಳೆಗಳನ್ನು ಮಾತ್ರ ಪಟ್ಟಿ ಮಾಡಲಾಗಿದೆ.",
    ),
    "soil_note": (
        "Soil noted; the catalogue has no soil-suitability data, so check the list against your soil with the Raitha "
        "Samparka Kendra.",
        "ಮಣ್ಣು ಗಮನಿಸಲಾಗಿದೆ; ಬೆಳೆ ಪಟ್ಟಿಯಲ್ಲಿ ಮಣ್ಣು ಹೊಂದಾಣಿಕೆ ಮಾಹಿತಿ ಇಲ್ಲ, ಆದ್ದರಿಂದ ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರದಲ್ಲಿ ಪರಿಶೀಲಿಸಿ.",
    ),
    "already": ("You already grow or mentioned: {crops}.", "ನೀವು ಈಗಾಗಲೇ ಬೆಳೆಯುತ್ತಿರುವ ಅಥವಾ ಹೇಳಿದ ಬೆಳೆ: {crops}."),
    "ask": (
        "To narrow this down, tell me {missing} (for example: 'red soil, borewell').",
        "ಇನ್ನಷ್ಟು ಸರಿಯಾಗಿ ಹೇಳಲು {missing} ತಿಳಿಸಿ (ಉದಾಹರಣೆಗೆ: 'ಕೆಂಪು ಮಣ್ಣು, ಬೋರ್‌ವೆಲ್').",
    ),
    "ask_soil": ("your soil type", "ನಿಮ್ಮ ಮಣ್ಣಿನ ಪ್ರಕಾರ"),
    "ask_water": ("your water source", "ನೀರಿನ ಮೂಲ"),
    "and": (" and ", " ಮತ್ತು "),
    "not_advice": (
        "This is a shortlist to discuss with your Raitha Samparka Kendra, not a guarantee.",
        "ಇದು ರೈತ ಸಂಪರ್ಕ ಕೇಂದ್ರದೊಂದಿಗೆ ಚರ್ಚಿಸಲು ಒಂದು ಪಟ್ಟಿ, ಖಾತರಿ ಅಲ್ಲ.",
    ),
}
SEASON_WORDS = {
    "kharif": ("kharif (Jun–Sep)", "ಮುಂಗಾರು (ಜೂನ್–ಸೆಪ್ಟೆಂಬರ್)"),
    "rabi": ("rabi (Oct–Feb)", "ಹಿಂಗಾರು (ಅಕ್ಟೋಬರ್–ಫೆಬ್ರವರಿ)"),
    "summer": ("summer (Mar–May)", "ಬೇಸಿಗೆ (ಮಾರ್ಚ್–ಮೇ)"),
    "year_round": ("any season", "ಯಾವುದೇ ಹಂಗಾಮು"),
}
NOT_FIELD_GROUPS = frozenset({"mushrooms", "agroforestry", "ornamental"})
_SOIL_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("red", ("red", "ಕೆಂಪು")),
    ("black", ("black", "ಕಪ್ಪು", "ಎರೆ")),
    ("sandy", ("sandy", "sand", "ಮರಳು")),
    ("loamy", ("loam", "ಗೋಡು")),
    ("clay", ("clay", "ಜೇಡಿ")),
    ("laterite", ("laterite",)),
    ("alluvial", ("alluvial",)),
)
_WATER_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rainfed", ("rainfed", "rain-fed", "rain fed", "ಮಳೆಯಾಶ್ರಿತ", "ಮಳೆ ಆಶ್ರಿತ", "ಮಳೆ ಆಧಾರಿತ")),
    ("borewell", ("borewell", "bore well", "bore-well", "ಬೋರ್ವೆಲ್", "ಬೋರ್‌ವೆಲ್", "ಕೊಳವೆ ಬಾವಿ")),
    ("canal", ("canal", "ಕಾಲುವೆ")),
    ("drip", ("drip", "ಹನಿ")),
    ("sprinkler", ("sprinkler", "ತುಂತುರು")),
    ("tank", ("tank", "ಕೆರೆ")),
    ("river", ("river", "ನದಿ")),
)


def soil_and_water(text: str) -> tuple[str | None, str | None]:
    """Soil type and water source the person SAID ('red soil, borewell'); None where not said."""
    low = text.lower()
    soil = next((k for k, words in _SOIL_WORDS if any(re.search(rf"(^|\W){re.escape(w)}", low) for w in words)), None)
    water = next((k for k, words in _WATER_WORDS if any(w in low for w in words)), None)
    return soil, water


def season_now(month: int) -> str:
    """Karnataka cropping seasons by calendar month (IST)."""
    if 6 <= month <= 9:
        return "kharif"
    if month >= 10 or month <= 2:
        return "rabi"
    return "summer"


def weather_day(text: str) -> Literal["today", "tomorrow"] | None:
    low = text.lower()
    if _WEATHER_DAY[0][1].search(low):
        return "tomorrow"
    if _WEATHER_DAY[1][1].search(low):
        return "today"
    return None


def _dec(value: object) -> Decimal | None:
    try:
        d = Decimal(str(value)) if value not in (None, "") else None
    except ArithmeticError:
        return None
    return d if d is not None and d > 0 else None


PERSONAL_CLAIM = re.compile(
    r"\byour (own )?(farm|field|plot|crop|crops|harvest|yield|expenses?|spending|orders?|income|plans?|land)\b"
    r"[^.!?]*\b(is|are|was|were|has|have|had|will|shows?)\b[^.!?]*\d",
    re.IGNORECASE,
)
# "I can't see your farm records" adds nothing: the app answers record questions itself (and, in a mixed answer, the
# facts from the records are printed right above the general part)
NO_ACCESS = re.compile(
    r"\b(?:i(?:'m| am)? (?:not able|unable) to (?:see|access|view)|i (?:don't|do not|cannot|can't) (?:have access"
    r"|see|view|access|know)\b[^.!?]*\b(?:your|the exact)|i'?m not aware of your|i (?:don't|do not) have (?:any )?"
    r"(?:information|details|data) (?:about|on) your)",
    re.IGNORECASE,
)
UNCERTAIN = re.compile(
    r"approx|typical|usually|about|around|roughly|vary|varies|depends|check|label|officer|kendra", re.IGNORECASE
)
LEADING_CONNECTIVE = re.compile(r"^(?:however|but|that said)\s*,?\s*", re.IGNORECASE)
CAUTION = "Numbers here are approximate: check the product label or your local agriculture officer before acting."


def checked_general_answer(text: str) -> str | None:
    """Keep a model answer only if it is usable: drop sentences that claim facts about the asker's own records
    (the model never saw them), mark numbers as approximate, cap the length."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [x for x in sentences if x and not PERSONAL_CLAIM.search(x) and not NO_ACCESS.search(x)]
    out = " ".join(kept).strip()
    # after a removed "I can't see your records" sentence the answer can start mid-thought ("However, ...")
    out = LEADING_CONNECTIVE.sub("", out, count=1)
    out = out[:1].upper() + out[1:]
    if not out:
        return None
    if re.search(r"\d", out) and not UNCERTAIN.search(out):
        out = f"{out} {CAUTION}"
    return out[:1500]


def _n(x: Decimal | float | int) -> str:
    """Human number: no trailing zeros, max 1 decimal."""
    d = Decimal(str(x)).quantize(Decimal("0.1"))
    return f"{d.normalize():f}" if d != d.to_integral() else f"{d.to_integral():f}"
