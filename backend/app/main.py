from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .routers import auth, etfs, watchlist, portfolio, tags, chat

settings = get_settings()

app = FastAPI(
    title="ETF Atlas API",
    description="ETF 정보 관리 및 인사이트 제공 서비스",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:9600", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(etfs.router, prefix="/api/etfs", tags=["ETFs"])
app.include_router(watchlist.router, prefix="/api/watchlist", tags=["Watchlist"])
app.include_router(portfolio.router, prefix="/api/portfolios", tags=["Portfolio"])
app.include_router(tags.router, prefix="/api/tags", tags=["Tags"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])


@app.get("/")
async def root():
    return {"message": "Welcome to ETF Atlas API", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
