# 📈 Price Tracker

![Python](https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136.1-green?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-red?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.4.0-brightgreen?logo=celery&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.49-red?logo=sqlalchemy&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker&logoColor=white)

A modern RESTful price tracking API built with FastAPI, PostgreSQL, Redis, and Celery. The project scrapes product prices from e-commerce websites, keeps a full price history, and uses an asynchronous architecture with background task processing, JWT-based authentication, and a fully containerized development workflow with Docker Compose.

## 📚 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Architecture](#-architecture)
- [Project Structure](#-project-structure)
- [Environment Variables](#️-environment-variables)
- [Docker Services](#-docker-services)
- [Getting Started](#-getting-started)
- [Available Services](#-available-services)
- [API Usage Example](#-api-usage-example)
- [API Endpoints](#-api-endpoints)
- [Database Seeding](#-database-seeding)
- [Testing](#-testing)
- [Background Tasks](#-background-tasks)
- [Web Scraping Strategy](#-web-scraping-strategy)
- [Security](#-security)
- [Authentication](#-authentication)
- [Author](#-author)

## 📋 Overview

Price Tracker is a backend application for monitoring product prices across e-commerce websites. It is designed as an asynchronous API service with a modular structure, background scraping jobs, and a multi-strategy price extraction engine.

The project includes:

- JWT-based authentication with access and refresh tokens
- Item tracking endpoints with automatic price scraping
- Full price history per item
- PostgreSQL integration with async SQLAlchemy
- Redis-backed Celery task processing
- Alembic database migrations
- SSRF-protected web scraper
- Admin panel for user management

## ✨ Features

**🔐 JWT Authentication**
- Access and refresh tokens
- Configurable expiration settings
- Token-based protected endpoints

**🔒 Password Security**
- Argon2 password hashing

**📉 Price Tracking**
- Add items by URL and target price
- Automatic price scraping on item creation
- Full price history stored per item

**⏱ Background Automation**
- Celery beat scheduler refreshes prices for all tracked items daily at 3 AM UTC
- Celery worker executes the scheduled refresh jobs asynchronously

**🛡 Admin Panel**
- User listing, status control, and account management

**🗄 Database Migrations**
- Alembic-based schema versioning

**🐳 Containerized Development**
- Multi-service Docker Compose setup
- Separate containers for API, database, Redis, and Celery

## 🛠 Tech Stack

### Backend
- **Python 3.13**
- **FastAPI 0.136.1**
- **Pydantic** — data validation and settings management

### Database & ORM
- **PostgreSQL 15**
- **SQLAlchemy 2.0.49** — asynchronous ORM
- **asyncpg** — asynchronous PostgreSQL driver
- **Alembic** — database migration management

### Background Tasks & Caching
- **Celery 5.4.0** — task queue for scheduled price updates
- **Redis 7** — message broker and cache

### Authentication & Security
- **JWT (python-jose)** — access + refresh tokens
- **Argon2** — password hashing

### Web Scraping
- **BeautifulSoup4, lxml, httpx** — scraping stack

### Testing
- **Pytest**, **pytest-asyncio**, **pytest-cov**

### DevOps & Tooling
- **Docker & Docker Compose**

## 🏗 Architecture

The project runs as a multi-container application and separates responsibilities across dedicated services.

**Main services**
- `api` — FastAPI application
- `db` — main PostgreSQL database
- `test_db` — isolated PostgreSQL database for tests
- `redis` — broker/cache used by Celery
- `celery_worker` — Celery worker executing scraping tasks
- `celery_beat` — Celery beat scheduler for daily price updates

**High-level flow**

```
Client
  ↓
FastAPI API
  ├── PostgreSQL (users, items, price history)
  ├── Redis (broker / cache)
  └── Celery
       ├── celery_worker (scrapes prices)
       └── celery_beat (schedules daily updates)
```

## 📁 Project Structure

```
price-tracker/
├── app/
│   ├── main.py                       # FastAPI application entry point
│   ├── api/
│   │   ├── dependencies.py           # Dependency injection (Auth)
│   │   └── routers/
│   │       ├── auth.py               # Authentication endpoints
│   │       ├── health.py             # Health check endpoint
│   │       ├── item.py               # Item CRUD operations
│   │       └── user.py               # User management
│   ├── core/
│   │   ├── config.py                 # Settings management
│   │   ├── logging.py                # Logging configuration
│   │   └── security.py               # JWT & password hashing
│   ├── database/
│   │   ├── db.py                     # Database session management
│   │   └── seed.py                   # Database seeding logic
│   ├── models/
│   │   ├── item.py                   # Item SQLAlchemy model
│   │   ├── price_history.py          # Price history SQLAlchemy model
│   │   └── user.py                   # User SQLAlchemy model
│   ├── schemas/
│   │   ├── health.py                 # Health check Pydantic schemas
│   │   ├── item.py                   # Item Pydantic schemas
│   │   ├── pagination.py            # Pagination Pydantic schemas
│   │   ├── password_change.py        # Password change Pydantic schema
│   │   ├── price_history.py          # Price history Pydantic schema
│   │   ├── refresh_token.py          # Refresh token Pydantic schema
│   │   └── user.py                   # User Pydantic schemas
│   ├── services/
│   │   └── scraper.py                # Core web scraping service
│   └── worker/
│       └── worker.py                 # Celery worker & beat tasks
├── migration/
│   ├── env.py                        # Alembic environment configuration
│   └── versions/                     # Database migrations history
├── tests/
│   ├── conftest.py                   # Pytest fixtures
│   ├── test_auth.py                  # Authentication tests
│   ├── test_health.py                # Health check tests
│   ├── test_items.py                 # Item CRUD tests
│   ├── test_scraper.py               # Web scraper tests
│   ├── test_users.py                 # User management tests
│   └── test_worker.py                # Background worker tests
├── .env.example                      # Environment variables example
├── alembic.ini                       # Alembic configuration
├── docker-compose.yaml               # Docker Compose infrastructure setup
├── Dockerfile                        # Docker image
├── pytest.ini                        # Pytest configuration
└── requirements.txt                  # Python dependencies
```

## ⚙️ Environment Variables

Example configuration:

```env
# JWT
ACCESS_TOKEN_SECRET_KEY=your_access_secret_key_change_this
REFRESH_TOKEN_SECRET_KEY=your_refresh_secret_key_change_this
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRES_MINUTES=20
REFRESH_TOKEN_EXPIRES_DAYS=14
DEBUG=False

# Database
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=price_tracker
DATABASE_URL=postgresql+asyncpg://postgres:your_secure_password@db:5432/price_tracker
SEED_ADMIN_PASSWORD=your_secure_admin_password_here
SEED_USER_PASSWORD=your_secure_user_password_here

# Test Database
TEST_POSTGRES_USER=test_user
TEST_POSTGRES_PASSWORD=test_password_secret
TEST_POSTGRES_DB=test_price_tracker
TEST_DATABASE_URL=postgresql+asyncpg://test_user:test_password_secret@db:5432/test_price_tracker

# CORS
CORS_ORIGINS='["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"]'
```

**Key variables**

| Variable | Description |
|---|---|
| `DATABASE_URL` | Main PostgreSQL connection string |
| `TEST_DATABASE_URL` | Database used during tests |
| `ACCESS_TOKEN_SECRET_KEY` | Secret key for access tokens |
| `REFRESH_TOKEN_SECRET_KEY` | Secret key for refresh tokens |
| `ACCESS_TOKEN_EXPIRES_MINUTES` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRES_DAYS` | Refresh token lifetime |
| `SEED_ADMIN_PASSWORD` | Password used for the seeded admin account |
| `SEED_USER_PASSWORD` | Password used for the seeded test accounts |
| `CORS_ORIGINS` | Comma-separated list of allowed origins |
| `DEBUG` | Enables debug mode |

## 🐳 Docker Services

The application is designed to run using Docker Compose.

| Service | Container Name | Port (host:container) | Purpose |
|---|---|---|---|
| `api` | `price_tracker_api` | `8000:8000` | FastAPI application |
| `db` | — | `5433:5432` | Main PostgreSQL database |
| `test_db` | — | `5434:5432` | Isolated PostgreSQL database for tests |
| `redis` | `price_tracker_redis` | `6380:6379` | Redis broker / cache |
| `celery_worker` | `price_tracker_worker` | — | Executes scraping tasks |
| `celery_beat` | `price_tracker_beat` | — | Schedules the daily price update job |

> **Note:** `db` and `test_db` are exposed on non-default host ports (`5433`, `5434`) to avoid clashing with a local PostgreSQL instance. Inside the Docker network, services still connect on the default port `5432`.

## 🚀 Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/bohdan-tur/price-tracker.git
cd price-tracker
```

### 2. Create the environment file

```bash
cp .env.example .env
```

Then update the `.env` file with your local configuration.

### 3a. Run with Docker Compose (recommended)

```bash
docker-compose up --build
```

### 3b. Manual setup

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 4. Check service status

```bash
docker-compose ps
```

## 🌐 Available Services

Once the application is running, the following endpoints should be available:

| Service | URL |
|---|---|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| PostgreSQL (main) | localhost:5433 |
| PostgreSQL (test) | localhost:5434 |
| Redis | localhost:6380 |

## 💻 API Usage Example

**Track a new item**

**Request**

```http
POST /items/
```

```json
{
  "title": "Awesome Laptop Pro 2026",
  "url": "https://example-shop.com/product/awesome-laptop"
}
```

**Response — 201 Created**

```json
{
  "id": 1,
  "title": "Awesome Laptop Pro 2026",
  "url": "https://example-shop.com/product/awesome-laptop",
  "current_price": 1050.00,
  "user_id": 5,
  "price_histories": []
}
```

> **Note:** The price is fetched **synchronously** on item creation  so `current_price` is already populated in the response. The Celery beat scheduler only handles subsequent, periodic price refreshes (daily at 3 AM UTC) — it does not populate the initial price.

## 🔌 API Endpoints

**Auth**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/auth/register` | User registration |
| POST | `/auth/login` | User login |
| POST | `/auth/refresh_token` | Refresh access token |

**User Management**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/users/me` | Get current user profile |
| PATCH | `/users/me/password` | Change password |
| DELETE | `/users/me/` | Deactivate account |
| GET | `/users/` | List all users (Admin only) |
| GET | `/users/{user_id}` | Get user by ID (Admin only) |
| PATCH | `/users/{user_id}/deactivate` | Deactivate user (Admin only) |
| PATCH | `/users/{user_id}/activate` | Activate user (Admin only) |
| DELETE | `/users/{user_id}` | Delete user (Admin only) |

**Items & Tracking**

| Method | Endpoint | Description |
|---|---|---|
| POST | `/items/` | Create a new tracked item |
| GET | `/items/` | List user's tracked items |
| DELETE | `/items/{item_id}` | Delete an item |

**System**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe |

## 🗄 Database Seeding

Database seeding is **automatic** — it runs during application startup in the `lifespan` function of `main.py`.

This creates the following test accounts:

- `admin@price-tracker.com` (Superuser)
- `user4@example.com`
- `user5@example.com`

## 🧪 Testing

**Run tests**

```bash
pytest tests/
```

## 📬 Background Tasks

Background processing is handled with Celery and Redis.

**Included services**
- `celery_worker` — executes the scheduled price-refresh job
- `celery_beat` — schedules the daily refresh job (3 AM UTC)

**Typical use cases for background tasks include:**
- Refreshing prices for all tracked items on a daily schedule

> Note: the price shown right after creating an item is **not** fetched by Celery — it's fetched synchronously in the request itself, before the response is returned.

## 🕷 Web Scraping Strategy

The application uses a robust, multi-strategy approach to extract prices from various e-commerce platforms:

1. **JSON-LD Structured Data** — extracts clean, structured product data directly from page metadata
2. **Meta Tags** — scans for standard e-commerce tags (e.g. `product:price:amount`)
3. **CSS Selectors** — fallback extraction using common commerce classes (e.g. `.product_price_current`, `.price--current`)

## 🔒 Security

- **SSRF Protection** — secures the web scraper against Server-Side Request Forgery attacks
- **Argon2 Hashing** — state-of-the-art password hashing
- **URL Validation** — strict validation of targets before initiating any scraping requests
- **CORS Configuration** — secure cross-origin resource sharing middleware

## 🔐 Authentication

The application uses JWT-based authentication with separate settings for access and refresh tokens.

**Authentication configuration**

```env
ALGORITHM=HS256
ACCESS_TOKEN_SECRET_KEY=your_access_secret_key_change_this
REFRESH_TOKEN_SECRET_KEY=your_refresh_secret_key_change_this
ACCESS_TOKEN_EXPIRES_MINUTES=20
REFRESH_TOKEN_EXPIRES_DAYS=14
```

**Supported token types**
- **Access token** — short-lived token for protected requests
- **Refresh token** — longer-lived token used to issue a new access token

Passwords are hashed using Argon2.

## 👤 Author

[Bohdan Turevych](https://www.linkedin.com/in/bohdan-turevych)

* GitHub: [@bohdan-tur](https://github.com/bohdan-tur)
* LinkedIn: [Bohdan Turevych](https://www.linkedin.com/in/bohdan-turevych)
