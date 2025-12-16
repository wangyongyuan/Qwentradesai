"""
市场检测数据仓库
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database.connection import db
from app.utils.logger import logger


class MarketDetectionRepository:
    """市场检测数据仓库"""
    
    @staticmethod
    def insert_snapshot(
        session: Session,
        symbol: str,
        detected_at: datetime,
        price: float,
        price_change_24h: Optional[float],
        kline_15m_time: datetime,
        kline_4h_time: datetime,
        kline_1d_time: Optional[datetime],
        market_mode: Optional[str],
        market_active: bool,
        trend_15m: Optional[bool],
        trend_4h: Optional[bool],
        multi_tf_aligned: bool,
        momentum_turn: bool,
        ema_cross: bool,
        rsi_extreme: bool,
        bb_breakout: bool,
        volume_surge: bool,
        price_pattern: bool,
        rsi_value: Optional[float],
        macd_histogram: Optional[float],
        volume_ratio: Optional[float],
        bb_width_ratio: Optional[float],
        volume_confirm: bool,
        bb_confirm: bool,
        has_signal: bool,
        signal_direction: Optional[str],
        signal_strength: Optional[str],
        position_size_multiplier: float,
        kline_15m_count: int,
        kline_4h_count: int,
        kline_1d_count: Optional[int],
        detection_version: str = '1.0'
    ) -> Optional[int]:
        """插入检测快照"""
        try:
            sql = text("""
                INSERT INTO market_detection_snapshots (
                    symbol, detected_at, price, price_change_24h,
                    kline_15m_time, kline_4h_time, kline_1d_time,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                    rsi_value, macd_histogram, volume_ratio, bb_width_ratio,
                    volume_confirm, bb_confirm,
                    has_signal, signal_direction, signal_strength, position_size_multiplier,
                    kline_15m_count, kline_4h_count, kline_1d_count, detection_version
                ) VALUES (
                    :symbol, :detected_at, :price, :price_change_24h,
                    :kline_15m_time, :kline_4h_time, :kline_1d_time,
                    :market_mode, :market_active, :trend_15m, :trend_4h, :multi_tf_aligned,
                    :momentum_turn, :ema_cross, :rsi_extreme, :bb_breakout, :volume_surge, :price_pattern,
                    :rsi_value, :macd_histogram, :volume_ratio, :bb_width_ratio,
                    :volume_confirm, :bb_confirm,
                    :has_signal, :signal_direction, :signal_strength, :position_size_multiplier,
                    :kline_15m_count, :kline_4h_count, :kline_1d_count, :detection_version
                ) RETURNING id
            """)
            
            result = session.execute(sql, {
                'symbol': symbol,
                'detected_at': detected_at,
                'price': price,
                'price_change_24h': price_change_24h,
                'kline_15m_time': kline_15m_time,
                'kline_4h_time': kline_4h_time,
                'kline_1d_time': kline_1d_time,
                'market_mode': market_mode,
                'market_active': market_active,
                'trend_15m': trend_15m,
                'trend_4h': trend_4h,
                'multi_tf_aligned': multi_tf_aligned,
                'momentum_turn': momentum_turn,
                'ema_cross': ema_cross,
                'rsi_extreme': rsi_extreme,
                'bb_breakout': bb_breakout,
                'volume_surge': volume_surge,
                'price_pattern': price_pattern,
                'rsi_value': rsi_value,
                'macd_histogram': macd_histogram,
                'volume_ratio': volume_ratio,
                'bb_width_ratio': bb_width_ratio,
                'volume_confirm': volume_confirm,
                'bb_confirm': bb_confirm,
                'has_signal': has_signal,
                'signal_direction': signal_direction,
                'signal_strength': signal_strength,
                'position_size_multiplier': position_size_multiplier,
                'kline_15m_count': kline_15m_count,
                'kline_4h_count': kline_4h_count,
                'kline_1d_count': kline_1d_count,
                'detection_version': detection_version
            })
            
            snapshot_id = result.fetchone()[0]
            session.commit()
            return snapshot_id
            
        except Exception as e:
            logger.error(f"插入检测快照失败: {e}", exc_info=True)
            session.rollback()
            return None
    
    @staticmethod
    def insert_signal(
        session: Session,
        snapshot_id: int,
        symbol: str,
        signal_type: str,
        detected_at: datetime,
        price: float,
        confidence_score: float,
        signal_strength: str,
        position_size_multiplier: float,
        kline_15m_time: datetime,
        kline_4h_time: datetime,
        trigger_factors: List[str],
        market_mode: Optional[str] = None,
        multi_tf_aligned: bool = False,
        rsi_value: Optional[float] = None,
        macd_histogram: Optional[float] = None,
        volume_ratio: Optional[float] = None,
        expired_at: Optional[datetime] = None
    ) -> Optional[int]:
        """插入市场信号"""
        try:
            import json
            
            sql = text("""
                INSERT INTO market_signals (
                    snapshot_id, symbol, signal_type, detected_at, price,
                    confidence_score, signal_strength, position_size_multiplier,
                    kline_15m_time, kline_4h_time, trigger_factors,
                    market_mode, multi_tf_aligned,
                    rsi_value, macd_histogram, volume_ratio,
                    expired_at, status
                ) VALUES (
                    :snapshot_id, :symbol, :signal_type, :detected_at, :price,
                    :confidence_score, :signal_strength, :position_size_multiplier,
                    :kline_15m_time, :kline_4h_time, :trigger_factors,
                    :market_mode, :multi_tf_aligned,
                    :rsi_value, :macd_histogram, :volume_ratio,
                    :expired_at, 'PENDING'
                ) RETURNING id
            """)
            
            result = session.execute(sql, {
                'snapshot_id': snapshot_id,
                'symbol': symbol,
                'signal_type': signal_type,
                'detected_at': detected_at,
                'price': price,
                'confidence_score': confidence_score,
                'signal_strength': signal_strength,
                'position_size_multiplier': position_size_multiplier,
                'kline_15m_time': kline_15m_time,
                'kline_4h_time': kline_4h_time,
                'trigger_factors': json.dumps(trigger_factors),
                'market_mode': market_mode,
                'multi_tf_aligned': multi_tf_aligned,
                'rsi_value': rsi_value,
                'macd_histogram': macd_histogram,
                'volume_ratio': volume_ratio,
                'expired_at': expired_at
            })
            
            signal_id = result.fetchone()[0]
            session.commit()
            return signal_id
            
        except Exception as e:
            logger.error(f"插入市场信号失败: {e}", exc_info=True)
            session.rollback()
            return None
    
    @staticmethod
    def get_latest_signal(
        session: Session,
        symbol: str,
        status: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """获取最新信号"""
        try:
            if status:
                sql = text("""
                    SELECT * FROM market_signals
                    WHERE symbol = :symbol AND status = :status
                    ORDER BY detected_at DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'symbol': symbol, 'status': status}).fetchone()
            else:
                sql = text("""
                    SELECT * FROM market_signals
                    WHERE symbol = :symbol
                    ORDER BY detected_at DESC
                    LIMIT 1
                """)
                result = session.execute(sql, {'symbol': symbol}).fetchone()
            
            if not result:
                return None
            
            return dict(result._mapping)
            
        except Exception as e:
            logger.error(f"获取最新信号失败: {e}", exc_info=True)
            return None
    
    @staticmethod
    def check_and_expire_signals(
        session: Session,
        symbol: Optional[str] = None
    ) -> int:
        """检查并更新过期信号"""
        try:
            if symbol:
                sql = text("""
                    UPDATE market_signals
                    SET status = 'EXPIRED', updated_at = NOW()
                    WHERE symbol = :symbol
                    AND status = 'PENDING'
                    AND expired_at IS NOT NULL
                    AND expired_at < NOW()
                """)
                result = session.execute(sql, {'symbol': symbol})
            else:
                sql = text("""
                    UPDATE market_signals
                    SET status = 'EXPIRED', updated_at = NOW()
                    WHERE status = 'PENDING'
                    AND expired_at IS NOT NULL
                    AND expired_at < NOW()
                """)
                result = session.execute(sql)
            
            expired_count = result.rowcount
            session.commit()
            return expired_count
            
        except Exception as e:
            logger.error(f"检查过期信号失败: {e}", exc_info=True)
            session.rollback()
            return 0

