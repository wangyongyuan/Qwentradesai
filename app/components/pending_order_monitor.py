"""
挂单监控服务
实时监控价格，检查挂单触发条件，自动开仓
"""
import time
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from app.database.connection import db
from app.database.pending_order import PendingOrderRepository
from app.components.okx_websocket_client import OKXWebSocketClient
from app.utils.logger import logger


class PendingOrderMonitor:
    """挂单监控服务"""
    
    def __init__(
        self,
        websocket_client: OKXWebSocketClient,
        trading_manager: Any  # 避免循环导入，使用Any类型
    ):
        """
        初始化挂单监控服务
        
        Args:
            websocket_client: WebSocket客户端实例（用于获取实时价格）
            trading_manager: 交易管理器实例（用于开仓）
        """
        self.websocket_client = websocket_client
        self.trading_manager = trading_manager
        self.db = db
        self.pending_order_repo = PendingOrderRepository
        
        # 运行状态
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # 监控间隔（秒）
        self.check_interval = 1.0  # 每秒检查一次
        
        logger.info("挂单监控服务已初始化")
    
    def start(self):
        """启动监控服务"""
        if self.running:
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("挂单监控服务已启动")
    
    def stop(self):
        """停止监控服务"""
        self.running = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=3)
        
        logger.info("挂单监控服务已停止")
    
    def _monitor_loop(self):
        """监控循环（在独立线程中运行）"""
        logger.info("挂单监控循环已启动")
        
        while self.running:
            try:
                # 检查过期挂单
                self._check_expired_orders()
                
                # 检查待触发的挂单
                self._check_pending_orders()
                
                # 等待下次检查
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"挂单监控循环异常: {e}", exc_info=True)
                time.sleep(self.check_interval)
    
    def _check_expired_orders(self):
        """检查并标记过期的挂单"""
        try:
            with self.db.get_session() as session:
                count = self.pending_order_repo.mark_expired_orders(session)
                if count > 0:
                    logger.info(f"已标记{count}个过期的挂单")
        except Exception as e:
            logger.error(f"检查过期挂单失败: {e}", exc_info=True)
    
    def _check_pending_orders(self):
        """检查待触发的挂单"""
        try:
            # 获取实时价格
            price_data = self.websocket_client.get_latest_price()
            if not price_data:
                return
            
            current_price = price_data.get('last')
            if not current_price or current_price <= 0:
                return
            
            # 查询待检查的挂单
            with self.db.get_session() as session:
                pending_orders = self.pending_order_repo.get_pending_orders_to_check(session)
                
                for order in pending_orders:
                    # 检查是否触发
                    if self._should_trigger(order, current_price):
                        # 触发开仓
                        self._trigger_order(order, current_price)
                        break  # 一次只处理一个挂单
                        
        except Exception as e:
            logger.error(f"检查待触发挂单失败: {e}", exc_info=True)
    
    def _should_trigger(self, order: Dict[str, Any], current_price: float) -> bool:
        """
        判断挂单是否应该触发
        
        Args:
            order: 挂单信息
            current_price: 当前价格
            
        Returns:
            是否应该触发
        """
        side = order['side'].upper()
        trigger_price = order['trigger_price']
        
        if side == 'LONG':
            # LONG: 当前价格 <= 触发价格
            return current_price <= trigger_price
        elif side == 'SHORT':
            # SHORT: 当前价格 >= 触发价格
            return current_price >= trigger_price
        else:
            logger.warning(f"未知的持仓方向: {side}")
            return False
    
    def _trigger_order(self, order: Dict[str, Any], current_price: float):
        """
        触发挂单，执行开仓
        
        Args:
            order: 挂单信息
            current_price: 触发时的价格
        """
        order_id = order['id']
        symbol = order['symbol']
        side = order['side']
        
        logger.info(
            f"挂单触发: order_id={order_id}, symbol={symbol}, side={side}, "
            f"trigger_price={order['trigger_price']}, current_price={current_price}"
        )
        
        # 更新状态为已触发
        triggered_at = datetime.now(timezone.utc)
        with self.db.get_session() as session:
            self.pending_order_repo.update_order_status(
                session=session,
                order_id=order_id,
                status='PENDING',  # 保持PENDING状态，等待开仓结果
                triggered_at=triggered_at
            )
        
        # 检查是否有活跃持仓
        if self.trading_manager.has_active_position():
            logger.warning(
                f"挂单触发但已有活跃持仓，取消挂单: order_id={order_id}"
            )
            with self.db.get_session() as session:
                self.pending_order_repo.update_order_status(
                    session=session,
                    order_id=order_id,
                    status='CANCELLED'
                )
            return
        
        # 调用开仓
        try:
            signal_id = order.get('signal_id')
            if not signal_id or signal_id <= 0:
                # 如果没有signal_id或无效，使用默认值1（避免验证失败）
                signal_id = 1
                logger.warning(f"挂单没有有效的signal_id，使用默认值1: order_id={order_id}")
            
            cl_ord_id = self.trading_manager.open_position(
                symbol=symbol,
                side=side,
                amount=order['amount'],
                stop_loss_trigger=order['stop_loss_trigger'],
                take_profit_trigger=order['take_profit_trigger'],
                leverage=order['leverage'],
                signal_id=signal_id
            )
            
            # 开仓成功，更新状态
            filled_at = datetime.now(timezone.utc)
            with self.db.get_session() as session:
                self.pending_order_repo.update_order_status(
                    session=session,
                    order_id=order_id,
                    status='FILLED',
                    filled_at=filled_at,
                    cl_ord_id=cl_ord_id
                )
            
            logger.info(
                f"挂单开仓成功: order_id={order_id}, cl_ord_id={cl_ord_id}"
            )
            
        except Exception as e:
            # 开仓失败，更新状态
            error_message = str(e)
            logger.error(
                f"挂单开仓失败: order_id={order_id}, 错误: {error_message}",
                exc_info=True
            )
            
            with self.db.get_session() as session:
                self.pending_order_repo.update_order_status(
                    session=session,
                    order_id=order_id,
                    status='FAILED',
                    error_message=error_message
                )

