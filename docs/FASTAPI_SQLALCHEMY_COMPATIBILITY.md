# FastAPI + SQLAlchemy + Uvicorn Compatibility Checklist
**Generated:** 2026-02-06  
**Purpose:** Data sanity & version compatibility verification

---

## 📚 Official Documentation Links

| Tool | Official Docs | Current Stable Version |
|------|---------------|------------------------|
| **FastAPI** | https://fastapi.tiangolo.com/ | 0.115.x+ (requires Python 3.9+) |
| **SQLAlchemy** | https://docs.sqlalchemy.org/ | 2.0.46 (January 21, 2026) |
| **Uvicorn** | https://www.uvicorn.org/ | 0.34.x+ |

---

## ✅ Pre-Installation Checklist

### 1. Python Version Compatibility
```
✓ Python 3.9+ REQUIRED (FastAPI 0.115+ dropped Python 3.8)
✓ Python 3.10+ RECOMMENDED for better async/await support
✓ Python 3.11+ OPTIMAL for performance improvements
```

### 2. Core Dependencies Matrix

| Package | Minimum | Recommended | Notes |
|---------|---------|-------------|-------|
| `fastapi` | 0.100.0 | 0.115.0+ | Pydantic v2 support |
| `sqlalchemy` | 2.0.0 | 2.0.46+ | 1.x is EOL |
| `uvicorn` | 0.23.0 | 0.34.0+ | `uvicorn[standard]` for prod |
| `pydantic` | 2.0.0 | 2.5.0+ | FastAPI requires v2+ |
| `starlette` | 0.27.0 | 0.41.0+ | FastAPI dependency |

---

## 🔧 Installation Commands

### Development Environment
```bash
# Standard installation
pip install "fastapi[standard]" sqlalchemy uvicorn

# With async database support
pip install "fastapi[standard]" sqlalchemy uvicorn asyncpg aiomysql

# With all recommended extras
pip install "fastapi[all]" sqlalchemy "uvicorn[standard]" alembic
```

### Production Environment
```bash
# Production-grade installation
pip install fastapi sqlalchemy "uvicorn[standard]" gunicorn

# Note: Use gunicorn with uvicorn workers for production
# pip install uvicorn-worker  (deprecated module replaced)
```

---

## 🧪 Compatibility Verification Script

```python
# compatibility_check.py
import sys

def check_versions():
    print(f"Python: {sys.version}")
    
    try:
        import fastapi
        print(f"✓ FastAPI: {fastapi.__version__}")
    except ImportError:
        print("✗ FastAPI: NOT INSTALLED")
    
    try:
        import sqlalchemy
        print(f"✓ SQLAlchemy: {sqlalchemy.__version__}")
    except ImportError:
        print("✗ SQLAlchemy: NOT INSTALLED")
    
    try:
        import uvicorn
        print(f"✓ Uvicorn: {uvicorn.__version__}")
    except ImportError:
        print("✗ Uvicorn: NOT INSTALLED")
    
    try:
        import pydantic
        print(f"✓ Pydantic: {pydantic.__version__}")
    except ImportError:
        print("✗ Pydantic: NOT INSTALLED")
    
    try:
        import starlette
        print(f"✓ Starlette: {starlette.__version__}")
    except ImportError:
        print("✗ Starlette: NOT INSTALLED")

if __name__ == "__main__":
    check_versions()
```

---

## ⚠️ Critical Compatibility Notes

### SQLAlchemy 2.0 Migration (BREAKING CHANGES)
```python
# ❌ SQLAlchemy 1.x style (REMOVED in 2.0)
from sqlalchemy import create_engine
engine = create_engine("sqlite:///test.db")
Session = sessionmaker(bind=engine)
session = Session()
query = session.query(User).filter(User.id == 1).first()

# ✅ SQLAlchemy 2.0 style (REQUIRED)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
engine = create_engine("sqlite:///test.db")
with Session(engine) as session:
    query = session.execute(select(User).where(User.id == 1)).scalar_one()
```

### FastAPI + SQLAlchemy 2.0 Integration
```python
# ✅ Recommended pattern for FastAPI + SQLAlchemy 2.0
from fastapi import FastAPI, Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

app = FastAPI()
engine = create_engine("sqlite:///./test.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/users/{user_id}")
def read_user(user_id: int, db: Session = Depends(get_db)):
    # Use new 2.0 select() syntax
    from sqlalchemy import select
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    return user
```

### Async SQLAlchemy + FastAPI Pattern
```python
# ✅ Async support with SQLAlchemy 2.0
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

app = FastAPI()
engine = create_async_engine("postgresql+asyncpg://user:pass@localhost/db")
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(Item).where(Item.id == item_id))
        return result.scalar_one_or_none()
```

---

## 🚨 Known Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| `ModuleNotFoundError: 'uvicorn.workers'` | Deprecated in uvicorn 0.30+ | Install `uvicorn-worker` separately |
| `PydanticImportError` | Pydantic v1 vs v2 mismatch | Ensure all packages use Pydantic v2 |
| `AttributeError: 'Session' object has no attribute 'query'` | SQLAlchemy 2.0 removed session.query() | Use `session.execute(select(...))` |
| `ImportError: cannot import name 'Mapped'` | SQLAlchemy < 2.0 | Upgrade to SQLAlchemy 2.0+ |
| `TypeError: 'async for' requires an object with __aiter__` | Missing async driver | Install `asyncpg` or `aiomysql` |

---

## 🐳 Docker Production Setup

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Production command (Gunicorn + Uvicorn workers)
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "main:app"]
```

### requirements.txt (Production)
```
fastapi==0.115.6
sqlalchemy==2.0.46
uvicorn[standard]==0.34.0
pydantic==2.10.4
alembic==1.14.0
asyncpg==0.30.0
psycopg2-binary==2.9.10
gunicorn==23.0.0
uvicorn-worker==0.2.0
```

---

## 📋 Validation Checklist

- [ ] Python 3.9+ installed (`python --version`)
- [ ] FastAPI 0.100+ installed (uses Pydantic v2)
- [ ] SQLAlchemy 2.0+ installed (1.x is EOL)
- [ ] Uvicorn 0.23+ installed
- [ ] Pydantic v2 installed (`pip show pydantic`)
- [ ] Async database driver installed (if using async)
- [ ] SQLAlchemy 2.0 syntax used (no `session.query()`)
- [ ] `uvicorn[standard]` installed for production (includes uvloop, httptools)
- [ ] `gunicorn` + `uvicorn-worker` for multi-process deployment
- [ ] Database URL format validated

---

## 🔗 Additional Resources

- **FastAPI Tutorial:** https://fastapi.tiangolo.com/tutorial/
- **SQLAlchemy 2.0 Tutorial:** https://docs.sqlalchemy.org/en/20/tutorial/
- **SQLAlchemy Migration Guide:** https://docs.sqlalchemy.org/en/20/changelog/migration_20.html
- **Uvicorn Settings:** https://www.uvicorn.org/settings/
- **FastAPI SQLAlchemy Guide:** https://fastapi.tiangolo.com/tutorial/sql-databases/

---

**Status:** ✅ Checklist Generated  
**Last Updated:** 2026-02-06
