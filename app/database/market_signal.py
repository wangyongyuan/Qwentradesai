"""
市场信号数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal
from app.database.connection import db
from app.utils.logger import logger
import json


class MarketSignalRepository:
    """市场信号数据仓库"""
    
    @staticmethod
    def insert_signal(
        session: Session,
        symbol: str,
        signal_type: str,
        confidence_score: float,
        market_type: str,
        detected_at: datetime,
        price: float,
        timeframe_15m_time: Optional[datetime] = None,
        timeframe_4h_time: Optional[datetime] = None,
        score_breakdown: Optional[Dict[str, Any]] = None,
        weight_config: Optional[Dict[str, Any]] = None,
        indicators_snapshot: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        插入市场信号
        
        Args:
            session: 数据库会话
            symbol: 币种名称
            signal_type: 信号类型
            confidence_score: 置信度分数
            market_type: 市场类型
            detected_at: 检测时间
            price: 检测时的价格
            timeframe_15m_time: 15分钟K线时间
            timeframe_4h_time: 4小时K线时间
            score_breakdown: 评分明细（字典）
            weight_config: 权重配置（字典）
            indicators_snapshot: 技术指标快照（字典）
            
        Returns:
            插入的信号ID，失败返回None
        """
        try:
            sql = text("""
                INSERT INTO market_signals (
                    symbol, signal_type, confidence_score, market_type, detected_at,
                    price, timeframe_15m_time, timeframe_4h_time,
                    score_breakdown, weight_config, indicators_snapshot
                )
                VALUES (
                    :symbol, :signal_type, :confidence_score, :market_type, :detected_at,
                    :price, :timeframe_15m_time, :timeframe_4h_time,
                    :score_breakdown, :weight_config, :indicators_snapshot
                )
                RETURNING id
            """)
            
            # 定义Decimal转float的辅助函数
            def decimal_to_float(obj):
                """递归将Decimal转换为float"""
                if isinstance(obj, Decimal):
                    return float(obj)
                elif isinstance(obj, dict):
                    return {k: decimal_to_float(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [decimal_to_float(item) for item in obj]
                return obj
            
            result = session.execute(sql, {
                'symbol': symbol,
                'signal_type': signal_type,
                'confidence_score': confidence_score,
                'market_type': market_type,
                'detected_at': detected_at,
                'price': price,
                'timeframe_15m_time': timeframe_15m_time,
                'timeframe_4h_time': timeframe_4h_time,
                'score_breakdown': json.dumps(decimal_to_float(score_breakdown)) if score_breakdown else None,
                'weight_config': json.dumps(decimal_to_float(weight_config)) if weight_config else None,
                'indicators_snapshot': json.dumps(decimal_to_float(indicators_snapshot)) if indicators_snapshot else None,
            })
            
            session.commit()
            signal_id = result.fetchone()[0]
            logger.info(f"市场信号已保存: ID={signal_id}, 信号类型={signal_type}, 分数={confidence_score:.2f}")
            return signal_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"插入市场信号失败: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_latest_signal(
        session: Session,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        min_score: float = 70.0
    ) -> Optional[Dict[str, Any]]:
        """
        获取最新市场信号
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            signal_type: 信号类型（可选）
            min_score: 最低分数
            
        Returns:
            信号字典，如果没有则返回None
        """
        try:
            conditions = ["confidence_score >= :min_score"]
            params = {'min_score': min_score}
            
            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol
            
            if signal_type:
                conditions.append("signal_type = :signal_type")
                params['signal_type'] = signal_type
            
            sql = text(f"""
                SELECT 
                    id, symbol, signal_type, confidence_score, market_type, detected_at,
                    price, timeframe_15m_time, timeframe_4h_time,
                    score_breakdown, weight_config, indicators_snapshot,
                    processed, opportunity_score_id, trade_id,
                    created_at, updated_at
                FROM market_signals
                WHERE {' AND '.join(conditions)}
                ORDER BY detected_at DESC
                LIMIT 1
            """)
            
            result = session.execute(sql, params).fetchone()
            
            if result:
                return dict(result._mapping)
            return None
            
        except Exception as e:
            logger.error(f"获取最新市场信号失败: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_signals(
        session: Session,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        market_type: Optional[str] = None,
        min_score: Optional[float] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        获取市场信号列表
        
        Args:
            session: 数据库会话
            symbol: 币种名称（可选）
            signal_type: 信号类型（可选）
            market_type: 市场类型（可选）
            min_score: 最低分数（可选）
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            信号字典列表
        """
        try:
            conditions = []
            params = {}
            
            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol
            
            if signal_type:
                conditions.append("signal_type = :signal_type")
                params['signal_type'] = signal_type
            
            if market_type:
                conditions.append("market_type = :market_type")
                params['market_type'] = market_type
            
            if min_score is not None:
                conditions.append("confidence_score >= :min_score")
                params['min_score'] = min_score
            
            where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
            
            sql = text(f"""
                SELECT 
                    id, symbol, signal_type, confidence_score, market_type, detected_at,
                    price, timeframe_15m_time, timeframe_4h_time,
                    score_breakdown, weight_config, indicators_snapshot,
                    processed, opportunity_score_id, trade_id,
                    created_at, updated_at
                FROM market_signals
                {where_clause}
                ORDER BY detected_at DESC
                LIMIT :limit OFFSET :offset
            """)
            
            params['limit'] = limit
            params['offset'] = offset
            
            results = session.execute(sql, params).fetchall()
            
            return [dict(row._mapping) for row in results]
            
        except Exception as e:
            logger.error(f"获取市场信号列表失败: {e}", exc_info=True)
            return []
    
    @staticmethod
    def update_signal_processed(
        session: Session,
        signal_id: int,
        processed: bool = True,
        opportunity_score_id: Optional[int] = None,
        trade_id: Optional[int] = None
    ) -> bool:
        """
        更新信号处理状态
        
        Args:
            session: 数据库会话
            signal_id: 信号ID
            processed: 是否已处理
            opportunity_score_id: 关联的机会评分ID
            trade_id: 关联的交易ID
            
        Returns:
            是否更新成功
        """
        try:
            updates = ["processed = :processed"]
            params = {'signal_id': signal_id, 'processed': processed}
            
            if opportunity_score_id is not None:
                updates.append("opportunity_score_id = :opportunity_score_id")
                params['opportunity_score_id'] = opportunity_score_id
            
            if trade_id is not None:
                updates.append("trade_id = :trade_id")
                params['trade_id'] = trade_id
            
            sql = text(f"""
                UPDATE market_signals
                SET {', '.join(updates)}
                WHERE id = :signal_id
            """)
            
            result = session.execute(sql, params)
            session.commit()
            
            return result.rowcount > 0
            
        except Exception as e:
            session.rollback()
            logger.error(f"更新信号处理状态失败: {e}", exc_info=True)
            return False

