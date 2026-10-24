"""Model-based what-if simulation without causal claims."""

from __future__ import annotations

from .features import FEATURE_COLUMNS
from .inference_schema import CreditApplication, WhatIfResponse
from .local_inference import LIMITATIONS_WARNING, LocalInferenceService


def compare_applications(
    service: LocalInferenceService,
    original: CreditApplication,
    alternative: CreditApplication,
) -> WhatIfResponse:
    original_values = original.model_dump()
    alternative_values = alternative.model_dump()
    changed_fields = [
        name for name in FEATURE_COLUMNS if original_values[name] != alternative_values[name]
    ]
    if not changed_fields:
        raise ValueError("What-if requires at least one changed model feature")
    original_response = service.score(original)
    alternative_response = service.score(alternative)
    delta = (
        alternative_response.score.probability - original_response.score.probability
    ) * 100.0
    return WhatIfResponse(
        changed_fields=changed_fields,
        original=original_response,
        alternative=alternative_response,
        delta_percentage_points=round(delta, 4),
        limitations_warning=(
            LIMITATIONS_WARNING
            + " What-if — только повторный расчёт модели для изменённой анкеты; он не обещает, "
            "что соответствующее реальное действие изменит решение банка."
        ),
    )

