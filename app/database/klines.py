"""
K线数据数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from app.database.connection import db
from app.utils.logger import logger
import pandas as pd


class KlineRepository:
    """K线数据仓库"""
    
    @staticmethod
    def get_table_name(timeframe: str) -> str:
        """根据时间周期获取表名"""
        mapping = {
            '15m': 'klines_15m',
            '4h': 'klines_4h',
            '1d': 'klines_1d',
        }
        return mapping.get(timeframe)
    
    @staticmethod
    def insert_klines(session: Session, timeframe: str, symbol: str, klines: List[Dict]) -> int:
        """
        插入K线数据（批量）
        
        Args:
            session: 数据库会话
            timeframe: 时间周期（15m/4h/1d）
            symbol: 币种名称（BTC, ETH等）
            klines: K线数据列表，格式：[{time, open, high, low, close, volume}, ...]
            
        Returns:
            插入的行数
        """
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        if not klines:
            return 0
        
        inserted_count = 0
        
        for kline in klines:
            try:
                # 转换时间戳为datetime（必须带时区）
                if isinstance(kline['time'], (int, float)):
                    kline_time = datetime.fromtimestamp(kline['time'] / 1000, tz=timezone.utc)
                else:
                    kline_time = kline['time']
                    # 确保datetime有时区信息
                    if kline_time.tzinfo is None:
                        kline_time = kline_time.replace(tzinfo=timezone.utc)
                
                # 使用ON CONFLICT DO NOTHING避免重复插入
                sql = text(f"""
                    INSERT INTO {table_name} (symbol, time, open, high, low, close, volume)
                    VALUES (:symbol, :time, :open, :high, :low, :close, :volume)
                    ON CONFLICT (symbol, time) DO NOTHING
                """)
                
                result = session.execute(sql, {
                    'symbol': symbol,
                    'time': kline_time,
                    'open': kline['open'],
                    'high': kline['high'],
                    'low': kline['low'],
                    'close': kline['close'],
                    'volume': kline['volume'],
                })
                
                if result.rowcount > 0:
                    inserted_count += 1
                else:
                    # 记录冲突的K线时间，用于调试
                    logger.debug(f"K线数据冲突（已存在）: {symbol} {timeframe} {kline_time}")
                    
            except Exception as e:
                logger.error(f"插入K线数据失败 {symbol} {timeframe} {kline.get('time')}: {e}", exc_info=True)
                continue
        
        session.commit()
        return inserted_count
    
    @staticmethod
    def get_latest_kline_time(session: Session, timeframe: str, symbol: str) -> Optional[datetime]:
        """
        获取最新K线的时间
        
        Args:
            session: 数据库会话
            timeframe: 时间周期
            symbol: 币种名称
            
        Returns:
            最新K线时间，如果没有数据则返回None
        """
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        sql = text(f"SELECT MAX(time) as latest_time FROM {table_name} WHERE symbol = :symbol")
        result = session.execute(sql, {'symbol': symbol}).fetchone()
        
        if result and result[0]:
            latest_time = result[0]
            # 确保返回的datetime有时区信息
            if latest_time.tzinfo is None:
                latest_time = latest_time.replace(tzinfo=timezone.utc)
            return latest_time
        return None
    
    @staticmethod
    def get_klines_dataframe(
        session: Session,
        timeframe: str,
        symbol: str,
        limit: int = 500,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        获取K线数据为DataFrame（用于技术指标计算）
        
        Args:
            session: 数据库会话
            timeframe: 时间周期
            symbol: 币种名称
            limit: 最大返回数量
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            
        Returns:
            DataFrame，列：time, open, high, low, close, volume
        """
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        sql = f"SELECT time, open, high, low, close, volume FROM {table_name}"
        conditions = ["symbol = :symbol"]
        params = {'symbol': symbol}
        
        if start_time:
            conditions.append("time >= :start_time")
            params['start_time'] = start_time
        
        if end_time:
            conditions.append("time <= :end_time")
            params['end_time'] = end_time
        
        sql += " WHERE " + " AND ".join(conditions)
        
        sql += " ORDER BY time DESC LIMIT :limit"
        params['limit'] = limit
        
        df = pd.read_sql(text(sql), session.bind, params=params)
        
        if not df.empty:
            df['time'] = pd.to_datetime(df['time'])
            df = df.sort_values('time').reset_index(drop=True)
            df.set_index('time', inplace=True)
        
        return df
    
    @staticmethod
    def update_indicators(
        session: Session,
        timeframe: str,
        symbol: str,
        time: datetime,
        indicators: Dict[str, Any]
    ) -> bool:
        """
        更新指定K线的技术指标
        
        Args:
            session: 数据库会话
            timeframe: 时间周期
            symbol: 币种名称
            time: K线时间
            indicators: 指标字典，如 {'ema_9': 50000, 'rsi_7': 65.5, ...}
            
        Returns:
            是否更新成功
        """
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        if not indicators:
            return False
        
        # 构建UPDATE语句
        set_clauses = []
        params = {'symbol': symbol, 'time': time}
        
        for key, value in indicators.items():
            if value is not None:
                set_clauses.append(f"{key} = :{key}")
                params[key] = value
        
        if not set_clauses:
            return False
        
        sql = text(f"""
            UPDATE {table_name}
            SET {', '.join(set_clauses)}
            WHERE symbol = :symbol AND time = :time
        """)
        
        try:
            result = session.execute(sql, params)
            session.commit()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"更新指标失败 {timeframe} {time}: {e}")
            session.rollback()
            return False
    
    @staticmethod
    def get_kline_count(session: Session, timeframe: str, symbol: str) -> int:
        """获取K线总数"""
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        sql = text(f"SELECT COUNT(*) as count FROM {table_name} WHERE symbol = :symbol")
        result = session.execute(sql, {'symbol': symbol}).fetchone()
        return result[0] if result else 0

    @staticmethod
    def get_klines_with_indicators(
        session: Session,
        timeframe: str,
        symbol: str,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        获取K线数据（包含技术指标）
        
        Args:
            session: 数据库会话
            timeframe: 时间周期（15m/4h/1d）
            symbol: 币种名称（BTC, ETH等）
            limit: 最大返回数量
            
        Returns:
            K线数据列表，每个元素包含OHLCV和技术指标
        """
        table_name = KlineRepository.get_table_name(timeframe)
        if not table_name:
            raise ValueError(f"不支持的时间周期: {timeframe}")
        
        # 根据时间周期选择需要查询的指标字段
        if timeframe == '15m':
            indicator_fields = """
                ema_9, ema_21, ema_55,
                rsi_7,
                macd_line, signal_line, histogram,
                bb_upper, bb_middle, bb_lower, bb_width,
                atr_14,
                obv, obv_ema_9,
                adx_14
            """
        elif timeframe == '4h':
            indicator_fields = """
                ema_9, ema_21,
                rsi_14,
                macd_line, signal_line, histogram,
                bb_upper, bb_middle, bb_lower,
                obv
            """
        elif timeframe == '1d':
            indicator_fields = "ema_9, ema_21"
        else:
            indicator_fields = ""
        
        sql = text(f"""
            SELECT 
                time, open, high, low, close, volume,
                {indicator_fields}
            FROM {table_name}
            WHERE symbol = :symbol
            ORDER BY time DESC
            LIMIT :limit
        """)
        
        result = session.execute(sql, {'symbol': symbol, 'limit': limit})
        rows = result.fetchall()
        
        # 转换为字典列表
        klines = []
        columns = result.keys()
        for row in rows:
            kline = dict(zip(columns, row))
            # 确保时间有时区信息
            if kline['time'] and kline['time'].tzinfo is None:
                kline['time'] = kline['time'].replace(tzinfo=timezone.utc)
            klines.append(kline)
        
        # 按时间正序排列（最旧的在前）
        klines.reverse()
        
        return klines

