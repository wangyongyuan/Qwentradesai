"""
爆仓历史数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class LiquidationRepository:
    """爆仓历史数据仓库"""
    
    @staticmethod
    def insert_liquidation_data(
        session: Session,
        symbol: str,
        time: datetime,
        aggregated_long_liquidation_usd: float,
        aggregated_short_liquidation_usd: float
    ) -> bool:
        """
        插入爆仓历史数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH等）
            time: 数据时间戳
            aggregated_long_liquidation_usd: 聚合多单爆仓金额（美元）
            aggregated_short_liquidation_usd: 聚合空单爆仓金额（美元）
            
        Returns:
            是否插入成功
        """
        try:
            sql = text("""
                INSERT INTO liquidation_history (
                    symbol, time,
                    aggregated_long_liquidation_usd,
                    aggregated_short_liquidation_usd
                )
                VALUES (
                    :symbol, :time,
                    :aggregated_long_liquidation_usd,
                    :aggregated_short_liquidation_usd
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    aggregated_long_liquidation_usd = EXCLUDED.aggregated_long_liquidation_usd,
                    aggregated_short_liquidation_usd = EXCLUDED.aggregated_short_liquidation_usd
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'time': time,
                'aggregated_long_liquidation_usd': aggregated_long_liquidation_usd,
                'aggregated_short_liquidation_usd': aggregated_short_liquidation_usd,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入爆仓历史数据失败: {e}")
            return False
    
    @staticmethod
    def batch_insert_liquidation_data(
        session: Session,
        data_list: List[Dict[str, Any]]
    ) -> int:
        """
        批量插入爆仓历史数据
        
        Args:
            session: 数据库会话
            data_list: 数据列表
            
        Returns:
            成功插入的数量
        """
        if not data_list:
            return 0
        
        try:
            sql = text("""
                INSERT INTO liquidation_history (
                    symbol, time,
                    aggregated_long_liquidation_usd,
                    aggregated_short_liquidation_usd
                )
                VALUES (
                    :symbol, :time,
                    :aggregated_long_liquidation_usd,
                    :aggregated_short_liquidation_usd
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    aggregated_long_liquidation_usd = EXCLUDED.aggregated_long_liquidation_usd,
                    aggregated_short_liquidation_usd = EXCLUDED.aggregated_short_liquidation_usd
            """)
            
            result = session.execute(sql, data_list)
            session.commit()
            return result.rowcount
            
        except Exception as e:
            session.rollback()
            logger.error(f"批量插入爆仓历史数据失败: {e}")
            return 0
    
    @staticmethod
    def get_latest_time(session: Session, symbol: str) -> Optional[datetime]:
        """
        获取最新的爆仓历史数据时间
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新的时间戳，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(time) as latest_time
                FROM liquidation_history
                WHERE symbol = :symbol
            """)
            
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新爆仓历史数据时间失败: {e}")
            return None
