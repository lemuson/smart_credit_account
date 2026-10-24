from app.common import Schema


class FeedItemRead(Schema):
    id: str
    title: str
    text: str
    industry_prefix: str | None
    application_status: str | None


class FeedRead(Schema):
    demonstration_only: bool = True
    source: str = "local_editorial_recommendations"
    items: list[FeedItemRead]
