from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.dependencies import db_dependency, get_current_user
from app.core.rate_limit import limiter
from app.models.item import Item, ItemStatus
from app.models.price_history import PriceHistory
from app.models.user import User
from app.schemas.item import ItemCreate, ItemResponse
from app.schemas.pagination import PaginationParams, get_pagination
from app.schemas.price_history import PriceHistoryResponse
from app.services.scraper import UnsafeScraperURLError, validate_scraper_url
from app.worker.tasks import scrape_item

router = APIRouter(prefix="/items", tags=["items"])


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_item(
    request: Request,
    item: ItemCreate,
    db: db_dependency,
    user: User = Depends(get_current_user),
) -> Item:

    try:
        await validate_scraper_url(str(item.url))
    except UnsafeScraperURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    new_item = Item(
        title=item.title,
        url=str(item.url),
        current_price=None,
        target_price=item.target_price,
        currency="UAH",
        status=ItemStatus.PENDING,
        user_id=user.id,
    )
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)

    scrape_item.delay(new_item.id)

    return new_item


@router.get("/", response_model=list[ItemResponse], status_code=status.HTTP_200_OK)
async def get_my_items(
    db: db_dependency,
    current_user: User = Depends(get_current_user),
    pagination: PaginationParams = Depends(get_pagination),
) -> list[Item]:
    query = await db.execute(
        select(Item)
        .where(Item.user_id == current_user.id)
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return list(query.scalars().all())


@router.get(
    "/{item_id}/history",
    response_model=list[PriceHistoryResponse],
    status_code=status.HTTP_200_OK,
)
async def get_item_history(
    item_id: int,
    db: db_dependency,
    current_user: User = Depends(get_current_user),
    pagination: PaginationParams = Depends(get_pagination),
) -> list[PriceHistory]:
    owned_item_id = await db.scalar(
        select(Item.id).where(
            Item.id == item_id,
            Item.user_id == current_user.id,
        )
    )

    if owned_item_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Item not found",
        )

    query = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.item_id == item_id)
        .order_by(PriceHistory.recorded_at.desc())
        .limit(pagination.limit)
        .offset(pagination.offset)
    )
    return list(query.scalars().all())


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: int, db: db_dependency, current_user: User = Depends(get_current_user)
) -> None:
    query = await db.execute(
        select(Item).where(Item.id == item_id, Item.user_id == current_user.id)
    )
    item = query.scalar_one_or_none()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found"
        )

    await db.delete(item)
    await db.commit()
