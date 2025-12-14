"""
技术指标计算器
"""
import pandas as pd
import numpy as np
from typing import Dict
from app.database.connection import db
from app.database.klines import KlineRepository
from app.utils.logger import logger


class IndicatorCalculator:
    """技术指标计算器"""
    
    def __init__(self):
        self.db = db
    
    def calculate_ema(self, df: pd.DataFrame, period: int) -> pd.Series:
        """计算EMA（指数移动平均）"""
        return df['close'].ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, df: pd.DataFrame, period: int) -> pd.Series:
        """计算RSI（相对强弱指标）"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(
        self,
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Dict[str, pd.Series]:
        """计算MACD指标"""
        ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
        ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        
        return {
            'macd_line': macd_line,
            'signal_line': signal_line,
            'histogram': histogram
        }
    
    def calculate_bollinger_bands(
        self,
        df: pd.DataFrame,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Dict[str, pd.Series]:
        """计算布林带"""
        middle = df['close'].rolling(window=period).mean()
        std = df['close'].rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        
        return {
            'bb_upper': upper,
            'bb_middle': middle,
            'bb_lower': lower
        }
    
    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR（平均真实波幅）"""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(window=period).mean()
        
        return atr
    
    def calculate_obv(self, df: pd.DataFrame) -> pd.Series:
        """计算OBV（能量潮指标）"""
        obv = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        return obv
    
    def calculate_adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        计算ADX（平均方向性指标）
        
        Args:
            df: K线数据DataFrame
            period: ADX计算周期，默认14
            
        Returns:
            ADX序列
        """
        # 计算真实波幅（True Range）
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        
        # 计算方向移动（Directional Movement）
        plus_dm = df['high'].diff()
        minus_dm = -df['low'].diff()
        
        # 确保方向移动的符号正确
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        
        # 如果两个方向移动同向，保留较大的，较小的设为0
        cond = (plus_dm > minus_dm)
        plus_dm[~cond] = 0
        minus_dm[cond] = 0
        
        # 平滑处理（使用Wilder's平滑方法，等同于EMA但平滑因子不同）
        # Wilder's平滑 = 前值 * (period - 1) / period + 当前值 / period
        atr = tr.ewm(alpha=1.0/period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1.0/period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1.0/period, adjust=False).mean() / atr)
        
        # 计算DX（方向性指数）
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        dx = dx.replace([np.inf, -np.inf], np.nan)
        
        # 计算ADX（DX的平滑移动平均）
        adx = dx.ewm(alpha=1.0/period, adjust=False).mean()
        
        return adx
    
    def calculate_bb_width(self, bb_upper: pd.Series, bb_middle: pd.Series, bb_lower: pd.Series) -> pd.Series:
        """
        计算布林带宽度 = (上轨 - 下轨) / 中轨
        
        Args:
            bb_upper: 布林带上轨
            bb_middle: 布林带中轨
            bb_lower: 布林带下轨
            
        Returns:
            布林带宽度序列
        """
        bb_width = (bb_upper - bb_lower) / bb_middle
        bb_width = bb_width.replace([np.inf, -np.inf], np.nan)
        return bb_width
    
    def calculate_indicators_15m(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算15分钟K线的所有指标"""
        # ADX需要至少28根K线（2倍周期），EMA55需要55根，取较大值
        min_required = max(55, 28)
        if len(df) < min_required:
            logger.warning(f"15m K线数据不足（需要至少{min_required}根），无法计算所有指标")
            return {}
        
        indicators = {}
        
        # EMA (9, 21, 55)
        indicators['ema_9'] = float(self.calculate_ema(df, 9).iloc[-1])
        indicators['ema_21'] = float(self.calculate_ema(df, 21).iloc[-1])
        indicators['ema_55'] = float(self.calculate_ema(df, 55).iloc[-1])
        
        # RSI (周期7)
        if len(df) >= 7:
            rsi_7 = self.calculate_rsi(df, 7)
            if not pd.isna(rsi_7.iloc[-1]):
                indicators['rsi_7'] = float(rsi_7.iloc[-1])
        
        # MACD (参数8,17,9)
        if len(df) >= 17:
            macd = self.calculate_macd(df, fast=8, slow=17, signal=9)
            indicators['macd_line'] = float(macd['macd_line'].iloc[-1])
            indicators['signal_line'] = float(macd['signal_line'].iloc[-1])
            indicators['histogram'] = float(macd['histogram'].iloc[-1])
        
        # 布林带 (参数20,2)
        if len(df) >= 20:
            bb = self.calculate_bollinger_bands(df, period=20, std_dev=2.0)
            indicators['bb_upper'] = float(bb['bb_upper'].iloc[-1])
            indicators['bb_middle'] = float(bb['bb_middle'].iloc[-1])
            indicators['bb_lower'] = float(bb['bb_lower'].iloc[-1])
        
        # ATR (周期14)
        if len(df) >= 14:
            atr = self.calculate_atr(df, period=14)
            if not pd.isna(atr.iloc[-1]):
                indicators['atr_14'] = float(atr.iloc[-1])
        
        # OBV + OBV_EMA(9)
        obv = self.calculate_obv(df)
        indicators['obv'] = float(obv.iloc[-1])
        if len(df) >= 9:
            obv_ema = obv.ewm(span=9, adjust=False).mean()
            indicators['obv_ema_9'] = float(obv_ema.iloc[-1])
        
        # ADX (周期14)
        if len(df) >= 28:  # ADX需要更多数据（至少2倍周期）
            adx = self.calculate_adx(df, period=14)
            if not pd.isna(adx.iloc[-1]):
                indicators['adx_14'] = float(adx.iloc[-1])
        
        # 布林带宽度（如果已计算布林带）
        if len(df) >= 20 and 'bb_upper' in indicators and 'bb_middle' in indicators and 'bb_lower' in indicators:
            if indicators['bb_middle'] > 0:
                bb_width = (indicators['bb_upper'] - indicators['bb_lower']) / indicators['bb_middle']
                indicators['bb_width'] = float(bb_width)
        
        return indicators
    
    def calculate_indicators_4h(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算4小时K线的所有指标"""
        if len(df) < 26:  # 需要足够的数据计算MACD
            logger.warning("4h K线数据不足，无法计算所有指标")
            return {}
        
        indicators = {}
        
        # EMA (9, 21)
        indicators['ema_9'] = float(self.calculate_ema(df, 9).iloc[-1])
        indicators['ema_21'] = float(self.calculate_ema(df, 21).iloc[-1])
        
        # RSI (周期14)
        if len(df) >= 14:
            rsi_14 = self.calculate_rsi(df, 14)
            if not pd.isna(rsi_14.iloc[-1]):
                indicators['rsi_14'] = float(rsi_14.iloc[-1])
        
        # MACD (参数12,26,9)
        if len(df) >= 26:
            macd = self.calculate_macd(df, fast=12, slow=26, signal=9)
            indicators['macd_line'] = float(macd['macd_line'].iloc[-1])
            indicators['signal_line'] = float(macd['signal_line'].iloc[-1])
            indicators['histogram'] = float(macd['histogram'].iloc[-1])
        
        # 布林带 (参数20,2)
        if len(df) >= 20:
            bb = self.calculate_bollinger_bands(df, period=20, std_dev=2.0)
            indicators['bb_upper'] = float(bb['bb_upper'].iloc[-1])
            indicators['bb_middle'] = float(bb['bb_middle'].iloc[-1])
            indicators['bb_lower'] = float(bb['bb_lower'].iloc[-1])
        
        # OBV (原始值)
        obv = self.calculate_obv(df)
        indicators['obv'] = float(obv.iloc[-1])
        
        return indicators
    
    def calculate_indicators_1d(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算日线K线的所有指标"""
        if len(df) < 21:
            logger.warning("1d K线数据不足，无法计算所有指标")
            return {}
        
        indicators = {}
        
        # EMA (9, 21)
        indicators['ema_9'] = float(self.calculate_ema(df, 9).iloc[-1])
        indicators['ema_21'] = float(self.calculate_ema(df, 21).iloc[-1])
        
        return indicators
    
    def update_latest_indicators(self, timeframe: str, symbol: str) -> bool:
        """
        更新最新K线的技术指标
        
        Args:
            timeframe: 时间周期（15m/4h/1d）
            symbol: 币种名称（BTC, ETH等）
            
        Returns:
            是否更新成功
        """
        session = self.db.get_session()
        try:
            # 获取足够的历史数据（用于计算指标）
            limit = 500 if timeframe == '15m' else (200 if timeframe == '4h' else 100)
            df = KlineRepository.get_klines_dataframe(session, timeframe, symbol, limit=limit)
            
            if df.empty or len(df) < 10:
                logger.warning(f"{timeframe} K线数据不足，跳过指标计算")
                return False
            
            # 计算指标
            if timeframe == '15m':
                indicators = self.calculate_indicators_15m(df)
            elif timeframe == '4h':
                indicators = self.calculate_indicators_4h(df)
            elif timeframe == '1d':
                indicators = self.calculate_indicators_1d(df)
            else:
                logger.error(f"不支持的时间周期: {timeframe}")
                return False
            
            if not indicators:
                logger.warning(f"{timeframe} 指标计算失败")
                return False
            
            # 获取最新K线时间
            latest_time = df.index[-1]
            
            # 更新数据库
            success = KlineRepository.update_indicators(
                session, timeframe, symbol, latest_time, indicators
            )
            
            # 指标已更新
            
            return success
            
        except Exception as e:
            logger.error(f"更新指标异常 {timeframe}: {e}", exc_info=True)
            session.rollback()
            return False
        finally:
            session.close()
    
    def batch_update_all_indicators(self, timeframe: str, symbol: str) -> int:
        """
        批量更新所有历史K线的技术指标
        
        Args:
            timeframe: 时间周期（15m/4h/1d）
            symbol: 币种名称（BTC, ETH等）
            
        Returns:
            成功更新的K线数量
        """
        session = self.db.get_session()
        try:
            # 获取所有K线数据
            df = KlineRepository.get_klines_dataframe(session, timeframe, symbol, limit=100000)
            
            if df.empty:
                logger.warning(f"{timeframe} 没有K线数据，跳过批量更新")
                return 0
            
            # 确定最小数据要求
            min_required = {
                '15m': 55,  # EMA55需要55根，ADX需要28根，取较大值
                '4h': 26,   # MACD需要26根
                '1d': 21,   # EMA21需要21根
            }
            min_data = min_required.get(timeframe, 10)
            
            if len(df) < min_data:
                logger.warning(f"{timeframe} K线数据不足（{len(df)} < {min_data}），无法批量更新指标")
                return 0
            
            
            # 计算所有指标（一次性计算整个DataFrame）
            if timeframe == '15m':
                indicators_df = self._calculate_all_indicators_15m(df)
            elif timeframe == '4h':
                indicators_df = self._calculate_all_indicators_4h(df)
            elif timeframe == '1d':
                indicators_df = self._calculate_all_indicators_1d(df)
            else:
                logger.error(f"不支持的时间周期: {timeframe}")
                return 0
            
            if indicators_df.empty:
                logger.warning(f"{timeframe} 指标计算失败")
                return 0
            
            # 批量更新数据库（从最小数据要求开始）
            updated_count = 0
            batch_size = 100  # 每批更新100根
            
            for i in range(min_data - 1, len(df)):
                kline_time = df.index[i]
                
                # 获取该K线的所有指标
                indicators = {}
                for col in indicators_df.columns:
                    value = indicators_df.loc[kline_time, col]
                    if pd.notna(value):
                        indicators[col] = float(value)
                
                if indicators:
                    # 更新数据库
                    success = KlineRepository.update_indicators(
                        session, timeframe, symbol, kline_time, indicators
                    )
                    if success:
                        updated_count += 1
                
                # 每批提交一次
                if (i + 1) % batch_size == 0:
                    session.commit()
            
            # 提交剩余更新
            session.commit()
            
            return updated_count
            
        except Exception as e:
            logger.error(f"批量更新指标异常 {timeframe}: {e}", exc_info=True)
            session.rollback()
            return 0
        finally:
            session.close()
    
    def _calculate_all_indicators_15m(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算15分钟K线的所有指标（返回DataFrame）"""
        result = pd.DataFrame(index=df.index)
        
        # EMA (9, 21, 55)
        result['ema_9'] = self.calculate_ema(df, 9)
        result['ema_21'] = self.calculate_ema(df, 21)
        result['ema_55'] = self.calculate_ema(df, 55)
        
        # RSI (周期7)
        if len(df) >= 7:
            result['rsi_7'] = self.calculate_rsi(df, 7)
        
        # MACD (参数8,17,9)
        if len(df) >= 17:
            macd = self.calculate_macd(df, fast=8, slow=17, signal=9)
            result['macd_line'] = macd['macd_line']
            result['signal_line'] = macd['signal_line']
            result['histogram'] = macd['histogram']
        
        # 布林带 (参数20,2)
        if len(df) >= 20:
            bb = self.calculate_bollinger_bands(df, period=20, std_dev=2.0)
            result['bb_upper'] = bb['bb_upper']
            result['bb_middle'] = bb['bb_middle']
            result['bb_lower'] = bb['bb_lower']
        
        # ATR (周期14)
        if len(df) >= 14:
            result['atr_14'] = self.calculate_atr(df, period=14)
        
        # OBV + OBV_EMA(9)
        obv = self.calculate_obv(df)
        result['obv'] = obv
        if len(df) >= 9:
            result['obv_ema_9'] = obv.ewm(span=9, adjust=False).mean()
        
        # ADX (周期14)
        if len(df) >= 28:  # ADX需要至少2倍周期
            result['adx_14'] = self.calculate_adx(df, period=14)
        
        # 布林带宽度（如果已计算布林带）
        if len(df) >= 20 and 'bb_upper' in result.columns and 'bb_middle' in result.columns and 'bb_lower' in result.columns:
            result['bb_width'] = self.calculate_bb_width(
                result['bb_upper'],
                result['bb_middle'],
                result['bb_lower']
            )
        
        return result
    
    def _calculate_all_indicators_4h(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算4小时K线的所有指标（返回DataFrame）"""
        result = pd.DataFrame(index=df.index)
        
        # EMA (9, 21)
        result['ema_9'] = self.calculate_ema(df, 9)
        result['ema_21'] = self.calculate_ema(df, 21)
        
        # RSI (周期14)
        if len(df) >= 14:
            result['rsi_14'] = self.calculate_rsi(df, 14)
        
        # MACD (参数12,26,9)
        if len(df) >= 26:
            macd = self.calculate_macd(df, fast=12, slow=26, signal=9)
            result['macd_line'] = macd['macd_line']
            result['signal_line'] = macd['signal_line']
            result['histogram'] = macd['histogram']
        
        # 布林带 (参数20,2)
        if len(df) >= 20:
            bb = self.calculate_bollinger_bands(df, period=20, std_dev=2.0)
            result['bb_upper'] = bb['bb_upper']
            result['bb_middle'] = bb['bb_middle']
            result['bb_lower'] = bb['bb_lower']
        
        # OBV (原始值)
        result['obv'] = self.calculate_obv(df)
        
        return result
    
    def _calculate_all_indicators_1d(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算日线K线的所有指标（返回DataFrame）"""
        result = pd.DataFrame(index=df.index)
        
        # EMA (9, 21)
        result['ema_9'] = self.calculate_ema(df, 9)
        result['ema_21'] = self.calculate_ema(df, 21)
        
        return result

