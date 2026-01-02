"""
市场检测器模块
采用层级过滤模型，通过三层过滤机制确保信号质量
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple, Any
from app.database.connection import db
from app.database.klines import KlineRepository
from app.config import settings
from app.utils.logger import logger
from sqlalchemy import text
import statistics
import json


class MarketDetector:
    """市场检测器 - 基于技术指标自动识别交易机会"""
    
    def __init__(self, symbol: str):
        """
        初始化市场检测器
        
        Args:
            symbol: 币种名称（ETH, BTC等）
        """
        self.symbol = symbol
        self.db = db
        
        logger.info(f"市场检测器初始化完成: {symbol}")
    
    def _get_klines(self, timeframe: str, count: int) -> List[Dict[str, Any]]:
        """
        获取K线数据（含技术指标）
        
        Args:
            timeframe: 时间周期（15m/4h）
            count: 获取数量
            
        Returns:
            K线数据列表，按时间正序排列（最旧的在前）
        """
        session = self.db.get_session()
        try:
            klines = KlineRepository.get_klines_with_indicators(
                session, timeframe, self.symbol, limit=count
            )
            
            if not klines:
                logger.warning(f"[{self.symbol}] {timeframe} K线数据为空")
                return []
            
            logger.debug(f"[{self.symbol}] 获取{timeframe} K线: {len(klines)}根")
            return klines
            
        except Exception as e:
            logger.error(f"[{self.symbol}] 获取{timeframe} K线失败: {e}", exc_info=True)
            return []
        finally:
            session.close()
    
    def _filter_layer(
        self, 
        klines_15m: List[Dict[str, Any]], 
        klines_4h: List[Dict[str, Any]]
    ) -> Tuple[str, bool, Optional[bool], Optional[bool], bool]:
        """
        环境层过滤 - 判断市场模式和活跃度
        
        Args:
            klines_15m: 15m K线数据列表
            klines_4h: 4h K线数据列表
            
        Returns:
            (market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned)
            - market_mode: BULL/BEAR/NEUTRAL
            - market_active: 市场是否活跃
            - trend_15m: 15m趋势方向（True=上涨，False=下跌，None=无法判断）
            - trend_4h: 4h趋势方向
            - multi_tf_aligned: 多时间框架是否对齐
        """
        if not klines_15m or not klines_4h:
            logger.warning(f"[{self.symbol}] K线数据不足，无法进行环境层过滤")
            return 'NEUTRAL', False, None, None, False
        
        latest_15m = klines_15m[-1]
        latest_4h = klines_4h[-1]
        
        # 1. 市场模式判断（基于15m价格 vs EMA55）
        price_15m = float(latest_15m['close'])
        ema_55 = latest_15m.get('ema_55')
        
        if ema_55 is None:
            logger.warning(f"[{self.symbol}] EMA55未计算，无法判断市场模式")
            market_mode = 'NEUTRAL'
            trend_15m = None
        else:
            ema_55 = float(ema_55)
            if price_15m > ema_55:
                market_mode = 'BULL'
                trend_15m = True
            elif price_15m < ema_55:
                market_mode = 'BEAR'
                trend_15m = False
            else:
                market_mode = 'NEUTRAL'
                trend_15m = None
        
        # 2. 市场活跃度判断（基于布林带宽度）
        bb_widths = [
            float(k.get('bb_width', 0) or 0)
            for k in klines_15m[-20:]
            if k.get('bb_width') is not None
        ]
        
        if bb_widths:
            avg_bb_width = statistics.mean(bb_widths)
            current_bb_width = float(latest_15m.get('bb_width', 0) or 0)
            threshold = settings.DETECTOR_BB_WIDTH_THRESHOLD
            market_active = current_bb_width >= (avg_bb_width * threshold)
        else:
            logger.warning(f"[{self.symbol}] 布林带宽度数据不足，认为市场不活跃")
            market_active = False
        
        # 3. 多时间框架对齐判断（15m和4h趋势是否一致）
        price_4h = float(latest_4h['close'])
        ema_21_4h = latest_4h.get('ema_21')
        
        if ema_21_4h is None:
            trend_4h = None
            multi_tf_aligned = False
        else:
            ema_21_4h = float(ema_21_4h)
            trend_4h = price_4h > ema_21_4h
            if trend_15m is not None and trend_4h is not None:
                multi_tf_aligned = (trend_15m == trend_4h)
            else:
                multi_tf_aligned = False
        
        logger.info(
            f"[{self.symbol}] 环境层: mode={market_mode}, active={market_active}, "
            f"trend_15m={trend_15m}, trend_4h={trend_4h}, aligned={multi_tf_aligned}"
        )
        
        return market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned
    
    def _check_momentum_turn(
        self, 
        klines_15m: List[Dict[str, Any]], 
        market_mode: str
    ) -> Tuple[bool, Optional[float]]:
        """
        检查MACD动量转折
        
        Args:
            klines_15m: 15m K线数据列表
            market_mode: 市场模式（BULL/BEAR）
            
        Returns:
            (是否触发, MACD柱状图值)
        """
        if len(klines_15m) < 2:
            return False, None
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        hist_latest = latest.get('histogram')
        hist_prev = prev.get('histogram')
        
        if hist_latest is None or hist_prev is None:
            return False, None
        
        # 转换为float类型
        hist_latest = float(hist_latest)
        hist_prev = float(hist_prev)
        
        # 多头模式
        if market_mode == 'BULL':
            # 情况1：MACD柱从负转正（金叉）
            if hist_prev <= 0 and hist_latest > 0:
                logger.debug(f"[{self.symbol}] MACD动量转折: 从负转正, histogram={hist_latest}")
                return True, hist_latest
            # 情况2：MACD柱持续增大（动量增强）
            if hist_prev > 0 and hist_latest > hist_prev:
                logger.debug(f"[{self.symbol}] MACD动量转折: 持续增大, histogram={hist_latest}")
                return True, hist_latest
        
        # 空头模式
        elif market_mode == 'BEAR':
            # 情况1：MACD柱从正转负（死叉）
            if hist_prev >= 0 and hist_latest < 0:
                logger.debug(f"[{self.symbol}] MACD动量转折: 从正转负, histogram={hist_latest}")
                return True, hist_latest
            # 情况2：MACD柱持续减小（动量减弱）
            if hist_prev < 0 and hist_latest < hist_prev:
                logger.debug(f"[{self.symbol}] MACD动量转折: 持续减小, histogram={hist_latest}")
                return True, hist_latest
        
        return False, hist_latest
    
    def _check_ema_cross(
        self, 
        klines_15m: List[Dict[str, Any]], 
        market_mode: str
    ) -> bool:
        """
        检查EMA交叉
        
        Args:
            klines_15m: 15m K线数据列表
            market_mode: 市场模式（BULL/BEAR）
            
        Returns:
            是否触发
        """
        if len(klines_15m) < 2:
            return False
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        ema9_latest = latest.get('ema_9')
        ema21_latest = latest.get('ema_21')
        ema9_prev = prev.get('ema_9')
        ema21_prev = prev.get('ema_21')
        
        if ema9_latest is None or ema21_latest is None or \
           ema9_prev is None or ema21_prev is None:
            return False
        
        # 转换为float类型
        ema9_latest = float(ema9_latest)
        ema21_latest = float(ema21_latest)
        ema9_prev = float(ema9_prev)
        ema21_prev = float(ema21_prev)
        
        # 多头模式：EMA9上穿EMA21
        if market_mode == 'BULL':
            if ema9_prev <= ema21_prev and ema9_latest > ema21_latest:
                logger.debug(f"[{self.symbol}] EMA交叉: EMA9上穿EMA21")
                return True
        
        # 空头模式：EMA9下穿EMA21
        elif market_mode == 'BEAR':
            if ema9_prev >= ema21_prev and ema9_latest < ema21_latest:
                logger.debug(f"[{self.symbol}] EMA交叉: EMA9下穿EMA21")
                return True
        
        return False
    
    def _check_rsi_extreme(
        self, 
        klines_15m: List[Dict[str, Any]], 
        market_mode: str
    ) -> Tuple[bool, Optional[float], float]:
        """
        检查RSI极值
        
        Args:
            klines_15m: 15m K线数据列表
            market_mode: 市场模式（BULL/BEAR）
            
        Returns:
            (是否触发, RSI值, 仓位倍数)
        """
        if not klines_15m:
            return False, None, 1.0
        
        latest = klines_15m[-1]
        rsi = latest.get('rsi_7')
        
        if rsi is None:
            return False, None, 1.0
        
        # 转换为float类型
        rsi = float(rsi)
        
        # 多头模式
        if market_mode == 'BULL':
            rsi_long_threshold = settings.DETECTOR_RSI_LONG_THRESHOLD
            rsi_double = settings.DETECTOR_RSI_DOUBLE_POSITION_LONG
            
            if rsi < rsi_long_threshold:
                # RSI低于阈值，允许做多
                if rsi < rsi_double:
                    position_multiplier = 2.0  # RSI极低，加倍仓位
                else:
                    position_multiplier = 1.0
                logger.debug(f"[{self.symbol}] RSI极值: RSI={rsi}, multiplier={position_multiplier}")
                return True, rsi, position_multiplier
        
        # 空头模式
        elif market_mode == 'BEAR':
            rsi_short_threshold = settings.DETECTOR_RSI_SHORT_THRESHOLD
            rsi_double = settings.DETECTOR_RSI_DOUBLE_POSITION_SHORT
            
            if rsi > rsi_short_threshold:
                # RSI高于阈值，允许做空
                if rsi > rsi_double:
                    position_multiplier = 2.0  # RSI极高，加倍仓位
                else:
                    position_multiplier = 1.0
                logger.debug(f"[{self.symbol}] RSI极值: RSI={rsi}, multiplier={position_multiplier}")
                return True, rsi, position_multiplier
        
        return False, rsi, 1.0
    
    def _check_bb_breakout(
        self, 
        klines_15m: List[Dict[str, Any]], 
        market_mode: str
    ) -> bool:
        """
        检查布林带突破
        
        Args:
            klines_15m: 15m K线数据列表
            market_mode: 市场模式（BULL/BEAR）
            
        Returns:
            是否触发
        """
        if not klines_15m:
            return False
        
        latest = klines_15m[-1]
        close = float(latest['close'])
        bb_upper = latest.get('bb_upper')
        bb_lower = latest.get('bb_lower')
        
        if bb_upper is None or bb_lower is None:
            return False
        
        # 转换为float类型
        bb_upper = float(bb_upper)
        bb_lower = float(bb_lower)
        
        # 多头模式：价格突破上轨
        if market_mode == 'BULL':
            if close > bb_upper:
                logger.debug(f"[{self.symbol}] 布林带突破: 价格突破上轨, close={close}, upper={bb_upper}")
                return True
        
        # 空头模式：价格跌破下轨
        elif market_mode == 'BEAR':
            if close < bb_lower:
                logger.debug(f"[{self.symbol}] 布林带突破: 价格跌破下轨, close={close}, lower={bb_lower}")
                return True
        
        return False
    
    def _check_volume_surge(
        self, 
        klines_15m: List[Dict[str, Any]]
    ) -> Tuple[bool, float]:
        """
        检查成交量异常
        
        Args:
            klines_15m: 15m K线数据列表
            
        Returns:
            (是否触发, 成交量比率)
        """
        if len(klines_15m) < 2:
            return False, 0.0
        
        latest = klines_15m[-1]
        current_volume = float(latest['volume'])
        
        # 计算最近20根K线的平均成交量和标准差
        volumes = [float(k['volume']) for k in klines_15m[-20:]]
        avg_volume = statistics.mean(volumes)
        
        # 计算标准差（至少需要2个数据点）
        if len(volumes) < 2:
            std_volume = 0
        else:
            std_volume = statistics.stdev(volumes)
        
        # 动态阈值
        threshold = avg_volume + (settings.DETECTOR_VOLUME_STD_MULTIPLIER * std_volume)
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        # 判断是否异常
        if current_volume > threshold:
            logger.debug(
                f"[{self.symbol}] 成交量异常: volume={current_volume}, "
                f"avg={avg_volume}, threshold={threshold}, ratio={volume_ratio:.2f}"
            )
            return True, volume_ratio
        
        return False, volume_ratio
    
    def _check_price_pattern(
        self, 
        klines_15m: List[Dict[str, Any]], 
        market_mode: str
    ) -> bool:
        """
        检查价格形态（吞没形态）
        
        Args:
            klines_15m: 15m K线数据列表
            market_mode: 市场模式（BULL/BEAR）
            
        Returns:
            是否触发
        """
        if len(klines_15m) < 2:
            return False
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        # 转换为float类型
        prev_open = float(prev['open'])
        prev_close = float(prev['close'])
        latest_open = float(latest['open'])
        latest_close = float(latest['close'])
        
        # 多头模式：看涨吞没
        if market_mode == 'BULL':
            prev_bearish = prev_close < prev_open  # 前一根是阴线
            latest_bullish = latest_close > latest_open  # 当前是阳线
            engulfed = latest_open < prev_close and latest_close > prev_open  # 完全吞没
            
            if prev_bearish and latest_bullish and engulfed:
                logger.debug(f"[{self.symbol}] 价格形态: 看涨吞没")
                return True
        
        # 空头模式：看跌吞没
        elif market_mode == 'BEAR':
            prev_bullish = prev_close > prev_open  # 前一根是阳线
            latest_bearish = latest_close < latest_open  # 当前是阴线
            engulfed = latest_open > prev_close and latest_close < prev_open  # 完全吞没
            
            if prev_bullish and latest_bearish and engulfed:
                logger.debug(f"[{self.symbol}] 价格形态: 看跌吞没")
                return True
        
        return False
    
    def _confirmation_layer(
        self, 
        klines_15m: List[Dict[str, Any]]
    ) -> Tuple[bool, bool, float, float]:
        """
        确认层验证 - 成交量和布林带确认
        
        Args:
            klines_15m: 15m K线数据列表
            
        Returns:
            (volume_confirm, bb_confirm, volume_ratio, bb_width_ratio)
            - volume_confirm: 成交量是否确认
            - bb_confirm: 布林带是否确认
            - volume_ratio: 成交量比率（当前/平均）
            - bb_width_ratio: 布林带宽度比率（当前/平均）
        """
        if not klines_15m:
            return False, False, 0.0, 0.0
        
        latest = klines_15m[-1]
        
        # 1. 成交量确认（使用与触发层相同的检测方法）
        volume_confirm, volume_ratio = self._check_volume_surge(klines_15m)
        
        # 2. 布林带确认（宽度扩大）
        bb_widths = [
            float(k.get('bb_width', 0) or 0)
            for k in klines_15m[-20:]
            if k.get('bb_width') is not None
        ]
        
        current_bb_width = float(latest.get('bb_width', 0) or 0)
        bb_confirm = False
        bb_width_ratio = 0.0
        
        if bb_widths and current_bb_width > 0:
            avg_bb_width = statistics.mean(bb_widths)
            if avg_bb_width > 0:
                bb_width_ratio = current_bb_width / avg_bb_width
                threshold = settings.DETECTOR_BB_CONFIRM_THRESHOLD
                bb_confirm = bb_width_ratio > threshold
        
        logger.info(
            f"[{self.symbol}] 确认层: volume_confirm={volume_confirm}, "
            f"bb_confirm={bb_confirm}, volume_ratio={volume_ratio:.2f}, "
            f"bb_width_ratio={bb_width_ratio:.2f}"
        )
        
        return volume_confirm, bb_confirm, volume_ratio, bb_width_ratio
    
    def _calculate_signal_strength(
        self,
        trigger_count: int,
        multi_tf_aligned: bool,
        volume_confirm: bool,
        bb_confirm: bool
    ) -> str:
        """
        计算信号强度
        
        Args:
            trigger_count: 触发维度数量
            multi_tf_aligned: 多时间框架是否对齐
            volume_confirm: 成交量是否确认
            bb_confirm: 布林带是否确认
            
        Returns:
            信号强度：WEAK/MODERATE/STRONG/VERY_STRONG
        """
        score = trigger_count
        if multi_tf_aligned:
            score += 0.5
        if volume_confirm:
            score += 1.0
        if bb_confirm:
            score += 1.0
        
        if score >= 4:
            return 'VERY_STRONG'
        elif score >= 3:
            return 'STRONG'
        elif score >= 2:
            return 'MODERATE'
        else:
            return 'WEAK'
    
    def _calculate_confidence_score(
        self,
        trigger_count: int,
        multi_tf_aligned: bool,
        volume_confirm: bool,
        bb_confirm: bool
    ) -> float:
        """
        计算置信度分数（0-100）
        
        Args:
            trigger_count: 触发维度数量
            multi_tf_aligned: 多时间框架是否对齐
            volume_confirm: 成交量是否确认
            bb_confirm: 布林带是否确认
            
        Returns:
            置信度分数（0-100）
        """
        score = trigger_count * 15
        if multi_tf_aligned:
            score += 10
        if volume_confirm:
            score += 15
        if bb_confirm:
            score += 15
        
        return min(100.0, float(score))
    
    def _save_snapshot(
        self,
        detected_at: datetime,
        price: float,
        kline_15m_time: datetime,
        kline_4h_time: datetime,
        market_mode: str,
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
        volume_ratio: float,
        bb_width_ratio: float,
        volume_confirm: bool,
        bb_confirm: bool,
        has_signal: bool,
        signal_direction: Optional[str],
        signal_strength: Optional[str],
        position_size_multiplier: float,
        kline_15m_count: int,
        kline_4h_count: int
    ) -> Optional[int]:
        """
        保存检测快照到数据库
        
        Returns:
            快照ID，失败返回None
        """
        session = self.db.get_session()
        try:
            sql = text("""
                INSERT INTO market_detection_snapshots (
                    symbol, detected_at, price,
                    kline_15m_time, kline_4h_time,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                    rsi_value, macd_histogram, volume_ratio, bb_width_ratio,
                    volume_confirm, bb_confirm,
                    has_signal, signal_direction, signal_strength, position_size_multiplier,
                    kline_15m_count, kline_4h_count
                )
                VALUES (
                    :symbol, :detected_at, :price,
                    :kline_15m_time, :kline_4h_time,
                    :market_mode, :market_active, :trend_15m, :trend_4h, :multi_tf_aligned,
                    :momentum_turn, :ema_cross, :rsi_extreme, :bb_breakout, :volume_surge, :price_pattern,
                    :rsi_value, :macd_histogram, :volume_ratio, :bb_width_ratio,
                    :volume_confirm, :bb_confirm,
                    :has_signal, :signal_direction, :signal_strength, :position_size_multiplier,
                    :kline_15m_count, :kline_4h_count
                )
                RETURNING id
            """)
            
            result = session.execute(sql, {
                'symbol': self.symbol,
                'detected_at': detected_at,
                'price': price,
                'kline_15m_time': kline_15m_time,
                'kline_4h_time': kline_4h_time,
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
            })
            
            session.commit()
            snapshot_id = result.fetchone()[0]
            logger.info(f"[{self.symbol}] 检测快照已保存: ID={snapshot_id}, has_signal={has_signal}")
            return snapshot_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"[{self.symbol}] 保存检测快照失败: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    def _save_signal(
        self,
        snapshot_id: int,
        signal_type: str,
        detected_at: datetime,
        price: float,
        confidence_score: float,
        signal_strength: str,
        position_size_multiplier: float,
        kline_15m_time: datetime,
        kline_4h_time: datetime,
        trigger_factors: List[str],
        market_mode: str,
        multi_tf_aligned: bool,
        rsi_value: Optional[float],
        macd_histogram: Optional[float],
        volume_ratio: float
    ) -> Optional[int]:
        """
        保存交易信号到数据库
        
        Returns:
            信号ID，失败返回None
        """
        session = self.db.get_session()
        try:
            # 计算过期时间
            expired_at = detected_at + timedelta(hours=settings.DETECTOR_SIGNAL_EXPIRE_HOURS)
            
            sql = text("""
                INSERT INTO market_signals (
                    snapshot_id, symbol, signal_type, detected_at, price,
                    confidence_score, signal_strength, position_size_multiplier,
                    kline_15m_time, kline_4h_time,
                    trigger_factors, market_mode, multi_tf_aligned,
                    rsi_value, macd_histogram, volume_ratio,
                    expired_at
                )
                VALUES (
                    :snapshot_id, :symbol, :signal_type, :detected_at, :price,
                    :confidence_score, :signal_strength, :position_size_multiplier,
                    :kline_15m_time, :kline_4h_time,
                    :trigger_factors, :market_mode, :multi_tf_aligned,
                    :rsi_value, :macd_histogram, :volume_ratio,
                    :expired_at
                )
                RETURNING id
            """)
            
            result = session.execute(sql, {
                'snapshot_id': snapshot_id,
                'symbol': self.symbol,
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
                'expired_at': expired_at,
            })
            
            session.commit()
            signal_id = result.fetchone()[0]
            logger.info(
                f"[{self.symbol}] 交易信号已保存: ID={signal_id}, type={signal_type}, "
                f"strength={signal_strength}, confidence={confidence_score:.2f}"
            )
            return signal_id
            
        except Exception as e:
            session.rollback()
            logger.error(f"[{self.symbol}] 保存交易信号失败: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    def detect(self) -> Optional[Dict[str, Any]]:
        """
        执行完整检测流程
        
        Returns:
            信号信息字典，如果没有信号则返回None
        """
        detected_at = datetime.now(timezone.utc)
        
        try:
            logger.info(f"[{self.symbol}] 开始市场检测")
            
            # 1. 获取K线数据
            kline_15m_count = settings.DETECTOR_KLINE_15M_COUNT
            kline_4h_count = settings.DETECTOR_KLINE_4H_COUNT
            
            klines_15m = self._get_klines('15m', kline_15m_count)
            klines_4h = self._get_klines('4h', kline_4h_count)
            
            if not klines_15m or not klines_4h:
                logger.warning(f"[{self.symbol}] K线数据不足，无法进行检测")
                return None
            
            latest_15m = klines_15m[-1]
            latest_4h = klines_4h[-1]
            price = float(latest_15m['close'])
            kline_15m_time = latest_15m['time']
            kline_4h_time = latest_4h['time']
            
            # 2. 环境层过滤
            market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned = self._filter_layer(
                klines_15m, klines_4h
            )
            
            # 如果NEUTRAL或不活跃，保存快照并退出
            if market_mode == 'NEUTRAL' or not market_active:
                snapshot_id = self._save_snapshot(
                    detected_at=detected_at,
                    price=price,
                    kline_15m_time=kline_15m_time,
                    kline_4h_time=kline_4h_time,
                    market_mode=market_mode,
                    market_active=market_active,
                    trend_15m=trend_15m,
                    trend_4h=trend_4h,
                    multi_tf_aligned=multi_tf_aligned,
                    momentum_turn=False,
                    ema_cross=False,
                    rsi_extreme=False,
                    bb_breakout=False,
                    volume_surge=False,
                    price_pattern=False,
                    rsi_value=None,
                    macd_histogram=None,
                    volume_ratio=0.0,
                    bb_width_ratio=0.0,
                    volume_confirm=False,
                    bb_confirm=False,
                    has_signal=False,
                    signal_direction=None,
                    signal_strength=None,
                    position_size_multiplier=1.0,
                    kline_15m_count=len(klines_15m),
                    kline_4h_count=len(klines_4h)
                )
                logger.info(f"[{self.symbol}] 环境层过滤: mode={market_mode}, active={market_active}")
                return None
            
            # 3. 触发层检测（6个维度）
            momentum_turn, macd_hist = self._check_momentum_turn(klines_15m, market_mode)
            ema_cross = self._check_ema_cross(klines_15m, market_mode)
            rsi_extreme, rsi_value, rsi_multiplier = self._check_rsi_extreme(klines_15m, market_mode)
            bb_breakout = self._check_bb_breakout(klines_15m, market_mode)
            volume_surge, volume_ratio = self._check_volume_surge(klines_15m)
            price_pattern = self._check_price_pattern(klines_15m, market_mode)
            
            # 统计触发维度数量
            trigger_factors = []
            trigger_count = 0
            if momentum_turn:
                trigger_factors.append('momentum_turn')
                trigger_count += 1
            if ema_cross:
                trigger_factors.append('ema_cross')
                trigger_count += 1
            if rsi_extreme:
                trigger_factors.append('rsi_extreme')
                trigger_count += 1
            if bb_breakout:
                trigger_factors.append('bb_breakout')
                trigger_count += 1
            if volume_surge:
                trigger_factors.append('volume_surge')
                trigger_count += 1
            if price_pattern:
                trigger_factors.append('price_pattern')
                trigger_count += 1
            
            # 4. 确认层验证（即使无触发也计算，用于保存快照）
            volume_confirm, bb_confirm, volume_ratio_confirm, bb_width_ratio = self._confirmation_layer(
                klines_15m
            )
            
            # 如果无任何触发，保存快照并退出
            if trigger_count == 0:
                snapshot_id = self._save_snapshot(
                    detected_at=detected_at,
                    price=price,
                    kline_15m_time=kline_15m_time,
                    kline_4h_time=kline_4h_time,
                    market_mode=market_mode,
                    market_active=market_active,
                    trend_15m=trend_15m,
                    trend_4h=trend_4h,
                    multi_tf_aligned=multi_tf_aligned,
                    momentum_turn=momentum_turn,
                    ema_cross=ema_cross,
                    rsi_extreme=rsi_extreme,
                    bb_breakout=bb_breakout,
                    volume_surge=volume_surge,
                    price_pattern=price_pattern,
                    rsi_value=rsi_value,
                    macd_histogram=macd_hist,
                    volume_ratio=volume_ratio_confirm,
                    bb_width_ratio=bb_width_ratio,
                    volume_confirm=volume_confirm,
                    bb_confirm=bb_confirm,
                    has_signal=False,
                    signal_direction=None,
                    signal_strength=None,
                    position_size_multiplier=rsi_multiplier,
                    kline_15m_count=len(klines_15m),
                    kline_4h_count=len(klines_4h)
                )
                logger.info(f"[{self.symbol}] 触发层: 无任何触发")
                return None
            
            # 如果无任何确认，保存快照并退出
            if not volume_confirm and not bb_confirm:
                snapshot_id = self._save_snapshot(
                    detected_at=detected_at,
                    price=price,
                    kline_15m_time=kline_15m_time,
                    kline_4h_time=kline_4h_time,
                    market_mode=market_mode,
                    market_active=market_active,
                    trend_15m=trend_15m,
                    trend_4h=trend_4h,
                    multi_tf_aligned=multi_tf_aligned,
                    momentum_turn=momentum_turn,
                    ema_cross=ema_cross,
                    rsi_extreme=rsi_extreme,
                    bb_breakout=bb_breakout,
                    volume_surge=volume_surge,
                    price_pattern=price_pattern,
                    rsi_value=rsi_value,
                    macd_histogram=macd_hist,
                    volume_ratio=volume_ratio_confirm,
                    bb_width_ratio=bb_width_ratio,
                    volume_confirm=volume_confirm,
                    bb_confirm=bb_confirm,
                    has_signal=False,
                    signal_direction=None,
                    signal_strength=None,
                    position_size_multiplier=rsi_multiplier,
                    kline_15m_count=len(klines_15m),
                    kline_4h_count=len(klines_4h)
                )
                logger.info(f"[{self.symbol}] 确认层: 无任何确认")
                return None
            
            # 5. 生成信号
            # 确定信号方向
            signal_direction = 'LONG' if market_mode == 'BULL' else 'SHORT'
            signal_type = signal_direction
            
            # 计算信号强度和置信度
            signal_strength = self._calculate_signal_strength(
                trigger_count, multi_tf_aligned, volume_confirm, bb_confirm
            )
            confidence_score = self._calculate_confidence_score(
                trigger_count, multi_tf_aligned, volume_confirm, bb_confirm
            )
            
            # 使用RSI的仓位倍数（如果有），否则使用1.0
            position_multiplier = rsi_multiplier if rsi_extreme else 1.0
            
            # 保存检测快照
            snapshot_id = self._save_snapshot(
                detected_at=detected_at,
                price=price,
                kline_15m_time=kline_15m_time,
                kline_4h_time=kline_4h_time,
                market_mode=market_mode,
                market_active=market_active,
                trend_15m=trend_15m,
                trend_4h=trend_4h,
                multi_tf_aligned=multi_tf_aligned,
                momentum_turn=momentum_turn,
                ema_cross=ema_cross,
                rsi_extreme=rsi_extreme,
                bb_breakout=bb_breakout,
                volume_surge=volume_surge,
                price_pattern=price_pattern,
                rsi_value=rsi_value,
                macd_histogram=macd_hist,
                volume_ratio=volume_ratio_confirm,
                bb_width_ratio=bb_width_ratio,
                volume_confirm=volume_confirm,
                bb_confirm=bb_confirm,
                has_signal=True,
                signal_direction=signal_direction,
                signal_strength=signal_strength,
                position_size_multiplier=position_multiplier,
                kline_15m_count=len(klines_15m),
                kline_4h_count=len(klines_4h)
            )
            
            if not snapshot_id:
                logger.error(f"[{self.symbol}] 保存检测快照失败")
                return None
            
            # 保存交易信号
            signal_id = self._save_signal(
                snapshot_id=snapshot_id,
                signal_type=signal_type,
                detected_at=detected_at,
                price=price,
                confidence_score=confidence_score,
                signal_strength=signal_strength,
                position_size_multiplier=position_multiplier,
                kline_15m_time=kline_15m_time,
                kline_4h_time=kline_4h_time,
                trigger_factors=trigger_factors,
                market_mode=market_mode,
                multi_tf_aligned=multi_tf_aligned,
                rsi_value=rsi_value,
                macd_histogram=macd_hist,
                volume_ratio=volume_ratio_confirm
            )
            
            if not signal_id:
                logger.error(f"[{self.symbol}] 保存交易信号失败")
                return None
            
            logger.info(
                f"[{self.symbol}] 市场检测完成: 生成{signal_type}信号, "
                f"strength={signal_strength}, confidence={confidence_score:.2f}, "
                f"triggers={trigger_factors}"
            )
            
            return {
                'signal_id': signal_id,
                'snapshot_id': snapshot_id,
                'signal_type': signal_type,
                'signal_strength': signal_strength,
                'confidence_score': confidence_score,
                'price': price,
                'trigger_factors': trigger_factors
            }
            
        except Exception as e:
            logger.error(f"[{self.symbol}] 市场检测失败: {e}", exc_info=True)
            return None

