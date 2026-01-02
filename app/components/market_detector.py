"""
市场检测器 - 层级过滤模型
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Any, Tuple
import statistics
from app.database.connection import db
from app.database.klines import KlineRepository
from app.database.market_detection import MarketDetectionRepository
from app.config import settings
from app.utils.logger import logger


class MarketDetector:
    """市场检测器 - 层级过滤模型"""
    
    def __init__(self, symbol: str):
        """
        初始化市场检测器
        
        Args:
            symbol: 币种名称（BTC, ETH等）
        """
        self.symbol = symbol
        self.db = db
    
    def _get_klines(self, timeframe: str, count: int) -> List[Dict[str, Any]]:
        """获取K线数据（包含指标）"""
        session = self.db.get_session()
        try:
            klines = KlineRepository.get_klines_with_indicators(
                session, timeframe, self.symbol, limit=count
            )
            return klines
        except Exception as e:
            logger.error(f"获取{timeframe} K线数据失败: {e}", exc_info=True)
            return []
        finally:
            session.close()
    
    def _filter_layer(
        self,
        klines_15m: List[Dict],
        klines_4h: List[Dict]
    ) -> Tuple[Optional[str], bool, Optional[bool], Optional[bool], bool]:
        """
        环境层过滤
        
        Returns:
            (market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned)
            market_mode: BULL/BEAR/NEUTRAL
            market_active: 市场是否活跃
            trend_15m: 15m趋势方向（True=上涨，False=下跌）
            trend_4h: 4h趋势方向
            multi_tf_aligned: 多时间框架是否对齐
        """
        if not klines_15m or not klines_4h:
            return None, False, None, None, False
        
        # 获取最新K线
        latest_15m = klines_15m[-1]
        latest_4h = klines_4h[-1]
        
        # 判断趋势方向（价格是否在EMA55之上）
        price_15m = latest_15m['close']
        price_4h = latest_4h['close']
        
        # 15m趋势判断
        trend_15m = None
        if latest_15m.get('ema_55'):
            trend_15m = price_15m > latest_15m['ema_55']
        
        # 4h趋势判断（使用EMA21）
        trend_4h = None
        if latest_4h.get('ema_21'):
            trend_4h = price_4h > latest_4h['ema_21']
        
        # 判断市场模式
        if trend_15m is True:
            market_mode = 'BULL'
        elif trend_15m is False:
            market_mode = 'BEAR'
        else:
            market_mode = 'NEUTRAL'
        
        # 判断市场活性（布林带宽度）
        market_active = False
        if len(klines_15m) >= 20:
            # 计算最近20根K线的布林带宽度平均值
            bb_widths = [
                k.get('bb_width', 0) or 0
                for k in klines_15m[-20:]
                if k.get('bb_width') is not None
            ]
            if bb_widths:
                avg_bb_width = statistics.mean(bb_widths)
                current_bb_width = latest_15m.get('bb_width', 0) or 0
                threshold = settings.DETECTOR_BB_WIDTH_THRESHOLD
                # 当前宽度 >= 平均值 × 阈值，认为市场活跃
                market_active = current_bb_width >= (avg_bb_width * threshold)
        
        # 多时间框架对齐（15m和4h趋势一致）
        multi_tf_aligned = False
        if trend_15m is not None and trend_4h is not None:
            multi_tf_aligned = (trend_15m == trend_4h)
        
        return market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned
    
    def _check_momentum_turn(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> Tuple[bool, Optional[float]]:
        """检查MACD动量转折"""
        if len(klines_15m) < 2:
            return False, None
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        hist_latest = latest.get('histogram')
        hist_prev = prev.get('histogram')
        
        if hist_latest is None or hist_prev is None:
            return False, None
        
        # 多头模式：MACD柱从负转正或持续增大
        if market_mode == 'BULL':
            if hist_prev <= 0 and hist_latest > 0:
                return True, hist_latest
            if hist_prev > 0 and hist_latest > hist_prev:
                return True, hist_latest
        
        # 空头模式：MACD柱从正转负或持续减小
        elif market_mode == 'BEAR':
            if hist_prev >= 0 and hist_latest < 0:
                return True, hist_latest
            if hist_prev < 0 and hist_latest < hist_prev:
                return True, hist_latest
        
        return False, hist_latest
    
    def _check_ema_cross(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> bool:
        """检查EMA交叉"""
        if len(klines_15m) < 2:
            return False
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        ema9_latest = latest.get('ema_9')
        ema21_latest = latest.get('ema_21')
        ema9_prev = prev.get('ema_9')
        ema21_prev = prev.get('ema_21')
        
        if None in [ema9_latest, ema21_latest, ema9_prev, ema21_prev]:
            return False
        
        # 多头模式：EMA9上穿EMA21
        if market_mode == 'BULL':
            return ema9_prev <= ema21_prev and ema9_latest > ema21_latest
        
        # 空头模式：EMA9下穿EMA21
        elif market_mode == 'BEAR':
            return ema9_prev >= ema21_prev and ema9_latest < ema21_latest
        
        return False
    
    def _check_rsi_extreme(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> Tuple[bool, Optional[float], float]:
        """
        检查RSI极值
        
        Returns:
            (triggered, rsi_value, position_multiplier)
        """
        if not klines_15m:
            return False, None, 1.0
        
        latest = klines_15m[-1]
        rsi = latest.get('rsi_7')
        
        if rsi is None:
            return False, None, 1.0
        
        position_multiplier = 1.0
        
        # 多头模式：RSI超卖反弹
        if market_mode == 'BULL':
            rsi_long_threshold = settings.DETECTOR_RSI_LONG_THRESHOLD
            rsi_double = settings.DETECTOR_RSI_DOUBLE_POSITION_LONG
            
            if rsi < rsi_long_threshold:
                if rsi < rsi_double:
                    position_multiplier = 2.0
                return True, rsi, position_multiplier
        
        # 空头模式：RSI超买回调
        elif market_mode == 'BEAR':
            rsi_short_threshold = settings.DETECTOR_RSI_SHORT_THRESHOLD
            rsi_double = settings.DETECTOR_RSI_DOUBLE_POSITION_SHORT
            
            if rsi > rsi_short_threshold:
                if rsi > rsi_double:
                    position_multiplier = 2.0
                return True, rsi, position_multiplier
        
        return False, rsi, 1.0
    
    def _check_bb_breakout(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> bool:
        """检查布林带突破"""
        if not klines_15m:
            return False
        
        latest = klines_15m[-1]
        close = latest['close']
        bb_upper = latest.get('bb_upper')
        bb_lower = latest.get('bb_lower')
        
        if bb_upper is None or bb_lower is None:
            return False
        
        # 多头模式：价格突破上轨
        if market_mode == 'BULL':
            return close > bb_upper
        
        # 空头模式：价格跌破下轨
        elif market_mode == 'BEAR':
            return close < bb_lower
        
        return False
    
    def _check_volume_surge(
        self,
        klines_15m: List[Dict]
    ) -> Tuple[bool, Optional[float]]:
        """
        检查成交量异常
        
        Returns:
            (triggered, volume_ratio)
        """
        if len(klines_15m) < 20:
            return False, None
        
        latest = klines_15m[-1]
        current_volume = latest['volume']
        
        # 计算最近20根K线的平均成交量和标准差
        volumes = [k['volume'] for k in klines_15m[-20:]]
        avg_volume = statistics.mean(volumes)
        
        if avg_volume == 0:
            return False, None
        
        # 计算标准差（至少需要2个数据点）
        try:
            if len(volumes) < 2:
                std_volume = 0
            else:
                std_volume = statistics.stdev(volumes)
        except (statistics.StatisticsError, ValueError):
            std_volume = 0
        
        # 动态阈值
        threshold = avg_volume + (settings.DETECTOR_VOLUME_STD_MULTIPLIER * std_volume)
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        return current_volume > threshold, volume_ratio
    
    def _check_price_pattern(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> bool:
        """检查价格形态（吞没形态）"""
        if len(klines_15m) < 2:
            return False
        
        latest = klines_15m[-1]
        prev = klines_15m[-2]
        
        # 多头模式：看涨吞没（前一根是阴线，当前是阳线，且当前完全吞没前一根）
        if market_mode == 'BULL':
            prev_bearish = prev['close'] < prev['open']
            latest_bullish = latest['close'] > latest['open']
            engulfed = latest['open'] < prev['close'] and latest['close'] > prev['open']
            return prev_bearish and latest_bullish and engulfed
        
        # 空头模式：看跌吞没（前一根是阳线，当前是阴线，且当前完全吞没前一根）
        elif market_mode == 'BEAR':
            prev_bullish = prev['close'] > prev['open']
            latest_bearish = latest['close'] < latest['open']
            engulfed = latest['open'] > prev['close'] and latest['close'] < prev['open']
            return prev_bullish and latest_bearish and engulfed
        
        return False
    
    def _confirmation_layer(
        self,
        klines_15m: List[Dict],
        market_mode: str
    ) -> Tuple[bool, bool, Optional[float], Optional[float]]:
        """
        确认层验证
        
        Returns:
            (volume_confirm, bb_confirm, volume_ratio, bb_width_ratio)
        """
        if not klines_15m:
            return False, False, None, None
        
        latest = klines_15m[-1]
        
        # 成交量确认
        volume_confirm, volume_ratio = self._check_volume_surge(klines_15m)
        
        # 布林带确认
        bb_confirm = False
        bb_width_ratio = None
        
        if len(klines_15m) >= 20:
            current_bb_width = latest.get('bb_width', 0) or 0
            bb_widths = [
                k.get('bb_width', 0) or 0
                for k in klines_15m[-20:]
                if k.get('bb_width') is not None
            ]
            if bb_widths and current_bb_width > 0:
                avg_bb_width = statistics.mean(bb_widths)
                if avg_bb_width > 0:
                    bb_width_ratio = current_bb_width / avg_bb_width
                    # 布林带宽度扩大（突破确认）
                    bb_confirm = bb_width_ratio > 1.2
        
        return volume_confirm, bb_confirm, volume_ratio, bb_width_ratio
    
    def _calculate_signal_strength(
        self,
        trigger_count: int,
        multi_tf_aligned: bool,
        volume_confirm: bool,
        bb_confirm: bool
    ) -> str:
        """计算信号强度"""
        score = trigger_count
        
        if multi_tf_aligned:
            score += 0.5
        
        if volume_confirm:
            score += 1
        
        if bb_confirm:
            score += 1
        
        if score >= 4:
            return 'VERY_STRONG'
        elif score >= 3:
            return 'STRONG'
        elif score >= 2:
            return 'MODERATE'
        else:
            return 'WEAK'
    
    def detect(self) -> Optional[Dict[str, Any]]:
        """
        执行市场检测
        
        Returns:
            检测结果字典，包含信号信息（如果有信号）
        """
        try:
            # 获取K线数据
            count_15m = settings.DETECTOR_KLINE_15M_COUNT
            count_4h = settings.DETECTOR_KLINE_4H_COUNT
            
            klines_15m = self._get_klines('15m', count_15m)
            klines_4h = self._get_klines('4h', count_4h)
            klines_1d = self._get_klines('1d', 40) if settings.DETECTOR_ENABLE_MULTI_TF else []
            
            if not klines_15m or not klines_4h:
                logger.warning(f"{self.symbol} K线数据不足，跳过检测")
                return None
            
            # 获取最新价格
            latest_15m = klines_15m[-1]
            price = latest_15m['close']
            detected_at = datetime.now(timezone.utc)
            
            # 环境层过滤
            market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned = self._filter_layer(
                klines_15m, klines_4h
            )
            
            # NEUTRAL模式不交易
            if market_mode == 'NEUTRAL':
                logger.debug(f"{self.symbol} 市场模式为NEUTRAL，跳过检测")
                # 仍然保存快照
                self._save_snapshot(
                    detected_at, price, None,
                    latest_15m['time'], klines_4h[-1]['time'],
                    klines_1d[-1]['time'] if klines_1d else None,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    False, False, False, False, False, False,
                    None, None, None, None,
                    False, False,
                    False, None, None, 1.0,
                    len(klines_15m), len(klines_4h), len(klines_1d) if klines_1d else None
                )
                return None
            
            # 市场不活跃时不交易
            if not market_active:
                logger.debug(f"{self.symbol} 市场不活跃，跳过检测")
                # 仍然保存快照
                self._save_snapshot(
                    detected_at, price, None,
                    latest_15m['time'], klines_4h[-1]['time'],
                    klines_1d[-1]['time'] if klines_1d else None,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    False, False, False, False, False, False,
                    None, None, None, None,
                    False, False,
                    False, None, None, 1.0,
                    len(klines_15m), len(klines_4h), len(klines_1d) if klines_1d else None
                )
                return None
            
            # 触发层检测（6个维度）
            momentum_turn, macd_histogram = self._check_momentum_turn(klines_15m, market_mode)
            ema_cross = self._check_ema_cross(klines_15m, market_mode)
            rsi_extreme, rsi_value, rsi_multiplier = self._check_rsi_extreme(klines_15m, market_mode)
            bb_breakout = self._check_bb_breakout(klines_15m, market_mode)
            volume_surge, volume_ratio = self._check_volume_surge(klines_15m)
            price_pattern = self._check_price_pattern(klines_15m, market_mode)
            
            # 任一触发即可
            has_trigger = momentum_turn or ema_cross or rsi_extreme or bb_breakout or volume_surge or price_pattern
            
            if not has_trigger:
                logger.debug(f"{self.symbol} 无触发信号")
                # 保存快照
                self._save_snapshot(
                    detected_at, price, None,
                    latest_15m['time'], klines_4h[-1]['time'],
                    klines_1d[-1]['time'] if klines_1d else None,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                    rsi_value, macd_histogram, volume_ratio, None,
                    False, False,
                    False, None, None, rsi_multiplier,
                    len(klines_15m), len(klines_4h), len(klines_1d) if klines_1d else None
                )
                return None
            
            # 确认层验证
            volume_confirm, bb_confirm, confirm_volume_ratio, bb_width_ratio = self._confirmation_layer(
                klines_15m, market_mode
            )
            
            # 需要至少一个确认
            if not volume_confirm and not bb_confirm:
                logger.debug(f"{self.symbol} 确认层未通过")
                # 保存快照
                self._save_snapshot(
                    detected_at, price, None,
                    latest_15m['time'], klines_4h[-1]['time'],
                    klines_1d[-1]['time'] if klines_1d else None,
                    market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                    momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                    rsi_value, macd_histogram, volume_ratio, bb_width_ratio,
                    volume_confirm, bb_confirm,
                    False, None, None, rsi_multiplier,
                    len(klines_15m), len(klines_4h), len(klines_1d) if klines_1d else None
                )
                return None
            
            # 生成信号
            signal_direction = 'LONG' if market_mode == 'BULL' else 'SHORT'
            
            # 计算信号强度
            trigger_factors = []
            if momentum_turn:
                trigger_factors.append('momentum_turn')
            if ema_cross:
                trigger_factors.append('ema_cross')
            if rsi_extreme:
                trigger_factors.append('rsi_extreme')
            if bb_breakout:
                trigger_factors.append('bb_breakout')
            if volume_surge:
                trigger_factors.append('volume_surge')
            if price_pattern:
                trigger_factors.append('price_pattern')
            
            trigger_count = len(trigger_factors)
            signal_strength = self._calculate_signal_strength(
                trigger_count, multi_tf_aligned, volume_confirm, bb_confirm
            )
            
            # 计算置信度分数（0-100）
            confidence_score = min(100, (trigger_count * 15) + (10 if multi_tf_aligned else 0) + 
                                  (15 if volume_confirm else 0) + (15 if bb_confirm else 0))
            
            # 保存快照
            snapshot_id = self._save_snapshot(
                detected_at, price, None,
                latest_15m['time'], klines_4h[-1]['time'],
                klines_1d[-1]['time'] if klines_1d else None,
                market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                rsi_value, macd_histogram, confirm_volume_ratio, bb_width_ratio,
                volume_confirm, bb_confirm,
                True, signal_direction, signal_strength, rsi_multiplier,
                len(klines_15m), len(klines_4h), len(klines_1d) if klines_1d else None
            )
            
            if not snapshot_id:
                logger.error(f"{self.symbol} 保存检测快照失败")
                return None
            
            # 保存信号
            expired_at = detected_at + timedelta(hours=settings.DETECTOR_SIGNAL_EXPIRE_HOURS)
            signal_id = self._save_signal(
                snapshot_id, signal_direction, detected_at, price,
                confidence_score, signal_strength, rsi_multiplier,
                latest_15m['time'], klines_4h[-1]['time'],
                trigger_factors, market_mode, multi_tf_aligned,
                rsi_value, macd_histogram, confirm_volume_ratio, expired_at
            )
            
            if signal_id:
                logger.info(
                    f"{self.symbol} 检测到{signal_direction}信号 "
                    f"(强度: {signal_strength}, 置信度: {confidence_score:.1f}, "
                    f"触发因素: {', '.join(trigger_factors)})"
                )
            
            return {
                'signal_id': signal_id,
                'signal_type': signal_direction,
                'signal_strength': signal_strength,
                'confidence_score': confidence_score,
                'trigger_factors': trigger_factors,
                'price': price,
                'detected_at': detected_at
            }
            
        except Exception as e:
            logger.error(f"{self.symbol} 市场检测异常: {e}", exc_info=True)
            return None
    
    def _save_snapshot(
        self,
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
        kline_1d_count: Optional[int]
    ) -> Optional[int]:
        """保存检测快照"""
        session = self.db.get_session()
        try:
            snapshot_id = MarketDetectionRepository.insert_snapshot(
                session, self.symbol, detected_at, price, price_change_24h,
                kline_15m_time, kline_4h_time, kline_1d_time,
                market_mode, market_active, trend_15m, trend_4h, multi_tf_aligned,
                momentum_turn, ema_cross, rsi_extreme, bb_breakout, volume_surge, price_pattern,
                rsi_value, macd_histogram, volume_ratio, bb_width_ratio,
                volume_confirm, bb_confirm,
                has_signal, signal_direction, signal_strength, position_size_multiplier,
                kline_15m_count, kline_4h_count, kline_1d_count
            )
            return snapshot_id
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
        market_mode: Optional[str],
        multi_tf_aligned: bool,
        rsi_value: Optional[float],
        macd_histogram: Optional[float],
        volume_ratio: Optional[float],
        expired_at: datetime
    ) -> Optional[int]:
        """保存市场信号"""
        session = self.db.get_session()
        try:
            signal_id = MarketDetectionRepository.insert_signal(
                session, snapshot_id, self.symbol, signal_type, detected_at, price,
                confidence_score, signal_strength, position_size_multiplier,
                kline_15m_time, kline_4h_time, trigger_factors,
                market_mode, multi_tf_aligned,
                rsi_value, macd_histogram, volume_ratio, expired_at
            )
            return signal_id
        finally:
            session.close()

