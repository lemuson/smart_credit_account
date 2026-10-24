from __future__ import annotations

import argparse
import asyncio
import json

from app.messaging.demo import publish_demo


async def run(message: str) -> None:
    request = await publish_demo(message)
    print(json.dumps(request.model_dump(mode="json"), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one demo chat request")
    parser.add_argument("message", nargs="?", default="Какие кредиты подходят моему ИП?")
    args = parser.parse_args()
    asyncio.run(run(args.message))


if __name__ == "__main__":
    main()
