"""
K线数据同步管理器
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.klines import KlineRepository
from app.components.indicator_calculator import IndicatorCalculator
from app.config import settings
from app.utils.logger import logger


class KlineSyncManager(threading.Thread):
    """K线数据同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager, symbol: str, market_detector=None):
        """
        初始化K线同步管理器
        
        Args:
            api_manager: API管理器
            symbol: 币种名称（BTC, ETH等）
            market_detector: 市场检测器实例（可选）
        """
        super().__init__(name=f"KlineSyncThread-{symbol}", daemon=False)
        self.api_manager = api_manager
        self.symbol = symbol  # 币种名称：BTC, ETH等
        self.ccxt_symbol = settings.symbol_to_ccxt_format(symbol)  # 转换为CCXT格式
        self.stop_event = threading.Event()
        self.indicator_calculator = IndicatorCalculator()
        self.market_detector = market_detector  # 市场检测器（可选）
        self.db = db
        
        # 同步状态
        self.last_sync_15m: Optional[datetime] = None
        self.last_sync_4h: Optional[datetime] = None
        self.last_sync_1d: Optional[datetime] = None
    
    def stop(self):
        """停止同步线程"""
        self.stop_event.set()
    
    def _convert_ccxt_klines(self, klines: List) -> List[Dict]:
        """
        转换CCXT返回的K线数据格式
        
        CCXT格式: [timestamp, open, high, low, close, volume]
        """
        result = []
        for kline in klines:
            result.append({
                'time': kline[0],  # timestamp (ms)
                'open': float(kline[1]),
                'high': float(kline[2]),
                'low': float(kline[3]),
                'close': float(kline[4]),
                'volume': float(kline[5]),
            })
        return result
    
    def _fetch_and_save_klines(
        self,
        timeframe: str,
        limit: int = 1,
        since: Optional[int] = None
    ) -> bool:
        """
        从API获取K线并保存到数据库
        
        Args:
            timeframe: 时间周期（15m/4h/1d）
            limit: 获取数量
            since: 起始时间戳（毫秒），None表示获取最新
            
        Returns:
            是否成功
        """
        try:
            # 调用API获取K线
            klines = self.api_manager.get_klines(
                symbol=self.ccxt_symbol,
                timeframe=timeframe,
                limit=limit,
                since=since
            )
            
            if klines is None:
                logger.error(f"获取{timeframe} K线数据返回None，可能是API调用失败")
                return False
            
            if not klines:
                logger.warning(f"获取{timeframe} K线数据为空（空列表）")
                return False
            
            
            # 转换格式
            klines_data = self._convert_ccxt_klines(klines)
            
            # 保存到数据库
            session = self.db.get_session()
            try:
                inserted = KlineRepository.insert_klines(
                    session, timeframe, self.symbol, klines_data
                )
                
                # 数据已保存或已存在
                
                # 无论是否插入新数据，都更新指标（确保数据最新）
                self.indicator_calculator.update_latest_indicators(timeframe, self.symbol)
                
                return True
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"获取并保存{timeframe} K线失败: {e}", exc_info=True)
            return False
    
    def _should_sync_15m(self, now: datetime) -> bool:
        """判断是否应该同步15分钟K线（每15分钟整点：00, 15, 30, 45）"""
        minute = now.minute
        second = now.second
        
        # 在整点分钟（00, 15, 30, 45）且秒数小于10时执行
        if minute % 15 == 0 and second < 10:
            if self.last_sync_15m is None:
                return True
            # 距离上次同步超过10分钟才执行
            if (now - self.last_sync_15m).total_seconds() > 600:
                return True
        return False
    
    def _should_sync_4h(self, now: datetime) -> bool:
        """判断是否应该同步4小时K线（每4小时整点：0:00, 4:00, 8:00...）"""
        hour = now.hour
        minute = now.minute
        second = now.second
        
        # 在整点小时（0, 4, 8, 12, 16, 20）且分钟和秒数都小于10时执行
        if hour % 4 == 0 and minute < 10 and second < 10:
            if self.last_sync_4h is None:
                return True
            # 距离上次同步超过3小时才执行
            if (now - self.last_sync_4h).total_seconds() > 10800:
                return True
        return False
    
    def _should_sync_1d(self, now: datetime) -> bool:
        """判断是否应该同步日线（每天0:00）"""
        hour = now.hour
        minute = now.minute
        second = now.second
        
        # 在0点且分钟和秒数都小于10时执行
        if hour == 0 and minute < 10 and second < 10:
            if self.last_sync_1d is None:
                return True
            # 距离上次同步超过20小时才执行
            if (now - self.last_sync_1d).total_seconds() > 72000:
                return True
        return False
    
    def _get_timeframe_interval_seconds(self, timeframe: str) -> int:
        """获取时间周期的秒数"""
        mapping = {
            '15m': 15 * 60,      # 900秒
            '4h': 4 * 60 * 60,  # 14400秒
            '1d': 24 * 60 * 60, # 86400秒
        }
        return mapping.get(timeframe, 0)
    
    def _fetch_klines_batch(
        self,
        timeframe: str,
        start_time: datetime,
        end_time: datetime,
        batch_size: int = 200
    ) -> int:
        """
        批量获取K线数据（分页）
        
        Args:
            timeframe: 时间周期
            start_time: 开始时间
            end_time: 结束时间
            batch_size: 每批获取数量
            
        Returns:
            成功获取的K线数量
        """
        total_inserted = 0
        # 确保时区一致
        start_time_tz = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        end_time_tz = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
        current_time = start_time_tz
        interval_seconds = self._get_timeframe_interval_seconds(timeframe)
        
        while current_time < end_time_tz:
            try:
                # 计算本次获取的结束时间
                batch_end = min(
                    current_time + timedelta(seconds=interval_seconds * batch_size),
                    end_time_tz
                )
                
                # 转换为时间戳（毫秒）
                since_timestamp = int(current_time.timestamp() * 1000)
                
                # 计算需要获取的数量
                time_diff = (batch_end - current_time).total_seconds()
                limit = min(int(time_diff / interval_seconds) + 1, batch_size)
                
                
                # 调用API获取K线
                klines = self.api_manager.get_klines(
                    timeframe=timeframe,
                    limit=limit,
                    since=since_timestamp
                )
                
                if not klines:
                    logger.warning(f"批量获取{timeframe} K线为空: {current_time} 到 {batch_end}")
                    # 移动到下一批
                    current_time = batch_end
                    continue
                
                # 转换格式
                klines_data = self._convert_ccxt_klines(klines)
                
                # 保存到数据库
                session = self.db.get_session()
                try:
                    inserted = KlineRepository.insert_klines(
                        session, timeframe, self.symbol, klines_data
                    )
                    total_inserted += inserted
                    
                    # 数据已保存
                finally:
                    session.close()
                
                # 更新当前时间（使用最后获取的K线时间，添加UTC时区）
                if klines_data:
                    last_kline_time = datetime.fromtimestamp(klines_data[-1]['time'] / 1000, tz=timezone.utc)
                    current_time = last_kline_time + timedelta(seconds=interval_seconds)
                else:
                    current_time = batch_end
                
                # 避免请求过快
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"批量获取{timeframe} K线失败 {current_time}: {e}")
                # 跳过当前批次，继续下一批
                current_time += timedelta(seconds=interval_seconds * batch_size)
                continue
        
        return total_inserted
    
    def _detect_gaps(
        self,
        session,
        timeframe: str,
        start_time: datetime,
        end_time: datetime
    ) -> List[Tuple[datetime, datetime]]:
        """
        检测K线时间序列中的断点
        
        Returns:
            断点列表，每个断点是(start, end)时间元组
        """
        interval_seconds = self._get_timeframe_interval_seconds(timeframe)
        gaps = []
        
        # 获取时间范围内的所有K线时间
        df = KlineRepository.get_klines_dataframe(
            session, timeframe, self.symbol,
            start_time=start_time,
            end_time=end_time,
            limit=100000  # 足够大的数量
        )
        
        if df.empty:
            return [(start_time, end_time)]
        
        # 按时间排序
        times = sorted(df.index.tolist())
        
        # 检查第一个时间点（确保时区一致）
        first_time = times[0] if times[0].tzinfo else times[0].replace(tzinfo=timezone.utc)
        start_time_tz = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        if first_time > start_time_tz:
            gaps.append((start_time_tz, first_time - timedelta(seconds=interval_seconds)))
        
        # 检查中间断点（确保时区一致）
        for i in range(len(times) - 1):
            time_i = times[i] if times[i].tzinfo else times[i].replace(tzinfo=timezone.utc)
            time_next = times[i + 1] if times[i + 1].tzinfo else times[i + 1].replace(tzinfo=timezone.utc)
            expected_next = time_i + timedelta(seconds=interval_seconds)
            if time_next > expected_next:
                gaps.append((expected_next, time_next - timedelta(seconds=interval_seconds)))
        
        # 检查最后一个时间点（确保时区一致）
        last_time = times[-1] if times[-1].tzinfo else times[-1].replace(tzinfo=timezone.utc)
        end_time_tz = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
        if last_time < end_time_tz:
            gaps.append((last_time + timedelta(seconds=interval_seconds), end_time_tz))
        
        return gaps
    
    def _smart_sync_klines(self, timeframe: str, priority_days: int = None) -> bool:
        """
        智能补全K线数据
        
        Args:
            timeframe: 时间周期（15m/4h/1d）
            priority_days: 优先补全的天数（None表示全部补全）
            
        Returns:
            是否成功
        """
        session = self.db.get_session()
        try:
            # 获取配置的开始天数
            start_days_map = {
                '15m': settings.KLINE_15M_START_DAYS,
                '4h': settings.KLINE_4H_START_DAYS,
                '1d': settings.KLINE_1D_START_DAYS,
            }
            start_days = start_days_map.get(timeframe, 30)
            
            # 如果指定了优先天数，使用较小的值
            if priority_days:
                start_days = min(start_days, priority_days)
            
            # 计算开始时间（使用UTC时区）
            now = datetime.now(timezone.utc)
            start_time = now - timedelta(days=start_days)
            
            # 获取数据库最新K线时间
            latest_time = KlineRepository.get_latest_kline_time(session, timeframe, self.symbol)
            
            # 确保latest_time有时区信息（如果是naive，添加UTC时区）
            if latest_time and latest_time.tzinfo is None:
                latest_time = latest_time.replace(tzinfo=timezone.utc)
            
            if latest_time is None:
                # 数据库为空，从开始时间补全到当前
                total_inserted = self._fetch_klines_batch(timeframe, start_time, now)
                return True
            
            # 检查是否需要补全
            need_sync = False
            sync_start = None
            sync_end = None
            
            if latest_time < start_time:
                # 最新时间早于开始时间，需要补全两段
                # 第一段：从开始时间到最新时间
                sync_start = start_time
                sync_end = latest_time
                need_sync = True
                
                # 补全第一段
                inserted1 = self._fetch_klines_batch(timeframe, sync_start, sync_end)
                
                # 第二段：从最新时间到当前时间
                sync_start = latest_time + timedelta(seconds=self._get_timeframe_interval_seconds(timeframe))
                sync_end = now
            elif latest_time < now:
                # 最新时间在开始时间和当前时间之间，只补全到当前
                sync_start = latest_time + timedelta(seconds=self._get_timeframe_interval_seconds(timeframe))
                sync_end = now
                need_sync = True
            
            if need_sync and sync_start and sync_start < sync_end:
                # 补全缺失数据
                total_inserted = self._fetch_klines_batch(timeframe, sync_start, sync_end)
            
            # 检测并补全断点
            gaps = self._detect_gaps(session, timeframe, start_time, now)
            
            if gaps:
                for gap_start, gap_end in gaps:
                    if gap_start < gap_end:
                        inserted = self._fetch_klines_batch(timeframe, gap_start, gap_end)
                        # 断点已补全
            # 更新最新指标
            self.indicator_calculator.update_latest_indicators(timeframe, self.symbol)
            
            # 批量更新所有历史指标
            updated_count = self.indicator_calculator.batch_update_all_indicators(timeframe, self.symbol)
            
            return True
            
        except Exception as e:
            logger.error(f"智能补全{timeframe} K线失败: {e}", exc_info=True)
            return False
        finally:
            session.close()
    
    def _sync_initial_data(self):
        """同步初始历史数据（智能补全）"""
        
        # 按优先级补全：1d → 4h → 15m
        # 先快速补全最近数据，再补全历史数据
        
        # 1. 优先补全最近数据（快速）
        self._smart_sync_klines('1d', priority_days=90)
        self._smart_sync_klines('4h', priority_days=30)
        self._smart_sync_klines('15m', priority_days=7)
        
        # 2. 后台补全完整历史数据（异步，不阻塞）
        threading.Thread(
            target=self._sync_full_history,
            daemon=True,
            name="FullHistorySync"
        ).start()
        
    
    def _sync_full_history(self):
        """后台补全完整历史数据"""
        try:
            self._smart_sync_klines('1d')
            self._smart_sync_klines('4h')
            self._smart_sync_klines('15m')
            
            # 批量更新所有历史指标（确保所有K线都有指标）
            self.indicator_calculator.batch_update_all_indicators('1d', self.symbol)
            self.indicator_calculator.batch_update_all_indicators('4h', self.symbol)
            self.indicator_calculator.batch_update_all_indicators('15m', self.symbol)
        except Exception as e:
            logger.error(f"{self.symbol} 完整历史数据补全失败: {e}", exc_info=True)
    
    def run(self):
        """线程主循环"""
        
        # 启动时先同步初始数据
        self._sync_initial_data()
        
        # 主循环：每秒检查一次是否需要同步
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                
                # 检查15分钟K线
                if self._should_sync_15m(now):
                    if self._fetch_and_save_klines('15m', limit=1):
                        self.last_sync_15m = now
                
                # 检查4小时K线
                if self._should_sync_4h(now):
                    if self._fetch_and_save_klines('4h', limit=1):
                        self.last_sync_4h = now
                
                # 检查日线
                if self._should_sync_1d(now):
                    if self._fetch_and_save_klines('1d', limit=1):
                        self.last_sync_1d = now
                
                # 等待1秒后继续检查
                self.stop_event.wait(1)
                
            except Exception as e:
                logger.error(f"K线同步循环异常: {e}", exc_info=True)
                # 异常后等待10秒再继续
                self.stop_event.wait(10)
        

