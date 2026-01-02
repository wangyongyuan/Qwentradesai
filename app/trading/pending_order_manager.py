"""
挂单管理器
提供创建、查询、取消挂单等功能
"""
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from app.database.connection import db
from app.database.pending_order import PendingOrderRepository
from app.config import settings
from app.utils.logger import logger


class PendingOrderManager:
    """挂单管理器"""
    
    def __init__(self):
        """初始化挂单管理器"""
        self.db = db
        self.pending_order_repo = PendingOrderRepository
        
        # 验证数据库连接
        try:
            from sqlalchemy import text
            with self.db.get_session() as session:
                session.execute(text("SELECT 1"))
            logger.debug("数据库连接验证成功")
        except Exception as e:
            logger.warning(f"数据库连接验证失败: {e}")
        
        logger.info("挂单管理器已初始化")
    
    def create_pending_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        trigger_price: float,
        stop_loss_trigger: float,
        take_profit_trigger: float,
        leverage: float,
        signal_id: Optional[int] = None,
        expire_hours: Optional[float] = None
    ) -> int:
        """
        创建挂单
        
        Args:
            symbol: 币种名称（如BTC、ETH）
            side: 持仓方向（LONG/SHORT）
            amount: 开仓数量
            trigger_price: 开仓触发价格
            stop_loss_trigger: 止损触发价格
            take_profit_trigger: 止盈触发价格
            leverage: 杠杆倍数
            signal_id: 信号ID（可选）
            expire_hours: 过期时长（小时，默认从配置读取）
            
        Returns:
            挂单ID
            
        Raises:
            ValueError: 参数验证失败
            RuntimeError: 创建失败
        """
        # 参数验证
        if not symbol or not symbol.strip():
            raise ValueError("symbol不能为空")
        
        symbol = symbol.strip().upper()
        
        if side.upper() not in ['LONG', 'SHORT']:
            raise ValueError(f"side必须是LONG或SHORT，当前值: {side}")
        
        if amount <= 0:
            raise ValueError(f"amount必须大于0，当前值: {amount}")
        
        if trigger_price <= 0:
            raise ValueError(f"trigger_price必须大于0，当前值: {trigger_price}")
        
        if stop_loss_trigger <= 0:
            raise ValueError(f"stop_loss_trigger必须大于0，当前值: {stop_loss_trigger}")
        
        if take_profit_trigger <= 0:
            raise ValueError(f"take_profit_trigger必须大于0，当前值: {take_profit_trigger}")
        
        if leverage <= 0:
            raise ValueError(f"leverage必须大于0，当前值: {leverage}")
        
        # 获取过期时长（从配置或参数）
        if expire_hours is None:
            expire_hours = settings._get('PENDING_ORDER_EXPIRE_HOURS', 1.0, 'float')
        
        logger.info(
            f"创建挂单: symbol={symbol}, side={side}, amount={amount}, "
            f"trigger_price={trigger_price}, expire_hours={expire_hours}"
        )
        
        with self.db.get_session() as session:
            # 先取消所有待处理的挂单
            self.pending_order_repo.cancel_old_pending_orders(session)
            
            # 创建新挂单
            order_id = self.pending_order_repo.create_pending_order(
                session=session,
                symbol=symbol,
                side=side,
                amount=amount,
                trigger_price=trigger_price,
                stop_loss_trigger=stop_loss_trigger,
                take_profit_trigger=take_profit_trigger,
                leverage=leverage,
                signal_id=signal_id,
                expire_hours=expire_hours
            )
            
            if not order_id:
                raise RuntimeError("创建挂单失败")
            
            logger.info(f"挂单创建成功: order_id={order_id}")
            return order_id
    
    def get_pending_order(
        self,
        order_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        查询挂单
        
        Args:
            order_id: 挂单ID
            
        Returns:
            挂单信息字典，不存在返回None
        """
        with self.db.get_session() as session:
            return self.pending_order_repo.get_pending_order_by_id(session, order_id)
    
    def cancel_pending_order(
        self,
        order_id: int
    ) -> bool:
        """
        取消挂单
        
        Args:
            order_id: 挂单ID
            
        Returns:
            是否取消成功
        """
        logger.info(f"取消挂单: order_id={order_id}")
        
        with self.db.get_session() as session:
            success = self.pending_order_repo.cancel_pending_order(session, order_id)
            
            if success:
                logger.info(f"挂单已取消: order_id={order_id}")
            else:
                logger.warning(f"取消挂单失败或挂单不存在: order_id={order_id}")
            
            return success
    
    def get_pending_orders_by_status(
        self,
        status: str
    ) -> list:
        """
        根据状态查询挂单列表
        
        Args:
            status: 状态（PENDING/EXPIRED/FILLED/FAILED/CANCELLED）
            
        Returns:
            挂单列表
        """
        with self.db.get_session() as session:
            return self.pending_order_repo.get_pending_orders_by_status(session, status)

