import json

from app.db.session import get_session_factory
from app.services.qa_service import run_qa

if __name__ == "__main__":
    with get_session_factory()() as session:
        print(json.dumps(run_qa(session), ensure_ascii=False))
