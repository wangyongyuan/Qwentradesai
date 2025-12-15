"""
爆仓历史数据同步管理器
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.components.coinglass_client import CoinGlassClient
from app.database.connection import db
from app.database.liquidation import LiquidationRepository
from app.config import settings
from app.utils.logger import logger


class LiquidationSyncManager(threading.Thread):
    """爆仓历史数据同步管理器（后台线程）"""
    
    def __init__(self, coinglass_client: CoinGlassClient, symbol: str):
        super().__init__(name=f"LiquidationSyncThread-{symbol}", daemon=False)
        self.coinglass_client = coinglass_client
        self.symbol = symbol
        self.stop_event = threading.Event()
        self.db = db
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """每4小时同步一次"""
        if self.last_sync_time is None:
            return True
        time_diff = (now - self.last_sync_time).total_seconds()
        return time_diff >= 4 * 3600  # 4小时
    
    def _fetch_and_save_liquidation(self) -> bool:
        """获取并保存爆仓历史数据"""
        try:
            now = datetime.now(timezone.utc)
            # 获取最近30天的数据（CoinGlass API需要毫秒级时间戳）
            end_time = int(now.timestamp() * 1000)  # 毫秒级时间戳
            start_time = int((now - timedelta(days=30)).timestamp() * 1000)
            
            data_list = self.coinglass_client.get_liquidation_history(
                symbol=self.symbol,
                exchange_list="OKX",  # 使用OKX交易所
                interval="4h",  # 4小时间隔
                limit=1000,  # 最多返回1000条
                start_time=start_time,
                end_time=end_time
            )
            
            if not data_list:
                logger.warning(f"获取{self.symbol}爆仓历史数据为空")
                return False
            
            with self.db.get_session() as session:
                saved_count = 0
                for item in data_list:
                    time_ms = int(item.get('time', 0))
                    if time_ms == 0:
                        continue
                    
                    # CoinGlass API返回的时间戳是毫秒级，需要除以1000转换为秒级
                    time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
                    
                    aggregated_long_liquidation_usd = float(item.get('aggregated_long_liquidation_usd', 0))
                    aggregated_short_liquidation_usd = float(item.get('aggregated_short_liquidation_usd', 0))
                    
                    if LiquidationRepository.insert_liquidation_data(
                        session,
                        symbol=self.symbol,
                        time=time_dt,
                        aggregated_long_liquidation_usd=aggregated_long_liquidation_usd,
                        aggregated_short_liquidation_usd=aggregated_short_liquidation_usd
                    ):
                        saved_count += 1
                
                if saved_count > 0:
                    self.last_sync_time = now
                    logger.info(f"{self.symbol} 爆仓历史数据保存成功，共{saved_count}条")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}爆仓历史数据失败: {e}", exc_info=True)
            return False
    
    def _sync_initial_data(self):
        """同步初始历史数据（30天）"""
        try:
            self._fetch_and_save_liquidation()
        except Exception as e:
            logger.error(f"同步{self.symbol}爆仓历史数据失败: {e}")
    
    def run(self):
        self._sync_initial_data()  # 初始同步30天历史数据
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_liquidation()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"{self.symbol} 爆仓历史同步线程错误: {e}")
                time.sleep(60)
