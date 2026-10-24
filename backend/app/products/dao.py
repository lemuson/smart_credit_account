from sqlalchemy import select

from app.products.models import Product


class ProductDAO:
    def __init__(self, session):
        self.session = session

    def get(self, product_id):
        return self.session.get(Product, product_id)

    def list(self, offset=0, limit=50):
        return self.session.scalars(
            select(Product)
            .where(Product.active.is_(True))
            .order_by(Product.id)
            .offset(offset)
            .limit(limit)
        ).all()

    def search(self, purpose=None, amount=None, term=None):
        query = select(Product).where(Product.active.is_(True))
        if amount is not None:
            query = query.where(Product.min_amount <= amount, Product.max_amount >= amount)
        if term is not None:
            query = query.where(Product.min_term_months <= term, Product.max_term_months >= term)
        rows = self.session.scalars(query.order_by(Product.annual_rate, Product.id)).all()
        return [row for row in rows if purpose is None or purpose in row.purposes]

    def create(self, data):
        product = Product(**data)
        self.session.add(product)
        self.session.flush()
        return product
