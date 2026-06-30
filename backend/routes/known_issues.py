from fastapi import APIRouter
from backend.data.mock_known_issues import KNOWN_ISSUES

router = APIRouter()


@router.get("/known-issues")
def get_known_issues():
    return KNOWN_ISSUES
