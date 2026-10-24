from datetime import date
from decimal import Decimal

from app.applications.decision import business_age, monthly_payment
from app.common import fail
from app.loans.obligations import credit_obligations
from app.products.dao import ProductDAO


class ProductService:
    def __init__(self, session):
        self.dao = ProductDAO(session)

    def get(self, product_id):
        product = self.dao.get(str(product_id))
        if not product:
            fail(404, "PRODUCT_NOT_FOUND")
        return product

    def create(self, data):
        return self.dao.create(data.model_dump())

    def search(self, purpose=None, amount=None, term=None, profile=None):
        rows = self.dao.search(purpose, amount, term)
        if profile is None:
            return rows
        registration = profile.company.get("registration_date")
        age = business_age(date.fromisoformat(registration), date.today()) if registration else 0
        financials = profile.financials
        revenue = Decimal(str(financials.get("annual_revenue", 0)))
        eligible = []
        for row in rows:
            if age < row.min_business_age_months or revenue < row.min_annual_revenue:
                continue
            if row.collateral_required and not financials.get("has_collateral"):
                continue
            if amount is not None and term is not None:
                debt = Decimal(
                    credit_obligations(self.dao.session, profile.user_id, financials)[
                        "total_monthly_payments"
                    ]
                )
                payment = monthly_payment(amount, row.annual_rate, term)
                if revenue <= 0 or (debt + payment) / (revenue / 12) > row.max_debt_burden:
                    continue
            eligible.append(row)
        return eligible

    def update(self, product_id, data):
        product = self.get(product_id)
        for field, value in data.model_dump().items():
            setattr(product, field, value)
        self.dao.session.flush()
        return product
