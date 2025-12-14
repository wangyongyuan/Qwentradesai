"""
资金费率数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class FundingRateRepository:
    """资金费率数据仓库"""
    
    @staticmethod
    def insert_funding_rate(
        session: Session,
        symbol: str,
        time: datetime,
        funding_rate: float,
        open_interest: Optional[float] = None
    ) -> bool:
        """
        插入资金费率数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH等）
            time: 资金费率时间
            funding_rate: 资金费率
            open_interest: 持仓量（可选）
            
        Returns:
            是否插入成功
        """
        try:
            # 使用ON CONFLICT DO NOTHING避免重复插入
            sql = text("""
                INSERT INTO funding_rate_history (symbol, time, funding_rate, open_interest)
                VALUES (:symbol, :time, :funding_rate, :open_interest)
                ON CONFLICT (symbol, time) DO NOTHING
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'time': time,
                'funding_rate': funding_rate,
                'open_interest': open_interest,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            logger.error(f"插入资金费率数据失败 {symbol} {time}: {e}")
            session.rollback()
            return False
    
    @staticmethod
    def get_latest_funding_rate_time(session: Session, symbol: str) -> Optional[datetime]:
        """
        获取最新资金费率的时间
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新资金费率时间，如果没有数据则返回None
        """
        sql = text("""
            SELECT MAX(time) as latest_time 
            FROM funding_rate_history 
            WHERE symbol = :symbol
        """)
        result = session.execute(sql, {'symbol': symbol}).fetchone()
        
        if result and result[0]:
            return result[0]
        return None
    
    @staticmethod
    def get_funding_rate_history(
        session: Session,
        symbol: str,
        limit: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        获取资金费率历史数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            limit: 最大返回数量
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            
        Returns:
            资金费率历史列表
        """
        sql = """
            SELECT time, funding_rate, open_interest 
            FROM funding_rate_history
            WHERE symbol = :symbol
        """
        params = {'symbol': symbol}
        
        if start_time:
            sql += " AND time >= :start_time"
            params['start_time'] = start_time
        
        if end_time:
            sql += " AND time <= :end_time"
            params['end_time'] = end_time
        
        sql += " ORDER BY time DESC LIMIT :limit"
        params['limit'] = limit
        
        try:
            result = session.execute(text(sql), params)
            rows = result.fetchall()
            
            return [
                {
                    'time': row[0],
                    'funding_rate': float(row[1]),
                    'open_interest': float(row[2]) if row[2] else None
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"获取资金费率历史失败 {symbol}: {e}")
            return []
    
    @staticmethod
    def get_funding_rate_count(session: Session, symbol: str) -> int:
        """获取资金费率总数"""
        sql = text("""
            SELECT COUNT(*) as count 
            FROM funding_rate_history 
            WHERE symbol = :symbol
        """)
        result = session.execute(sql, {'symbol': symbol}).fetchone()
        return result[0] if result else 0

