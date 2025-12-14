"""
未平仓合约数数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class OpenInterestRepository:
    """未平仓合约数数据仓库"""
    
    @staticmethod
    def insert_open_interest(
        session: Session,
        symbol: str,
        time: datetime,
        oi_open: float,
        oi_high: float,
        oi_low: float,
        oi_close: float,
        oi_change: Optional[float] = None,
        oi_change_pct: Optional[float] = None
    ) -> bool:
        """
        插入未平仓合约数数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH等）
            time: K线时间戳
            oi_open: 开始时的未平仓合约数
            oi_high: 最高未平仓合约数
            oi_low: 最低未平仓合约数
            oi_close: 结束时的未平仓合约数
            oi_change: 持仓量变化（可选，自动计算）
            oi_change_pct: 持仓量变化百分比（可选，自动计算）
            
        Returns:
            是否插入成功
        """
        try:
            # 如果没有提供计算字段，自动计算
            if oi_change is None:
                oi_change = oi_close - oi_open
            if oi_change_pct is None and oi_open != 0:
                oi_change_pct = (oi_change / oi_open) * 100
            
            sql = text("""
                INSERT INTO open_interest_15m (
                    symbol, time, oi_open, oi_high, oi_low, oi_close,
                    oi_change, oi_change_pct
                )
                VALUES (
                    :symbol, :time, :oi_open, :oi_high, :oi_low, :oi_close,
                    :oi_change, :oi_change_pct
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    oi_open = EXCLUDED.oi_open,
                    oi_high = EXCLUDED.oi_high,
                    oi_low = EXCLUDED.oi_low,
                    oi_close = EXCLUDED.oi_close,
                    oi_change = EXCLUDED.oi_change,
                    oi_change_pct = EXCLUDED.oi_change_pct
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'time': time,
                'oi_open': oi_open,
                'oi_high': oi_high,
                'oi_low': oi_low,
                'oi_close': oi_close,
                'oi_change': oi_change,
                'oi_change_pct': oi_change_pct,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入未平仓合约数数据失败: {e}")
            return False
    
    @staticmethod
    def batch_insert_open_interest(
        session: Session,
        data_list: List[Dict[str, Any]]
    ) -> int:
        """
        批量插入未平仓合约数数据
        
        Args:
            session: 数据库会话
            data_list: 数据列表，每个元素包含 symbol, time, oi_open, oi_high, oi_low, oi_close
            
        Returns:
            成功插入的数量
        """
        if not data_list:
            return 0
        
        try:
            sql = text("""
                INSERT INTO open_interest_15m (
                    symbol, time, oi_open, oi_high, oi_low, oi_close,
                    oi_change, oi_change_pct
                )
                VALUES (
                    :symbol, :time, :oi_open, :oi_high, :oi_low, :oi_close,
                    :oi_change, :oi_change_pct
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    oi_open = EXCLUDED.oi_open,
                    oi_high = EXCLUDED.oi_high,
                    oi_low = EXCLUDED.oi_low,
                    oi_close = EXCLUDED.oi_close,
                    oi_change = EXCLUDED.oi_change,
                    oi_change_pct = EXCLUDED.oi_change_pct
            """)
            
            # 处理每条数据，计算变化字段
            processed_data = []
            for data in data_list:
                oi_open = float(data['oi_open'])
                oi_close = float(data['oi_close'])
                oi_change = oi_close - oi_open
                oi_change_pct = (oi_change / oi_open * 100) if oi_open != 0 else None
                
                processed_data.append({
                    'symbol': data['symbol'],
                    'time': data['time'],
                    'oi_open': oi_open,
                    'oi_high': float(data['oi_high']),
                    'oi_low': float(data['oi_low']),
                    'oi_close': oi_close,
                    'oi_change': oi_change,
                    'oi_change_pct': oi_change_pct,
                })
            
            result = session.execute(sql, processed_data)
            session.commit()
            return result.rowcount
            
        except Exception as e:
            session.rollback()
            logger.error(f"批量插入未平仓合约数数据失败: {e}")
            return 0
    
    @staticmethod
    def get_latest_time(session: Session, symbol: str) -> Optional[datetime]:
        """
        获取最新的未平仓合约数时间
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新的时间戳，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(time) as latest_time
                FROM open_interest_15m
                WHERE symbol = :symbol
            """)
            
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新未平仓合约数时间失败: {e}")
            return None

