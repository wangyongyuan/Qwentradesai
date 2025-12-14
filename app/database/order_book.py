"""
盘口挂单分布数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime
from typing import List, Optional, Dict, Any
import json
from app.database.connection import db
from app.utils.logger import logger


class OrderBookRepository:
    """盘口挂单分布数据仓库"""
    
    @staticmethod
    def insert_order_book(
        session: Session,
        symbol: str,
        time: datetime,
        asks: List[List[Any]],
        bids: List[List[Any]],
        total_ask_amount: Optional[float] = None,
        total_bid_amount: Optional[float] = None,
        total_ask_orders: Optional[int] = None,
        total_bid_orders: Optional[int] = None,
        bid_ask_ratio: Optional[float] = None,
        large_ask_amount: Optional[float] = None,
        large_bid_amount: Optional[float] = None
    ) -> bool:
        """
        插入盘口挂单分布数据
        
        Args:
            session: 数据库会话
            symbol: 币种名称（BTC, ETH等）
            time: 数据时间戳
            asks: 卖单深度数组
            bids: 买单深度数组
            total_ask_amount: 卖单总数量（可选，自动计算）
            total_bid_amount: 买单总数量（可选，自动计算）
            total_ask_orders: 卖单总订单数（可选，自动计算）
            total_bid_orders: 买单总订单数（可选，自动计算）
            bid_ask_ratio: 买卖比（可选，自动计算）
            large_ask_amount: 大额卖单总量（可选）
            large_bid_amount: 大额买单总量（可选）
            
        Returns:
            是否插入成功
        """
        try:
            # 如果没有提供汇总字段，自动计算
            if total_ask_amount is None:
                total_ask_amount = sum(float(ask[1]) for ask in asks if len(ask) >= 2)
            if total_bid_amount is None:
                total_bid_amount = sum(float(bid[1]) for bid in bids if len(bid) >= 2)
            if total_ask_orders is None:
                total_ask_orders = sum(int(ask[3]) for ask in asks if len(ask) >= 4)
            if total_bid_orders is None:
                total_bid_orders = sum(int(bid[3]) for bid in bids if len(bid) >= 4)
            if bid_ask_ratio is None and total_ask_amount != 0:
                bid_ask_ratio = total_bid_amount / total_ask_amount
            
            sql = text("""
                INSERT INTO order_book_distribution (
                    symbol, time, asks, bids,
                    total_ask_amount, total_bid_amount,
                    total_ask_orders, total_bid_orders,
                    bid_ask_ratio, large_ask_amount, large_bid_amount
                )
                VALUES (
                    :symbol, :time, :asks, :bids,
                    :total_ask_amount, :total_bid_amount,
                    :total_ask_orders, :total_bid_orders,
                    :bid_ask_ratio, :large_ask_amount, :large_bid_amount
                )
                ON CONFLICT (symbol, time) DO UPDATE SET
                    asks = EXCLUDED.asks,
                    bids = EXCLUDED.bids,
                    total_ask_amount = EXCLUDED.total_ask_amount,
                    total_bid_amount = EXCLUDED.total_bid_amount,
                    total_ask_orders = EXCLUDED.total_ask_orders,
                    total_bid_orders = EXCLUDED.total_bid_orders,
                    bid_ask_ratio = EXCLUDED.bid_ask_ratio,
                    large_ask_amount = EXCLUDED.large_ask_amount,
                    large_bid_amount = EXCLUDED.large_bid_amount
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'time': time,
                'asks': json.dumps(asks),
                'bids': json.dumps(bids),
                'total_ask_amount': total_ask_amount,
                'total_bid_amount': total_bid_amount,
                'total_ask_orders': total_ask_orders,
                'total_bid_orders': total_bid_orders,
                'bid_ask_ratio': bid_ask_ratio,
                'large_ask_amount': large_ask_amount,
                'large_bid_amount': large_bid_amount,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入盘口挂单分布数据失败: {e}")
            return False
    
    @staticmethod
    def get_latest_time(session: Session, symbol: str) -> Optional[datetime]:
        """
        获取最新的盘口挂单分布数据时间
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            
        Returns:
            最新的时间戳，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(time) as latest_time
                FROM order_book_distribution
                WHERE symbol = :symbol
            """)
            
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新盘口挂单分布数据时间失败: {e}")
            return None

