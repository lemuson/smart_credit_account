#!/usr/bin/env python3
"""Run trusted local scoring or a what-if simulation and print structured JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from ml_scoring.inference_schema import CreditApplication  # noqa: E402
from ml_scoring.local_inference import (  # noqa: E402
    LocalInferenceService,
    UnsupportedInputRangeError,
    validation_error_payload,
)
from ml_scoring.what_if import compare_applications  # noqa: E402


def _boolean(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annual-revenue", type=float, required=True)
    parser.add_argument(
        "--credit-history", choices=["good", "average", "bad", "none"], required=True
    )
    parser.add_argument("--business-age-months", type=int, required=True)
    parser.add_argument("--loan-amount", type=float, required=True)
    parser.add_argument("--has-collateral", type=_boolean, required=True)
    parser.add_argument("--loan-term-months", type=int, required=True)
    parser.add_argument("--age", type=int)
    parser.add_argument("--what-if-annual-revenue", type=float)
    parser.add_argument(
        "--what-if-credit-history", choices=["good", "average", "bad", "none"]
    )
    parser.add_argument("--what-if-business-age-months", type=int)
    parser.add_argument("--what-if-loan-amount", type=float)
    parser.add_argument("--what-if-has-collateral", type=_boolean)
    parser.add_argument("--what-if-loan-term-months", type=int)
    return parser


def _application_values(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "annual_revenue": args.annual_revenue,
        "credit_history": args.credit_history,
        "business_age_months": args.business_age_months,
        "loan_amount": args.loan_amount,
        "has_collateral": args.has_collateral,
        "loan_term_months": args.loan_term_months,
        "age": args.age,
    }


def main() -> None:
    args = _parser().parse_args()
    try:
        service = LocalInferenceService.from_artifact_directory(ML_ROOT / "models")
        original_values = _application_values(args)
        original = CreditApplication.model_validate(original_values)
        replacements = {
            name: getattr(args, f"what_if_{name}")
            for name in (
                "annual_revenue",
                "credit_history",
                "business_age_months",
                "loan_amount",
                "has_collateral",
                "loan_term_months",
            )
            if getattr(args, f"what_if_{name}") is not None
        }
        if replacements:
            alternative = CreditApplication.model_validate(
                {**original_values, **replacements}
            )
            result = compare_applications(service, original, alternative)
        else:
            result = service.score(original)
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    except ValidationError as error:
        print(json.dumps(validation_error_payload(error), ensure_ascii=False, indent=2))
        raise SystemExit(2) from error
    except UnsupportedInputRangeError as error:
        payload = {
            "status": "unsupported_range",
            "score": None,
            "message": str(error),
            "issues": error.issues,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()

