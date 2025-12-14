"""
ETF资金流数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger


class ETFFlowRepository:
    """ETF资金流数据仓库"""
    
    @staticmethod
    def insert_etf_flow(
        session: Session,
        symbol: str,
        date_val: date,
        net_assets_usd: float,
        change_usd: float,
        timestamp: int
    ) -> bool:
        """
        插入ETF资金流数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH）
            date_val: 日期
            net_assets_usd: 净资产总额（USD）
            change_usd: 当日资金变化（USD）
            timestamp: 日期（时间戳，单位毫秒）
            
        Returns:
            是否插入成功
        """
        try:
            sql = text("""
                INSERT INTO etf_flow_data (
                    symbol, date, net_assets_usd, change_usd, price_usd, timestamp
                )
                VALUES (
                    :symbol, :date, :net_assets_usd, :change_usd, 0, :timestamp
                )
                ON CONFLICT (symbol, date) DO UPDATE SET
                    net_assets_usd = EXCLUDED.net_assets_usd,
                    change_usd = EXCLUDED.change_usd,
                    timestamp = EXCLUDED.timestamp,
                    updated_at = NOW()
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'date': date_val,
                'net_assets_usd': net_assets_usd,
                'change_usd': change_usd,
                'timestamp': timestamp,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入ETF资金流数据失败: {e}")
            return False
    
    @staticmethod
    def batch_insert_etf_flow(
        session: Session,
        data_list: List[Dict[str, Any]]
    ) -> int:
        """
        批量插入ETF资金流数据
        
        Args:
            session: 数据库会话
            data_list: 数据列表，每条数据应包含：
                - symbol: 币种名称
                - date: 日期
                - net_assets_usd: 净资产总额（USD）
                - change_usd: 当日资金变化（USD）
                - timestamp: 日期（时间戳，单位毫秒）
            
        Returns:
            成功插入的数量
        """
        if not data_list:
            return 0
        
        try:
            sql = text("""
                INSERT INTO etf_flow_data (
                    symbol, date, net_assets_usd, change_usd, price_usd, timestamp
                )
                VALUES (
                    :symbol, :date, :net_assets_usd, :change_usd, 0, :timestamp
                )
                ON CONFLICT (symbol, date) DO UPDATE SET
                    net_assets_usd = EXCLUDED.net_assets_usd,
                    change_usd = EXCLUDED.change_usd,
                    timestamp = EXCLUDED.timestamp,
                    updated_at = NOW()
            """)
            
            # 处理数据，移除 price_usd 字段（如果存在）
            processed_data = []
            for data in data_list:
                processed_data.append({
                    'symbol': data['symbol'],
                    'date': data['date'],
                    'net_assets_usd': data['net_assets_usd'],
                    'change_usd': data['change_usd'],
                    'timestamp': data['timestamp'],
                })
            
            result = session.execute(sql, processed_data)
            session.commit()
            return result.rowcount
            
        except Exception as e:
            session.rollback()
            logger.error(f"批量插入ETF资金流数据失败: {e}")
            return 0
    
    @staticmethod
    def get_latest_date(session: Session, symbol: str) -> Optional[date]:
        """
        获取最新的ETF资金流数据日期
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新的日期，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(date) as latest_date
                FROM etf_flow_data
                WHERE symbol = :symbol
            """)
            
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新ETF资金流数据日期失败: {e}")
            return None

