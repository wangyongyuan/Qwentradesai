"""
恐惧贪婪指数数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import date
from typing import Optional
from app.database.connection import db
from app.utils.logger import logger


class FearGreedRepository:
    """恐惧贪婪指数数据仓库"""
    
    @staticmethod
    def _calculate_classification(value: int) -> str:
        """
        根据指数值计算分类
        
        Args:
            value: 恐惧贪婪指数值（0-100）
            
        Returns:
            分类字符串
        """
        if value <= 24:
            return "极度恐惧"
        elif value <= 44:
            return "恐惧"
        elif value <= 55:
            return "中性"
        elif value <= 75:
            return "贪婪"
        else:
            return "极度贪婪"
    
    @staticmethod
    def insert_fear_greed(
        session: Session,
        date_val: date,
        value: int,
        price: float,
        previous_value: Optional[int] = None,
        change: Optional[int] = None
    ) -> bool:
        """
        插入恐惧贪婪指数数据
        
        Args:
            session: 数据库会话
            date_val: 日期
            value: 恐惧贪婪指数值（0-100）
            price: 对应的价格数据（USD）
            previous_value: 前一天的值（可选，自动计算）
            change: 变化值（可选，自动计算）
            
        Returns:
            是否插入成功
        """
        try:
            # 如果没有提供previous_value，从数据库获取
            if previous_value is None:
                prev_date = session.execute(
                    text("SELECT MAX(date) FROM fear_greed_index WHERE date < :date"),
                    {'date': date_val}
                ).scalar()
                if prev_date:
                    prev_result = session.execute(
                        text("SELECT value FROM fear_greed_index WHERE date = :date"),
                        {'date': prev_date}
                    ).fetchone()
                    if prev_result:
                        previous_value = prev_result[0]
            
            # 计算变化值
            if change is None and previous_value is not None:
                change = value - previous_value
            
            # 计算分类
            classification = FearGreedRepository._calculate_classification(value)
            
            sql = text("""
                INSERT INTO fear_greed_index (
                    date, value, price, classification, previous_value, change
                )
                VALUES (
                    :date, :value, :price, :classification, :previous_value, :change
                )
                ON CONFLICT (date) DO UPDATE SET
                    value = EXCLUDED.value,
                    price = EXCLUDED.price,
                    classification = EXCLUDED.classification,
                    previous_value = EXCLUDED.previous_value,
                    change = EXCLUDED.change,
                    updated_at = NOW()
            """)
            
            result = session.execute(sql, {
                'date': date_val,
                'value': value,
                'price': price,
                'classification': classification,
                'previous_value': previous_value,
                'change': change,
            })
            
            session.commit()
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入恐惧贪婪指数数据失败: {e}")
            return False
    
    @staticmethod
    def get_latest_date(session: Session) -> Optional[date]:
        """
        获取最新的恐惧贪婪指数数据日期
        
        Args:
            session: 数据库会话
            
        Returns:
            最新的日期，如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT MAX(date) as latest_date
                FROM fear_greed_index
            """)
            
            result = session.execute(sql).fetchone()
            if result and result[0]:
                return result[0]
            return None
            
        except Exception as e:
            logger.error(f"获取最新恐惧贪婪指数数据日期失败: {e}")
            return None

    @staticmethod
    def get_latest_value(session: Session) -> Optional[int]:
        """
        获取最新的恐惧贪婪指数值
        
        Args:
            session: 数据库会话
            
        Returns:
            最新的指数值（0-100），如果没有数据则返回None
        """
        try:
            sql = text("""
                SELECT value
                FROM fear_greed_index
                WHERE date = (SELECT MAX(date) FROM fear_greed_index)
            """)
            
            result = session.execute(sql).fetchone()
            if result and result[0] is not None:
                return int(result[0])
            return None
            
        except Exception as e:
            logger.error(f"获取最新恐惧贪婪指数值失败: {e}")
            return None

