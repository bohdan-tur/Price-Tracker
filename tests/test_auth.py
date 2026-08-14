from httpx import AsyncClient

from app.core.rate_limit import limiter
from app.core.security import create_refresh_token


async def test_register_user_success(async_client: AsyncClient, create_test_user):
    payload = {"email": "new_user@test.com", "password": "secret_password"}

    response = await async_client.post("/auth/register", json=payload)

    assert response.status_code == 201
    assert response.json()["email"] == "new_user@test.com"


async def test_register_user_already_exists(
    async_client: AsyncClient, create_test_user
):
    await create_test_user(email="exists@test.com")

    payload = {"email": "exists@test.com", "password": "some_password"}

    response = await async_client.post("/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


async def test_login_success(async_client: AsyncClient, create_test_user):

    await create_test_user(email="login@test.com")

    payload = {"username": "login@test.com", "password": "secret123"}

    response = await async_client.post("/auth/login", data=payload)

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(async_client: AsyncClient, create_test_user):
    await create_test_user(email="wrong@test.com")

    payload = {"username": "wrong@test.com", "password": "wrongpassword"}

    response = await async_client.post("/auth/login", data=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect password"


async def test_login_rate_limit(async_client: AsyncClient):
    limiter.reset()
    payload = {
        "username": "rate-limit-test@example.com",
        "password": "wrong-password",
    }

    try:
        for _ in range(5):
            response = await async_client.post("/auth/login", data=payload)
            assert response.status_code == 401

        response = await async_client.post("/auth/login", data=payload)

        assert response.status_code == 429
    finally:
        limiter.reset()


async def test_protected_route_without_token(async_client):

    response = await async_client.get("/items/")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


async def test_protected_route_with_invalid_token(async_client):

    headers = {"Authorization": "Bearer fake_invalid_token_123"}
    response = await async_client.get("/items/", headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


async def test_refresh_token_success(async_client, create_test_user):

    user = await create_test_user(email="refresh@test.com")

    valid_refresh_token = create_refresh_token(data={"sub": str(user.id)})

    response = await async_client.post(
        "/auth/refresh_token", json={"refresh_token": valid_refresh_token}
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_refresh_token_invalid_token(async_client, create_test_user):

    await create_test_user(email="invalid@test.com")

    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake_payload.fake_signature"

    response = await async_client.post(
        "/auth/refresh_token", json={"refresh_token": fake_token}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"
