from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from ..models.watchlist import Watchlist, WatchlistItem
from ..models.etf import ETF, ETFPrice
from ..services.etf_service import ETFService
from ..config import get_settings

settings = get_settings()


class ETFRecommenderAgent:
    """ETF 추천 및 분석 에이전트"""

    def __init__(self, db: Session):
        self.db = db
        self.etf_service = ETFService(db)

    def analyze(self, query: str, user_id: int, watchlist_id: Optional[int] = None) -> Dict[str, Any]:
        """사용자 쿼리 기반 ETF 분석"""
        signals = []
        insights = []

        # 워치리스트 기반 분석
        if watchlist_id:
            watchlist = self.db.query(Watchlist).filter(
                Watchlist.id == watchlist_id,
                Watchlist.user_id == user_id
            ).first()
            if watchlist:
                for item in watchlist.items:
                    etf = self.db.query(ETF).filter(ETF.id == item.etf_id).first()
                    if etf:
                        signal = self._analyze_etf(etf)
                        if signal:
                            signals.append(signal)

        # 쿼리 기반 ETF 검색 및 분석
        etfs = self.etf_service.search_etfs(query, limit=5)
        for etf in etfs:
            signal = self._analyze_etf(etf)
            if signal and signal not in signals:
                signals.append(signal)

        # 인사이트 생성
        if signals:
            insights = self._generate_insights(signals)

        return {
            "signals": signals[:10],
            "insights": insights[:5],
            "summary": self._generate_summary(query, signals)
        }

    def _analyze_etf(self, etf: ETF) -> Optional[Dict[str, Any]]:
        """개별 ETF 분석"""
        prices = self.etf_service.get_etf_prices(etf.code, days=30)
        if not prices or len(prices) < 5:
            return None

        # 간단한 모멘텀 분석
        recent_prices = [p["close"] for p in prices[-5:] if p["close"]]
        if len(recent_prices) < 2:
            return None

        price_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100

        if price_change > 5:
            signal_type = "buy"
            confidence = min(0.8, 0.5 + price_change / 20)
            reason = f"최근 5일간 {price_change:.1f}% 상승, 상승 모멘텀 지속"
        elif price_change < -5:
            signal_type = "sell"
            confidence = min(0.8, 0.5 + abs(price_change) / 20)
            reason = f"최근 5일간 {price_change:.1f}% 하락, 하락 추세 주의"
        else:
            signal_type = "hold"
            confidence = 0.5
            reason = f"최근 5일간 {price_change:.1f}% 변동, 관망 권장"

        return {
            "etf_code": etf.code,
            "etf_name": etf.name,
            "signal_type": signal_type,
            "confidence": round(confidence, 2),
            "reason": reason
        }

    def _generate_insights(self, signals: List[Dict]) -> List[Dict[str, Any]]:
        """신호 기반 인사이트 생성"""
        insights = []

        buy_signals = [s for s in signals if s["signal_type"] == "buy"]
        sell_signals = [s for s in signals if s["signal_type"] == "sell"]

        if buy_signals:
            insights.append({
                "title": "상승 모멘텀 ETF",
                "content": f"{len(buy_signals)}개 ETF가 상승 모멘텀을 보이고 있습니다. 분할 매수를 고려해보세요.",
                "etfs": [s["etf_code"] for s in buy_signals[:3]]
            })

        if sell_signals:
            insights.append({
                "title": "하락 주의 ETF",
                "content": f"{len(sell_signals)}개 ETF가 하락 추세입니다. 리스크 관리가 필요합니다.",
                "etfs": [s["etf_code"] for s in sell_signals[:3]]
            })

        return insights

    def _generate_summary(self, query: str, signals: List[Dict]) -> str:
        """분석 요약 생성"""
        if not signals:
            return f"'{query}' 관련 ETF 분석 결과가 없습니다."

        buy_count = len([s for s in signals if s["signal_type"] == "buy"])
        sell_count = len([s for s in signals if s["signal_type"] == "sell"])
        hold_count = len([s for s in signals if s["signal_type"] == "hold"])

        return (
            f"'{query}' 관련 {len(signals)}개 ETF 분석 완료. "
            f"매수 신호 {buy_count}개, 매도 신호 {sell_count}개, 관망 {hold_count}개."
        )

    def get_watchlist_signals(self, user_id: int) -> List[Dict[str, Any]]:
        """사용자 워치리스트 기반 신호"""
        signals = []
        watchlists = self.db.query(Watchlist).filter(Watchlist.user_id == user_id).all()

        for watchlist in watchlists:
            for item in watchlist.items:
                etf = self.db.query(ETF).filter(ETF.id == item.etf_id).first()
                if etf:
                    signal = self._analyze_etf(etf)
                    if signal:
                        signals.append(signal)

        return signals

    def get_market_insights(self) -> List[Dict[str, Any]]:
        """전체 시장 인사이트"""
        # 상위 ETF 분석
        top_etfs = self.db.query(ETF).order_by(ETF.net_assets.desc()).limit(20).all()
        signals = []

        for etf in top_etfs:
            signal = self._analyze_etf(etf)
            if signal:
                signals.append(signal)

        return self._generate_insights(signals)
