"""
市场检测器测试路由
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict
from app.utils.logger import logger
from app.layers.market_detector import MarketDetector

router = APIRouter(prefix="/market-detector", tags=["市场检测器测试"])

# 全局市场检测器实例（在main.py中初始化后设置）
market_detectors: Dict[str, MarketDetector] = {}


def set_market_detectors(detectors: Dict[str, MarketDetector]):
    """设置市场检测器实例（由main.py调用）"""
    global market_detectors
    market_detectors = detectors


@router.post("/detect")
async def detect_market_signal(symbol: str = "ETH"):
    """
    手动触发市场检测
    
    Args:
        symbol: 币种名称（默认ETH）
    
    Returns:
        检测结果
    """
    global market_detectors
    
    if not market_detectors:
        raise HTTPException(
            status_code=400, 
            detail="市场检测器未初始化，请检查服务是否正常启动"
        )
    
    if symbol not in market_detectors:
        available_symbols = list(market_detectors.keys())
        raise HTTPException(
            status_code=404,
            detail=f"币种 {symbol} 未配置检测器。可用币种: {', '.join(available_symbols)}"
        )
    
    try:
        detector = market_detectors[symbol]
        result = detector.detect()
        
        if result is None:
            return {
                "status": "success",
                "has_signal": False,
                "message": "未检测到交易信号",
                "symbol": symbol
            }
        
        return {
            "status": "success",
            "has_signal": True,
            "symbol": symbol,
            "signal": {
                "signal_id": result.get("signal_id"),
                "snapshot_id": result.get("snapshot_id"),
                "signal_type": result.get("signal_type"),
                "signal_strength": result.get("signal_strength"),
                "confidence_score": result.get("confidence_score"),
                "price": result.get("price"),
                "trigger_factors": result.get("trigger_factors")
            }
        }
    except Exception as e:
        logger.error(f"市场检测失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"市场检测失败: {str(e)}"
        )


@router.get("/status")
async def get_detector_status():
    """
    获取市场检测器状态
    
    Returns:
        检测器状态信息
    """
    global market_detectors
    
    if not market_detectors:
        return {
            "status": "not_initialized",
            "message": "市场检测器未初始化",
            "detectors": {}
        }
    
    detectors_info = {}
    for symbol, detector in market_detectors.items():
        detectors_info[symbol] = {
            "symbol": detector.symbol,
            "initialized": True
        }
    
    return {
        "status": "initialized",
        "message": f"已初始化 {len(market_detectors)} 个检测器",
        "detectors": detectors_info
    }

