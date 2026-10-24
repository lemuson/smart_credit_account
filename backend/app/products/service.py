from app.common import fail
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

    def search(self, purpose, amount, term):
        return self.dao.search(purpose, amount, term)

    def update(self, product_id, data):
        product = self.get(product_id)
        for field, value in data.model_dump().items():
            setattr(product, field, value)
        self.dao.session.flush()
        return product
