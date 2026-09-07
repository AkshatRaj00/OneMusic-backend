# OneMusic Backend

A production‑grade Python backend for the OneMusic platform, providing RESTful APIs for user management, music catalog, and streaming services.

## Architecture Overview
The service follows a modular, layered architecture: **API layer** (FastAPI) handles HTTP requests, **service layer** encapsulates business logic, **repository layer** abstracts data access (SQLAlchemy + PostgreSQL), and **utility modules** provide authentication, validation, and background tasks. Dependency injection and Pydantic models ensure type safety and testability.

## Key Features
- **FastAPI** with automatic OpenAPI documentation.  
- **JWT‑based authentication** and role‑based access control.  
- **SQLAlchemy ORM** with async support for PostgreSQL.  
- **Background workers** for audio processing using Celery.  
- Comprehensive **unit and integration tests** with pytest.  

## Installation
```bash
git clone https://github.com/AkshatRaj00/OneMusic-backend.git
cd OneMusic-backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```
Set required environment variables (`DATABASE_URL`, `SECRET_KEY`, etc.) or copy `.env.example` to `.env` and edit accordingly.

## Usage Example
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000/docs` for interactive API documentation. Example request to register a user:

```http
POST /api/v1/users/register
Content-Type: application/json

{
  "username": "alice",
  "email": "alice@example.com",
  "password": "StrongPass!123"
}
```

## License
This project is licensed under the **MIT License** – see the [LICENSE](LICENSE) file for details.