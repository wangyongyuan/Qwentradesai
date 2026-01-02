"""
交易模块测试路由
"""
from fastapi import APIRouter, HTTPException, Body
from typing import Optional, Dict, Any
from pydantic import BaseModel
from app.components.api_manager import APIManager
from app.trading.trading_manager import TradingManager
from app.utils.logger import logger

router = APIRouter(prefix="/trading", tags=["交易模块测试"])

# 全局TradingManager实例（延迟初始化）
_trading_manager: Optional[TradingManager] = None


def get_trading_manager() -> TradingManager:
    """获取TradingManager实例（单例模式）"""
    global _trading_manager
    if _trading_manager is None:
        api_manager = APIManager()
        api_manager.start()  # 启动API管理器
        _trading_manager = TradingManager(api_manager)
    return _trading_manager


class OpenPositionRequest(BaseModel):
    """开仓请求模型"""
    symbol: str
    side: str  # LONG/SHORT
    amount: float
    stop_loss_trigger: float
    take_profit_trigger: float
    leverage: float
    signal_id: int


class SetStopLossTakeProfitRequest(BaseModel):
    """设置止盈止损请求模型（支持多个）"""
    cl_ord_id: str
    plans: list  # [{"take_profit": 3500.0, "amount": 0.03}, {"stop_loss": 3000.0, "amount": 0.1}]


class AddPositionRequest(BaseModel):
    """加仓请求模型"""
    cl_ord_id: str
    amount: float


class ReducePositionRequest(BaseModel):
    """减仓请求模型"""
    cl_ord_id: str
    amount: float


class ClosePositionRequest(BaseModel):
    """平仓请求模型"""
    cl_ord_id: str
    amount: Optional[float] = None  # None表示全部平仓


@router.post("/open-position")
async def open_position(request: OpenPositionRequest):
    """
    开仓测试接口
    
    测试JSON示例:
    ```json
    {
        "symbol": "ETH",
        "side": "LONG",
        "amount": 0.01,
        "stop_loss_trigger": 3000.0,
        "take_profit_trigger": 3500.0,
        "leverage": 3,
        "signal_id": 1
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        cl_ord_id = trading_manager.open_position(
            symbol=request.symbol,
            side=request.side,
            amount=request.amount,
            stop_loss_trigger=request.stop_loss_trigger,
            take_profit_trigger=request.take_profit_trigger,
            leverage=request.leverage,
            signal_id=request.signal_id
        )
        
        return {
            "status": "success",
            "cl_ord_id": cl_ord_id,
            "message": "开仓成功"
        }
        
    except Exception as e:
        logger.error(f"开仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"开仓失败: {str(e)}")


@router.post("/set-stop-loss-take-profit")
async def set_stop_loss_take_profit(request: SetStopLossTakeProfitRequest):
    """
    设置止盈止损测试接口（支持多个，分批止盈止损）
    
    测试JSON示例:
    ```json
    {
        "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
        "plans": [
            {"take_profit": 3500.0, "amount": 0.03},
            {"take_profit": 3600.0, "amount": 0.03},
            {"stop_loss": 3000.0, "amount": 0.1}
        ]
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        trading_manager.set_stop_loss_take_profit(
            cl_ord_id=request.cl_ord_id,
            plans=request.plans
        )
        
        return {
            "status": "success",
            "message": "设置止盈止损成功"
        }
        
    except Exception as e:
        logger.error(f"设置止盈止损失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"设置止盈止损失败: {str(e)}")


@router.post("/add-position")
async def add_position(request: AddPositionRequest):
    """
    加仓测试接口
    
    测试JSON示例:
    ```json
    {
        "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
        "amount": 0.01
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        trading_manager.add_position(
            cl_ord_id=request.cl_ord_id,
            amount=request.amount
        )
        
        return {
            "status": "success",
            "message": "加仓成功"
        }
        
    except Exception as e:
        logger.error(f"加仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"加仓失败: {str(e)}")


@router.post("/reduce-position")
async def reduce_position(request: ReducePositionRequest):
    """
    减仓测试接口
    
    测试JSON示例:
    ```json
    {
        "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
        "amount": 0.005
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        trading_manager.reduce_position(
            cl_ord_id=request.cl_ord_id,
            amount=request.amount
        )
        
        return {
            "status": "success",
            "message": "减仓成功"
        }
        
    except Exception as e:
        logger.error(f"减仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"减仓失败: {str(e)}")


@router.post("/close-position")
async def close_position(request: ClosePositionRequest):
    """
    平仓测试接口
    
    测试JSON示例（全部平仓）:
    ```json
    {
        "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
        "amount": null
    }
    ```
    
    测试JSON示例（部分平仓）:
    ```json
    {
        "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
        "amount": 0.005
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        trading_manager.close_position(
            cl_ord_id=request.cl_ord_id,
            amount=request.amount
        )
        
        return {
            "status": "success",
            "message": "平仓成功"
        }
        
    except Exception as e:
        logger.error(f"平仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"平仓失败: {str(e)}")


@router.get("/order-status/{cl_ord_id}")
async def get_order_status(cl_ord_id: str):
    """
    查询订单状态测试接口
    
    测试URL示例:
    ```
    GET /trading/order-status/2412081430aB3cD5eF7gH9iJ0kL2mN4
    ```
    
    返回JSON示例:
    ```json
    {
        "status": "success",
        "data": {
            "cl_ord_id": "2412081430aB3cD5eF7gH9iJ0kL2mN4",
            "ord_ids": ["123456789", "123456790"],
            "total_filled": 0.01,
            "total_amount": 0.01,
            "overall_status": "filled",
            "orders": [
                {
                    "ord_id": "123456789",
                    "state": "filled",
                    "acc_fill_sz": 0.005
                },
                {
                    "ord_id": "123456790",
                    "state": "filled",
                    "acc_fill_sz": 0.005
                }
            ]
        }
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        status = trading_manager.get_order_status(cl_ord_id)
        
        return {
            "status": "success",
            "data": status
        }
        
    except Exception as e:
        logger.error(f"查询订单状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询订单状态失败: {str(e)}")


@router.get("/current-position")
async def get_current_position():
    """
    查询当前持仓测试接口
    
    测试URL示例:
    ```
    GET /trading/current-position
    ```
    
    返回JSON示例（有持仓）:
    ```json
    {
        "status": "success",
        "data": {
            "symbol": "ETH",
            "side": "LONG",
            "size": 0.01,
            "entry_price": 3200.0,
            "mark_price": 3250.0,
            "unrealized_pnl": 0.5,
            "leverage": 3,
            "margin_mode": "cross"
        }
    }
    ```
    
    返回JSON示例（无持仓）:
    ```json
    {
        "status": "success",
        "data": null,
        "message": "当前无持仓"
    }
    ```
    """
    try:
        trading_manager = get_trading_manager()
        
        if not trading_manager.has_active_position():
            return {
                "status": "success",
                "data": None,
                "message": "当前无持仓"
            }
        
        # 获取当前活跃的clOrdId
        cl_ord_id = trading_manager.current_cl_ord_id
        if not cl_ord_id:
            return {
                "status": "success",
                "data": None,
                "message": "当前无活跃持仓（clOrdId为空）"
            }
        
        position = trading_manager.get_current_position(cl_ord_id)
        
        return {
            "status": "success",
            "data": position
        }
        
    except Exception as e:
        logger.error(f"查询当前持仓失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询当前持仓失败: {str(e)}")

