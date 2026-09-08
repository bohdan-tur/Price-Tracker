from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.dependencies import (
    db_dependency,
    get_current_superuser,
    get_current_user,
)
from app.core.security import get_password_hash, verify_password
from app.models.user import User
from app.schemas.pagination import PaginationParams, get_pagination
from app.schemas.password_change import PasswordChangeSchema
from app.schemas.user import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def get_current_logged_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    return user


@router.patch("/me/password", status_code=status.HTTP_200_OK)
async def change_password(
    user: Annotated[User, Depends(get_current_user)],
    password_change: PasswordChangeSchema,
    db: db_dependency,
):
    if not verify_password(password_change.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid old password")

    user.hashed_password = get_password_hash(password_change.new_password)
    await db.commit()

    return {"msg": "Password updated successfully"}


@router.delete("/me", status_code=status.HTTP_200_OK)
async def delete_my_account(
    user: Annotated[User, Depends(get_current_user)], db: db_dependency
):
    user.is_active = False
    await db.commit()
    return {"msg": "User deactivated successfully"}


@router.get(
    "/",
    response_model=list[UserResponse],
    dependencies=[Depends(get_current_superuser)],
)
async def get_all_users(
    db: db_dependency,
    pagination: PaginationParams = Depends(get_pagination),
) -> list[User]:
    query = await db.execute(
        select(User).offset(pagination.offset).limit(pagination.limit)
    )
    return list(query.scalars().all())


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(get_current_superuser)],
)
async def get_user_by_id(user_id: int, db: db_dependency) -> User:
    query = await db.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


@router.patch("/{user_id}/deactivate", dependencies=[Depends(get_current_superuser)])
async def deactivate_user(user_id: int, db: db_dependency):
    query = await db.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change status of a superuser",
        )

    user.is_active = False
    await db.commit()
    return {"msg": f"User {user_id} deactivated successfully"}


@router.patch("/{user_id}/activate", dependencies=[Depends(get_current_superuser)])
async def activate_user(user_id: int, db: db_dependency):
    query = await db.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change status of a superuser",
        )

    user.is_active = True
    await db.commit()
    return {"msg": f"User {user_id} activated successfully"}


@router.delete("/{user_id}", dependencies=[Depends(get_current_superuser)])
async def delete_user_hard(user_id: int, db: db_dependency):
    query = await db.execute(select(User).where(User.id == user_id))
    user = query.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete a superuser"
        )

    await db.delete(user)
    await db.commit()
    return {"msg": f"User {user_id} was deleted"}
