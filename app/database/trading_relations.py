"""
交易关联数据库操作模块
记录完整的交易链路：信号ID -> clOrdId -> 多个订单ID -> 持仓ID
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal
from app.database.connection import db
from app.utils.logger import logger


class TradingRelationsRepository:
    """交易关联数据仓库"""
    
    @staticmethod
    def insert_relation(
        session: Session,
        signal_id: int,
        cl_ord_id: str,
        operation_type: str,
        ord_id: Optional[str] = None,
        position_history_id: Optional[int] = None,
        amount: Optional[float] = None,
        price: Optional[float] = None
    ) -> bool:
        """
        插入交易关联记录
        
        Args:
            session: 数据库会话
            signal_id: 信号ID（market_signals.id）
            cl_ord_id: 客户端订单ID
            operation_type: 操作类型（open/add/reduce/close/set_stop_loss_take_profit）
            ord_id: 订单ID（OKX的ordId，可为空）
            position_history_id: 仓位历史ID（position_history.id，可为空）
            amount: 操作数量（可为空）
            price: 操作价格（可为空）
            
        Returns:
            是否插入成功
        """
        try:
            sql = text("""
                INSERT INTO trading_relations (
                    signal_id, cl_ord_id, ord_id, position_history_id,
                    operation_type, amount, price
                )
                VALUES (
                    :signal_id, :cl_ord_id, :ord_id, :position_history_id,
                    :operation_type, :amount, :price
                )
            """)
            
            # 转换数值字段
            def to_decimal(value):
                """转换为Decimal兼容的数值"""
                if value is None:
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            result = session.execute(sql, {
                'signal_id': signal_id,
                'cl_ord_id': cl_ord_id,
                'ord_id': ord_id,
                'position_history_id': position_history_id,
                'operation_type': operation_type,
                'amount': to_decimal(amount),
                'price': to_decimal(price),
            })
            
            session.commit()
            
            if result.rowcount > 0:
                logger.debug(
                    f"交易关联记录已插入: signal_id={signal_id}, "
                    f"cl_ord_id={cl_ord_id}, operation_type={operation_type}"
                )
                return True
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(
                f"插入交易关联记录失败: signal_id={signal_id}, "
                f"cl_ord_id={cl_ord_id}, operation_type={operation_type}, "
                f"错误: {e}",
                exc_info=True
            )
            return False
    
    @staticmethod
    def get_relations_by_cl_ord_id(
        session: Session,
        cl_ord_id: str
    ) -> List[Dict[str, Any]]:
        """
        根据clOrdId查询所有关联记录
        
        Args:
            session: 数据库会话
            cl_ord_id: 客户端订单ID
            
        Returns:
            关联记录列表
        """
        try:
            sql = text("""
                SELECT 
                    id, signal_id, cl_ord_id, ord_id, position_history_id,
                    operation_type, amount, price,
                    created_at, updated_at
                FROM trading_relations
                WHERE cl_ord_id = :cl_ord_id
                ORDER BY created_at ASC
            """)
            
            result = session.execute(sql, {'cl_ord_id': cl_ord_id})
            rows = result.fetchall()
            
            relations = []
            for row in rows:
                relation = {
                    'id': row[0],
                    'signal_id': row[1],
                    'cl_ord_id': row[2],
                    'ord_id': row[3],
                    'position_history_id': row[4],
                    'operation_type': row[5],
                    'amount': float(row[6]) if row[6] else None,
                    'price': float(row[7]) if row[7] else None,
                    'created_at': row[8],
                    'updated_at': row[9],
                }
                relations.append(relation)
            
            return relations
            
        except Exception as e:
            logger.error(f"查询交易关联记录失败 cl_ord_id={cl_ord_id}: {e}", exc_info=True)
            return []
    
    @staticmethod
    def get_relations_by_signal_id(
        session: Session,
        signal_id: int
    ) -> List[Dict[str, Any]]:
        """
        根据signal_id查询所有关联记录
        
        Args:
            session: 数据库会话
            signal_id: 信号ID
            
        Returns:
            关联记录列表
        """
        try:
            sql = text("""
                SELECT 
                    id, signal_id, cl_ord_id, ord_id, position_history_id,
                    operation_type, amount, price,
                    created_at, updated_at
                FROM trading_relations
                WHERE signal_id = :signal_id
                ORDER BY created_at ASC
            """)
            
            result = session.execute(sql, {'signal_id': signal_id})
            rows = result.fetchall()
            
            relations = []
            for row in rows:
                relation = {
                    'id': row[0],
                    'signal_id': row[1],
                    'cl_ord_id': row[2],
                    'ord_id': row[3],
                    'position_history_id': row[4],
                    'operation_type': row[5],
                    'amount': float(row[6]) if row[6] else None,
                    'price': float(row[7]) if row[7] else None,
                    'created_at': row[8],
                    'updated_at': row[9],
                }
                relations.append(relation)
            
            return relations
            
        except Exception as e:
            logger.error(f"查询交易关联记录失败 signal_id={signal_id}: {e}", exc_info=True)
            return []
    
    @staticmethod
    def get_ord_ids_by_cl_ord_id(
        session: Session,
        cl_ord_id: str
    ) -> List[str]:
        """
        根据clOrdId查询所有订单ID（ordId）
        
        Args:
            session: 数据库会话
            cl_ord_id: 客户端订单ID
            
        Returns:
            订单ID列表（去重，过滤空值）
        """
        try:
            sql = text("""
                SELECT ord_id
                FROM (
                    SELECT ord_id, created_at,
                           ROW_NUMBER() OVER (PARTITION BY ord_id ORDER BY created_at ASC) as rn
                    FROM trading_relations
                    WHERE cl_ord_id = :cl_ord_id AND ord_id IS NOT NULL
                ) AS subquery
                WHERE rn = 1
                ORDER BY created_at ASC
            """)
            
            result = session.execute(sql, {'cl_ord_id': cl_ord_id})
            rows = result.fetchall()
            
            ord_ids = [row[0] for row in rows if row[0]]
            return ord_ids
            
        except Exception as e:
            logger.error(f"查询订单ID失败 cl_ord_id={cl_ord_id}: {e}", exc_info=True)
            return []
    
    @staticmethod
    def update_position_history_id(
        session: Session,
        cl_ord_id: str,
        position_history_id: int
    ) -> bool:
        """
        更新仓位历史ID（平仓后关联）
        
        Args:
            session: 数据库会话
            cl_ord_id: 客户端订单ID
            position_history_id: 仓位历史ID（position_history.id）
            
        Returns:
            是否更新成功
        """
        try:
            sql = text("""
                UPDATE trading_relations
                SET position_history_id = :position_history_id, updated_at = NOW()
                WHERE cl_ord_id = :cl_ord_id
            """)
            
            result = session.execute(sql, {
                'cl_ord_id': cl_ord_id,
                'position_history_id': position_history_id
            })
            
            session.commit()
            
            if result.rowcount > 0:
                logger.debug(f"更新仓位历史ID成功: cl_ord_id={cl_ord_id}, position_history_id={position_history_id}")
                return True
            return False
            
        except Exception as e:
            session.rollback()
            logger.error(
                f"更新仓位历史ID失败: cl_ord_id={cl_ord_id}, position_history_id={position_history_id}, "
                f"错误: {e}",
                exc_info=True
            )
            return False
    
    @staticmethod
    def get_position_history_id_by_pos_id(
        session: Session,
        pos_id: str,
        u_time_ms: Optional[int] = None
    ) -> Optional[int]:
        """
        根据pos_id和u_time_ms查询position_history.id
        
        Args:
            session: 数据库会话
            pos_id: OKX的posId
            u_time_ms: 仓位更新时间（毫秒时间戳），如果不提供则返回最新的记录
            
        Returns:
            position_history.id，如果未找到则返回None
        """
        try:
            if u_time_ms:
                sql = text("""
                    SELECT id
                    FROM position_history
                    WHERE pos_id = :pos_id AND u_time_ms = :u_time_ms
                    LIMIT 1
                """)
                result = session.execute(sql, {
                    'pos_id': pos_id,
                    'u_time_ms': u_time_ms
                }).fetchone()
            else:
                sql = text("""
                    SELECT id
                    FROM position_history
                    WHERE pos_id = :pos_id
                    ORDER BY u_time DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'pos_id': pos_id}).fetchone()
            
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(
                f"查询position_history.id失败: pos_id={pos_id}, u_time_ms={u_time_ms}, "
                f"错误: {e}",
                exc_info=True
            )
            return None
    
    @staticmethod
    def try_update_position_history_id_by_ord_id(
        session: Session,
        ord_id: str,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> Optional[int]:
        """
        通过ord_id主动尝试更新trading_relations的position_history_id
        
        流程：
        1. 从order_history查询ord_id对应的pos_id（从raw_data中提取）
        2. 通过pos_id查询position_history.id
        3. 如果找到，更新对应的trading_relations记录
        
        Args:
            session: 数据库会话
            ord_id: 订单ID
            max_retries: 最大重试次数（因为position_history可能还未同步）
            retry_delay: 重试延迟（秒）
            
        Returns:
            更新成功的position_history_id，如果未找到则返回None
        """
        import json
        import time
        
        for attempt in range(max_retries):
            try:
                # 1. 从order_history查询ord_id对应的pos_id和相关信息
                sql = text("""
                    SELECT raw_data, symbol, pos_side, fill_time
                    FROM order_history
                    WHERE ord_id = :ord_id
                    LIMIT 1
                """)
                result = session.execute(sql, {'ord_id': ord_id}).fetchone()
                
                if not result:
                    logger.debug(f"未找到ord_id={ord_id}的订单记录")
                    return None
                
                raw_data = result[0]
                symbol = result[1]
                pos_side = result[2]
                fill_time = result[3]
                
                # 解析raw_data获取pos_id
                pos_id = None
                if raw_data:
                    try:
                        if isinstance(raw_data, str):
                            raw_data_dict = json.loads(raw_data)
                        elif isinstance(raw_data, dict):
                            raw_data_dict = raw_data
                        else:
                            raw_data_dict = None
                        
                        if raw_data_dict:
                            pos_id = raw_data_dict.get('posId')
                    except Exception as e:
                        logger.debug(f"解析order_history.raw_data失败 ord_id={ord_id}: {e}")
                
                if not pos_id:
                    # 如果第一次尝试没有pos_id，等待后重试
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    logger.debug(f"order_history中未找到pos_id ord_id={ord_id}")
                    return None
                
                # 2. 通过pos_id查询position_history.id
                # 优先匹配时间最接近的position_history（通过fill_time和u_time匹配）
                position_history_id = None
                
                if fill_time:
                    # 尝试匹配时间最接近的position_history（60秒内）
                    match_sql = text("""
                        SELECT ph.id
                        FROM position_history ph
                        WHERE ph.pos_id = :pos_id
                          AND ph.symbol = :symbol
                          AND ph.pos_side = :pos_side
                          AND ABS(EXTRACT(EPOCH FROM (:fill_time - ph.u_time))) < 60
                        ORDER BY ABS(EXTRACT(EPOCH FROM (:fill_time - ph.u_time))) ASC
                        LIMIT 1
                    """)
                    match_result = session.execute(match_sql, {
                        'pos_id': pos_id,
                        'symbol': symbol,
                        'pos_side': pos_side,
                        'fill_time': fill_time
                    }).fetchone()
                    
                    if match_result and match_result[0]:
                        position_history_id = match_result[0]
                
                # 如果时间匹配失败，尝试获取最新的position_history
                if not position_history_id:
                    position_history_id = TradingRelationsRepository.get_position_history_id_by_pos_id(
                        session, pos_id
                    )
                
                if not position_history_id:
                    # 如果还没找到，等待后重试
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        continue
                    logger.debug(f"未找到position_history pos_id={pos_id}, ord_id={ord_id}")
                    return None
                
                # 3. 更新对应的trading_relations记录
                update_sql = text("""
                    UPDATE trading_relations
                    SET position_history_id = :position_history_id, updated_at = NOW()
                    WHERE ord_id = :ord_id
                      AND position_history_id IS NULL
                """)
                update_result = session.execute(update_sql, {
                    'position_history_id': position_history_id,
                    'ord_id': ord_id
                })
                session.commit()
                
                if update_result.rowcount > 0:
                    logger.info(
                        f"主动更新position_history_id成功: ord_id={ord_id}, "
                        f"position_history_id={position_history_id}, pos_id={pos_id}"
                    )
                    return position_history_id
                else:
                    logger.debug(f"trading_relations记录已存在position_history_id或未找到 ord_id={ord_id}")
                    return None
                    
            except Exception as e:
                logger.warning(
                    f"尝试更新position_history_id失败 ord_id={ord_id}, 尝试次数={attempt+1}/{max_retries}: {e}"
                )
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                return None
        
        return None

