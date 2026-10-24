#!/usr/bin/env python3
"""Load the trusted local final model and run a schema-checked example prediction."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ML_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_ROOT / "src"))

from ml_scoring.inference import load_trusted_bundle  # noqa: E402


def main() -> None:
    models_dir = ML_ROOT / "models"
    manifest = json.loads((models_dir / "manifest.json").read_text(encoding="utf-8"))
    model = load_trusted_bundle(
        models_dir / "credit_scoring_model.joblib",
        expected_sha256=manifest["final_bundle_sha256"],
        trusted=True,
    )
    application = pd.DataFrame(
        [
            {
                "annual_revenue": 5_000_000.0,
                "credit_history": "average",
                "business_age_months": 36,
                "loan_amount": 1_500_000.0,
                "has_collateral": False,
                "loan_term_months": 24,
            }
        ]
    )
    probability = float(model.predict_proba(application)[0, 1])
    prediction = int(model.predict(application)[0])
    print(json.dumps({"probability": probability, "prediction": prediction}, indent=2))


if __name__ == "__main__":
    main()
