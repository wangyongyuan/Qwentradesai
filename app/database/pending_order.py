"""
挂单数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class PendingOrderRepository:
    """挂单数据仓库"""
    
    @staticmethod
    def create_pending_order(
        session: Session,
        symbol: str,
        side: str,
        amount: float,
        trigger_price: float,
        stop_loss_trigger: float,
        take_profit_trigger: float,
        leverage: float,
        signal_id: Optional[int] = None,
        expire_hours: float = 1.0
    ) -> Optional[int]:
        """
        创建挂单
        
        Args:
            session: 数据库会话
            symbol: 币种名称（如BTC、ETH）
            side: 持仓方向（LONG/SHORT）
            amount: 开仓数量
            trigger_price: 开仓触发价格
            stop_loss_trigger: 止损触发价格
            take_profit_trigger: 止盈触发价格
            leverage: 杠杆倍数
            signal_id: 信号ID（可选）
            expire_hours: 过期时长（小时，默认1小时）
            
        Returns:
            挂单ID，失败返回None
        """
        try:
            # 计算过期时间
            expired_at = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
            
            sql = text("""
                INSERT INTO pending_orders (
                    symbol, side, amount, trigger_price,
                    stop_loss_trigger, take_profit_trigger, leverage,
                    signal_id, status, expired_at
                )
                VALUES (
                    :symbol, :side, :amount, :trigger_price,
                    :stop_loss_trigger, :take_profit_trigger, :leverage,
                    :signal_id, 'PENDING', :expired_at
                )
                RETURNING id
            """)
            
            result = session.execute(sql, {
                'symbol': symbol.upper(),
                'side': side.upper(),
                'amount': float(amount),
                'trigger_price': float(trigger_price),
                'stop_loss_trigger': float(stop_loss_trigger),
                'take_profit_trigger': float(take_profit_trigger),
                'leverage': float(leverage),
                'signal_id': signal_id,
                'expired_at': expired_at
            })
            
            session.commit()
            row = result.fetchone()
            
            if row and row[0]:
                order_id = row[0]
                logger.info(
                    f"挂单创建成功: id={order_id}, symbol={symbol}, side={side}, "
                    f"trigger_price={trigger_price}"
                )
                return order_id
            return None
            
        except Exception as e:
            session.rollback()
            logger.error(f"创建挂单失败: symbol={symbol}, side={side}, 错误: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_pending_order_by_id(
        session: Session,
        order_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        根据ID查询挂单
        
        Args:
            session: 数据库会话
            order_id: 挂单ID
            
        Returns:
            挂单信息字典，不存在返回None
        """
        try:
            sql = text("""
                SELECT 
                    id, symbol, side, amount, trigger_price,
                    stop_loss_trigger, take_profit_trigger, leverage,
                    signal_id, status, created_at, expired_at,
                    triggered_at, filled_at, error_message, cl_ord_id,
                    updated_at
                FROM pending_orders
                WHERE id = :order_id
            """)
            
            result = session.execute(sql, {'order_id': order_id})
            row = result.fetchone()
            
            if row:
                return {
                    'id': row[0],
                    'symbol': row[1],
                    'side': row[2],
                    'amount': float(row[3]) if row[3] else 0.0,
                    'trigger_price': float(row[4]) if row[4] else 0.0,
                    'stop_loss_trigger': float(row[5]) if row[5] else 0.0,
                    'take_profit_trigger': float(row[6]) if row[6] else 0.0,
                    'leverage': float(row[7]) if row[7] else 0.0,
                    'signal_id': row[8],
                    'status': row[9],
                    'created_at': row[10],
                    'expired_at': row[11],
                    'triggered_at': row[12],
                    'filled_at': row[13],
                    'error_message': row[14],
                    'cl_ord_id': row[15],
                    'updated_at': row[16]
                }
            return None
            
        except Exception as e:
            logger.error(f"查询挂单失败: order_id={order_id}, 错误: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_pending_orders_by_status(
        session: Session,
        status: str
    ) -> List[Dict[str, Any]]:
        """
        根据状态查询挂单列表
        
        Args:
            session: 数据库会话
            status: 状态（PENDING/EXPIRED/FILLED/FAILED/CANCELLED）
            
        Returns:
            挂单列表
        """
        try:
            sql = text("""
                SELECT 
                    id, symbol, side, amount, trigger_price,
                    stop_loss_trigger, take_profit_trigger, leverage,
                    signal_id, status, created_at, expired_at,
                    triggered_at, filled_at, error_message, cl_ord_id,
                    updated_at
                FROM pending_orders
                WHERE status = :status
                ORDER BY created_at DESC
            """)
            
            result = session.execute(sql, {'status': status})
            rows = result.fetchall()
            
            orders = []
            for row in rows:
                orders.append({
                    'id': row[0],
                    'symbol': row[1],
                    'side': row[2],
                    'amount': float(row[3]) if row[3] else 0.0,
                    'trigger_price': float(row[4]) if row[4] else 0.0,
                    'stop_loss_trigger': float(row[5]) if row[5] else 0.0,
                    'take_profit_trigger': float(row[6]) if row[6] else 0.0,
                    'leverage': float(row[7]) if row[7] else 0.0,
                    'signal_id': row[8],
                    'status': row[9],
                    'created_at': row[10],
                    'expired_at': row[11],
                    'triggered_at': row[12],
                    'filled_at': row[13],
                    'error_message': row[14],
                    'cl_ord_id': row[15],
                    'updated_at': row[16]
                })
            
            return orders
            
        except Exception as e:
            logger.error(f"查询挂单列表失败: status={status}, 错误: {e}", exc_info=True)
            return []
    
    @staticmethod
    def get_pending_orders_to_check(
        session: Session
    ) -> List[Dict[str, Any]]:
        """
        查询需要检查的挂单（状态为PENDING且未过期）
        
        Args:
            session: 数据库会话
            
        Returns:
            挂单列表
        """
        try:
            sql = text("""
                SELECT 
                    id, symbol, side, amount, trigger_price,
                    stop_loss_trigger, take_profit_trigger, leverage,
                    signal_id, status, created_at, expired_at,
                    triggered_at, filled_at, error_message, cl_ord_id,
                    updated_at
                FROM pending_orders
                WHERE status = 'PENDING'
                  AND expired_at > NOW()
                  AND triggered_at IS NULL
                ORDER BY created_at ASC
            """)
            
            result = session.execute(sql)
            rows = result.fetchall()
            
            orders = []
            for row in rows:
                orders.append({
                    'id': row[0],
                    'symbol': row[1],
                    'side': row[2],
                    'amount': float(row[3]) if row[3] else 0.0,
                    'trigger_price': float(row[4]) if row[4] else 0.0,
                    'stop_loss_trigger': float(row[5]) if row[5] else 0.0,
                    'take_profit_trigger': float(row[6]) if row[6] else 0.0,
                    'leverage': float(row[7]) if row[7] else 0.0,
                    'signal_id': row[8],
                    'status': row[9],
                    'created_at': row[10],
                    'expired_at': row[11],
                    'triggered_at': row[12],
                    'filled_at': row[13],
                    'error_message': row[14],
                    'cl_ord_id': row[15],
                    'updated_at': row[16]
                })
            
            return orders
            
        except Exception as e:
            logger.error(f"查询待检查挂单失败: 错误: {e}", exc_info=True)
            return []
    
    @staticmethod
    def update_order_status(
        session: Session,
        order_id: int,
        status: str,
        triggered_at: Optional[datetime] = None,
        filled_at: Optional[datetime] = None,
        error_message: Optional[str] = None,
        cl_ord_id: Optional[str] = None
    ) -> bool:
        """
        更新挂单状态
        
        Args:
            session: 数据库会话
            order_id: 挂单ID
            status: 新状态
            triggered_at: 触发时间（可选）
            filled_at: 完成时间（可选）
            error_message: 错误信息（可选）
            cl_ord_id: 开仓成功后的clOrdId（可选）
            
        Returns:
            是否更新成功
        """
        try:
            # 构建更新SQL
            updates = ["status = :status", "updated_at = NOW()"]
            params = {'order_id': order_id, 'status': status}
            
            if triggered_at:
                updates.append("triggered_at = :triggered_at")
                params['triggered_at'] = triggered_at
            
            if filled_at:
                updates.append("filled_at = :filled_at")
                params['filled_at'] = filled_at
            
            if error_message is not None:
                updates.append("error_message = :error_message")
                params['error_message'] = error_message
            
            if cl_ord_id is not None:
                updates.append("cl_ord_id = :cl_ord_id")
                params['cl_ord_id'] = cl_ord_id
            
            sql = text(f"""
                UPDATE pending_orders
                SET {', '.join(updates)}
                WHERE id = :order_id
            """)
            
            result = session.execute(sql, params)
            session.commit()
            
            if result.rowcount > 0:
                logger.debug(f"更新挂单状态成功: order_id={order_id}, status={status}")
                return True
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(
                f"更新挂单状态失败: order_id={order_id}, status={status}, 错误: {e}",
                exc_info=True
            )
            return False
    
    @staticmethod
    def cancel_old_pending_orders(
        session: Session
    ) -> int:
        """
        取消所有待处理的挂单（创建新挂单时调用）
        
        Args:
            session: 数据库会话
            
        Returns:
            取消的挂单数量
        """
        try:
            sql = text("""
                UPDATE pending_orders
                SET status = 'CANCELLED', updated_at = NOW()
                WHERE status = 'PENDING'
            """)
            
            result = session.execute(sql)
            session.commit()
            
            count = result.rowcount
            if count > 0:
                logger.info(f"已取消{count}个待处理的挂单")
            return count
            
        except Exception as e:
            session.rollback()
            logger.error(f"取消待处理挂单失败: 错误: {e}", exc_info=True)
            return 0
    
    @staticmethod
    def cancel_pending_order(
        session: Session,
        order_id: int
    ) -> bool:
        """
        取消指定挂单
        
        Args:
            session: 数据库会话
            order_id: 挂单ID
            
        Returns:
            是否取消成功
        """
        try:
            sql = text("""
                UPDATE pending_orders
                SET status = 'CANCELLED', updated_at = NOW()
                WHERE id = :order_id AND status = 'PENDING'
            """)
            
            result = session.execute(sql, {'order_id': order_id})
            session.commit()
            
            if result.rowcount > 0:
                logger.info(f"挂单已取消: order_id={order_id}")
                return True
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(f"取消挂单失败: order_id={order_id}, 错误: {e}", exc_info=True)
            return False
    
    @staticmethod
    def mark_expired_orders(
        session: Session
    ) -> int:
        """
        标记过期的挂单
        
        Args:
            session: 数据库会话
            
        Returns:
            标记的挂单数量
        """
        try:
            sql = text("""
                UPDATE pending_orders
                SET status = 'EXPIRED', updated_at = NOW()
                WHERE status = 'PENDING'
                  AND expired_at <= NOW()
            """)
            
            result = session.execute(sql)
            session.commit()
            
            count = result.rowcount
            if count > 0:
                logger.info(f"已标记{count}个过期的挂单")
            return count
            
        except Exception as e:
            session.rollback()
            logger.error(f"标记过期挂单失败: 错误: {e}", exc_info=True)
            return 0

