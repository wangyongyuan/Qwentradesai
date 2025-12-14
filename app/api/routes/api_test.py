"""
API管理器测试路由
"""
from fastapi import APIRouter, HTTPException
from app.components.api_manager import APIManager, RequestPriority
from app.utils.logger import logger

router = APIRouter(prefix="/api-test", tags=["API测试"])

# 全局API管理器实例（实际使用时应该在main.py中创建）
api_manager = None


@router.get("/init")
async def init_api_manager():
    """初始化API管理器"""
    global api_manager
    try:
        if api_manager:
            return {"status": "success", "message": "API管理器已存在"}
        
        api_manager = APIManager()
        api_manager.start()
        return {
            "status": "success",
            "message": "API管理器已启动"
        }
    except Exception as e:
        logger.error(f"API管理器启动失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"启动失败: {str(e)}")


@router.get("/test/price")
async def test_get_price():
    """获取实时价格（真实API）"""
    global api_manager
    if not api_manager:
        raise HTTPException(status_code=400, detail="请先初始化API管理器")
    
    try:
        # 使用真实API获取价格
        price = api_manager.get_current_price()
        
        return {
            "status": "success",
            "price": price,
            "symbol": "BTC/USDT:USDT",
            "method": "real_api"
        }
    except Exception as e:
        logger.error(f"获取价格失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取价格失败: {str(e)}")


@router.get("/test/balance")
async def test_get_balance():
    """获取账户余额（真实API）"""
    global api_manager
    if not api_manager:
        raise HTTPException(status_code=400, detail="请先初始化API管理器")
    
    try:
        balance = api_manager.get_balance()
        return {
            "status": "success",
            "balance": balance,
            "currency": "USDT"
        }
    except Exception as e:
        logger.error(f"获取余额失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取余额失败: {str(e)}")


@router.get("/test/ticker")
async def test_get_ticker():
    """获取完整ticker信息（真实API）"""
    global api_manager
    if not api_manager:
        raise HTTPException(status_code=400, detail="请先初始化API管理器")
    
    try:
        ticker = api_manager.get_ticker()
        return {
            "status": "success",
            "ticker": {
                "symbol": ticker.get('symbol'),
                "last": ticker.get('last'),
                "bid": ticker.get('bid'),
                "ask": ticker.get('ask'),
                "high": ticker.get('high'),
                "low": ticker.get('low'),
                "volume": ticker.get('volume'),
                "timestamp": ticker.get('timestamp')
            }
        }
    except Exception as e:
        logger.error(f"获取ticker失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取ticker失败: {str(e)}")


@router.get("/test/klines")
async def test_get_klines(timeframe: str = "15m", limit: int = 10):
    """获取K线数据（真实API）"""
    global api_manager
    if not api_manager:
        raise HTTPException(status_code=400, detail="请先初始化API管理器")
    
    try:
        klines = api_manager.get_klines(timeframe=timeframe, limit=limit)
        return {
            "status": "success",
            "timeframe": timeframe,
            "count": len(klines),
            "klines": klines[-limit:] if len(klines) > limit else klines
        }
    except Exception as e:
        logger.error(f"获取K线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取K线失败: {str(e)}")


@router.get("/stop")
async def stop_api_manager():
    """停止API管理器"""
    global api_manager
    if not api_manager:
        return {"status": "success", "message": "API管理器未启动"}
    
    try:
        api_manager.stop()
        api_manager = None
        return {
            "status": "success",
            "message": "API管理器已停止"
        }
    except Exception as e:
        logger.error(f"停止API管理器失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"停止失败: {str(e)}")
