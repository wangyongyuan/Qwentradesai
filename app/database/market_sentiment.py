"""
市场情绪数据（多空比）数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class MarketSentimentRepository:
    """市场情绪数据仓库"""
    
    @staticmethod
    def insert_sentiment_data(
        session: Session,
        symbol: str,
        time: datetime,
        global_account_long_percent: Optional[float],
        global_account_short_percent: Optional[float],
        global_account_long_short_ratio: Optional[float]
    ) -> bool:
        """
        插入市场情绪数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH等）
            time: 数据时间戳
            global_account_long_percent: 账户多单比例（%）
            global_account_short_percent: 账户空单比例（%）
            global_account_long_short_ratio: 账户多空比（多/空）
            
        Returns:
            是否插入成功
        """
        try:
            sql = text("""
                INSERT INTO market_sentiment_data (
                    symbol, time,
                    global_account_long_percent,
                    global_account_short_percent,
                    global_account_long_short_ratio
                )
                VALUES (
                    :symbol, :time,
                    :global_account_long_percent,
                    :global_account_short_percent,
                    :global_account_long_short_ratio
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    global_account_long_percent = EXCLUDED.global_account_long_percent,
                    global_account_short_percent = EXCLUDED.global_account_short_percent,
                    global_account_long_short_ratio = EXCLUDED.global_account_long_short_ratio
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'time': time,
                'global_account_long_percent': global_account_long_percent,
                'global_account_short_percent': global_account_short_percent,
                'global_account_long_short_ratio': global_account_long_short_ratio,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入市场情绪数据失败: {e}")
            return False
    
    @staticmethod
    def batch_insert_sentiment_data(
        session: Session,
        data_list: List[Dict[str, Any]]
    ) -> int:
        """
        批量插入市场情绪数据
        
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
                INSERT INTO market_sentiment_data (
                    symbol, time,
                    global_account_long_percent,
                    global_account_short_percent,
                    global_account_long_short_ratio
                )
                VALUES (
                    :symbol, :time,
                    :global_account_long_percent,
                    :global_account_short_percent,
                    :global_account_long_short_ratio
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    global_account_long_percent = EXCLUDED.global_account_long_percent,
                    global_account_short_percent = EXCLUDED.global_account_short_percent,
                    global_account_long_short_ratio = EXCLUDED.global_account_long_short_ratio
            """)
            
            result = session.execute(sql, data_list)
            session.commit()
            return result.rowcount
            
        except Exception as e:
            session.rollback()
            logger.error(f"批量插入市场情绪数据失败: {e}")
            return 0
    
    @staticmethod
    def get_latest_time(session: Session, symbol: str) -> Optional[datetime]:
        """
        获取最新的市场情绪数据时间
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新的时间戳，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(time) as latest_time
                FROM market_sentiment_data
                WHERE symbol = :symbol
            """)
            
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新市场情绪数据时间失败: {e}")
            return None

