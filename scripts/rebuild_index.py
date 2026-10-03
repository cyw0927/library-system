import argparse
import json

from app.db.session import get_session_factory
from app.services.rag_service import index_paragraphs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index a bounded batch of changed paragraphs")
    parser.add_argument("--provider", choices=["local", "openai"], default="local")
    parser.add_argument("--book-id", type=int)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--confirm-cost", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 2000:
        parser.error("limit must be between 1 and 2000")
    if args.provider == "openai" and not args.confirm_cost:
        parser.error("OpenAI indexing incurs charges; pass --confirm-cost")
    with get_session_factory()() as session:
        print(json.dumps(index_paragraphs(session, args.provider, args.book_id, args.limit)))
