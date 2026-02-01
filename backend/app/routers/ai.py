from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..agents.recommender import ETFRecommenderAgent
from ..utils.jwt import get_current_user_id

router = APIRouter()


class RecommendationRequest(BaseModel):
    query: str
    watchlist_id: Optional[int] = None


class SignalResponse(BaseModel):
    etf_code: str
    etf_name: str
    signal_type: str  # buy, sell, hold
    confidence: float
    reason: str


class InsightResponse(BaseModel):
    title: str
    content: str
    etfs: List[str]


class RecommendationResponse(BaseModel):
    signals: List[SignalResponse]
    insights: List[InsightResponse]
    summary: str


@router.post("/recommend", response_model=RecommendationResponse)
async def get_recommendations(
    request: RecommendationRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    try:
        agent = ETFRecommenderAgent(db)
        result = agent.analyze(request.query, user_id, request.watchlist_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals", response_model=List[SignalResponse])
async def get_market_signals(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """워치리스트 기반 시장 신호 분석"""
    try:
        agent = ETFRecommenderAgent(db)
        signals = agent.get_watchlist_signals(user_id)
        return signals
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insights", response_model=List[InsightResponse])
async def get_market_insights(db: Session = Depends(get_db)):
    """전체 시장 인사이트"""
    try:
        agent = ETFRecommenderAgent(db)
        insights = agent.get_market_insights()
        return insights
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
