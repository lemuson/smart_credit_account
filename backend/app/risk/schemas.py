from decimal import Decimal

from pydantic import Field, model_validator

from app.common import Schema


class ScoreWeights(Schema):
    base: int = Field(default=500, ge=300, le=850)
    age_established: int = Field(default=60, ge=-300, le=300)
    age_medium: int = Field(default=30, ge=-300, le=300)
    age_young: int = Field(default=-20, ge=-300, le=300)
    revenue_high: int = Field(default=80, ge=-300, le=300)
    revenue_medium: int = Field(default=40, ge=-300, le=300)
    revenue_low: int = Field(default=-60, ge=-300, le=300)
    margin_high: int = Field(default=50, ge=-300, le=300)
    margin_medium: int = Field(default=20, ge=-300, le=300)
    margin_low: int = Field(default=-80, ge=-300, le=300)
    history_clean: int = Field(default=100, ge=-300, le=300)
    history_minor_delay: int = Field(default=20, ge=-300, le=300)
    history_overdue: int = Field(default=-100, ge=-300, le=300)
    tax_clean: int = Field(default=40, ge=-300, le=300)
    tax_debt: int = Field(default=-30, ge=-300, le=300)


class RiskRules(Schema):
    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    category_a_min: int = Field(default=750, ge=300, le=850)
    category_b_min: int = Field(default=650, ge=300, le=850)
    category_c_min: int = Field(default=550, ge=300, le=850)
    category_b_surcharge: Decimal = Field(default=Decimal("1.5"), ge=0, le=30, decimal_places=2)
    category_c_surcharge: Decimal = Field(default=Decimal("3.5"), ge=0, le=30, decimal_places=2)
    category_c_limit_factor: Decimal = Field(default=Decimal("0.70"), gt=0, le=1, decimal_places=4)
    yellow_burden: Decimal = Field(default=Decimal("0.50"), gt=0, le=1, decimal_places=4)
    max_burden: Decimal = Field(default=Decimal("0.70"), gt=0, le=1, decimal_places=4)
    reduced_limit_target: Decimal = Field(default=Decimal("0.65"), gt=0, le=1, decimal_places=4)
    yellow_surcharge: Decimal = Field(default=Decimal("1.5"), ge=0, le=30, decimal_places=2)
    min_business_age_months: int = Field(default=6, ge=6, le=1200)
    max_current_overdue_days: int = Field(default=30, ge=0, le=30)
    historical_default_days: int = Field(default=90, ge=30, le=90)

    @model_validator(mode="after")
    def ordered_thresholds(self):
        if not self.category_c_min < self.category_b_min < self.category_a_min:
            raise ValueError("risk score thresholds must be strictly ordered")
        if not self.yellow_burden <= self.reduced_limit_target <= self.max_burden:
            raise ValueError("burden thresholds must be ordered")
        if self.category_b_surcharge > self.category_c_surcharge:
            raise ValueError("category C surcharge must be >= category B")
        return self


class RiskPolicyRead(Schema):
    version: int
    rules: RiskRules
    demonstration_only: bool = True


class RiskPolicyUpdate(Schema):
    expected_version: int = Field(ge=0)
    rules: RiskRules
