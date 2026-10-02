"""
users.py - Endpoints about the logged-in user.
"""

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models import UserProfile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfile)
async def read_my_profile(user: dict = Depends(get_current_user)):
    # get_current_user has already checked the token and loaded (or created)
    # this user's record. response_model=UserProfile filters it down to the
    # public fields - internal ones like cognito_sub and _id are not sent.
    return user
