"""
挂单模块API路由
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any
from pydantic import BaseModel
from app.trading.pending_order_manager import PendingOrderManager
from app.utils.logger import logger

router = APIRouter(prefix="/pending-order", tags=["挂单模块"])

# 全局PendingOrderManager实例（延迟初始化）
_pending_order_manager: Optional[PendingOrderManager] = None


def get_pending_order_manager() -> PendingOrderManager:
    """获取PendingOrderManager实例（单例模式）"""
    global _pending_order_manager
    if _pending_order_manager is None:
        _pending_order_manager = PendingOrderManager()
    return _pending_order_manager


class CreatePendingOrderRequest(BaseModel):
    """创建挂单请求模型"""
    symbol: str
    side: str  # LONG/SHORT
    amount: float
    trigger_price: float  # 开仓触发价格
    stop_loss_trigger: float
    take_profit_trigger: float
    leverage: float
    signal_id: Optional[int] = None
    expire_hours: Optional[float] = None  # 过期时长（小时，默认1小时）


@router.post("/create")
async def create_pending_order(request: CreatePendingOrderRequest):
    """
    创建挂单接口
    
    测试JSON示例:
    ```json
    {
        "symbol": "ETH",
        "side": "LONG",
        "amount": 0.01,
        "trigger_price": 3000.0,
        "stop_loss_trigger": 2900.0,
        "take_profit_trigger": 3500.0,
        "leverage": 3,
        "signal_id": 1,
        "expire_hours": 1.0
    }
    ```
    
    说明：
    - trigger_price: 开仓触发价格
      - LONG: 当前价格 <= trigger_price 时触发
      - SHORT: 当前价格 >= trigger_price 时触发
    - 创建新挂单时会自动取消所有待处理的旧挂单
    - 一次只能有一个待处理的挂单
    """
    try:
        manager = get_pending_order_manager()
        
        order_id = manager.create_pending_order(
            symbol=request.symbol,
            side=request.side,
            amount=request.amount,
            trigger_price=request.trigger_price,
            stop_loss_trigger=request.stop_loss_trigger,
            take_profit_trigger=request.take_profit_trigger,
            leverage=request.leverage,
            signal_id=request.signal_id,
            expire_hours=request.expire_hours
        )
        
        return {
            "status": "success",
            "order_id": order_id,
            "message": "挂单创建成功"
        }
        
    except Exception as e:
        logger.error(f"创建挂单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建挂单失败: {str(e)}")


@router.get("/{order_id}")
async def get_pending_order(order_id: int):
    """
    查询挂单接口
    
    路径参数:
    - order_id: 挂单ID
    """
    try:
        manager = get_pending_order_manager()
        
        order = manager.get_pending_order(order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail=f"挂单不存在: order_id={order_id}")
        
        return {
            "status": "success",
            "order": order
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询挂单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询挂单失败: {str(e)}")


@router.get("/status/{status}")
async def get_pending_orders_by_status(status: str):
    """
    根据状态查询挂单列表接口
    
    路径参数:
    - status: 状态（PENDING/EXPIRED/FILLED/FAILED/CANCELLED）
    """
    try:
        if status.upper() not in ['PENDING', 'EXPIRED', 'FILLED', 'FAILED', 'CANCELLED']:
            raise HTTPException(
                status_code=400,
                detail=f"无效的状态: {status}，必须是 PENDING/EXPIRED/FILLED/FAILED/CANCELLED"
            )
        
        manager = get_pending_order_manager()
        
        orders = manager.get_pending_orders_by_status(status.upper())
        
        return {
            "status": "success",
            "count": len(orders),
            "orders": orders
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询挂单列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询挂单列表失败: {str(e)}")


@router.post("/{order_id}/cancel")
async def cancel_pending_order(order_id: int):
    """
    取消挂单接口
    
    路径参数:
    - order_id: 挂单ID
    """
    try:
        manager = get_pending_order_manager()
        
        success = manager.cancel_pending_order(order_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"取消挂单失败: 挂单不存在或状态不是PENDING，order_id={order_id}"
            )
        
        return {
            "status": "success",
            "message": "挂单已取消"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消挂单失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消挂单失败: {str(e)}")

