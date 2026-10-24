from dataclasses import dataclass


@dataclass(frozen=True)
class FeedItem:
    id: str
    title: str
    text: str
    industry_prefix: str | None = None
    application_status: str | None = None
