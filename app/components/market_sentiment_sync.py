"""
市场情绪数据（多空比）同步管理器
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.components.coinglass_client import CoinGlassClient
from app.database.connection import db
from app.database.market_sentiment import MarketSentimentRepository
from app.config import settings
from app.utils.logger import logger


class MarketSentimentSyncManager(threading.Thread):
    """市场情绪数据同步管理器（后台线程）"""
    
    def __init__(self, coinglass_client: CoinGlassClient, symbol: str):
        super().__init__(name=f"MarketSentimentSyncThread-{symbol}", daemon=False)
        self.coinglass_client = coinglass_client
        self.symbol = symbol
        self.stop_event = threading.Event()
        self.db = db
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """每4小时同步一次（与4h数据周期一致）"""
        if self.last_sync_time is None:
            return True
        time_diff = (now - self.last_sync_time).total_seconds()
        return time_diff >= 4 * 3600  # 4小时
    
    def _fetch_and_save_sentiment(self) -> bool:
        """获取并保存市场情绪数据（30天4h数据）"""
        try:
            now = datetime.now(timezone.utc)
            end_time = int(now.timestamp() * 1000)
            start_time = int((now - timedelta(days=30)).timestamp() * 1000)
            
            data_list = self.coinglass_client.get_long_short_ratio_history(
                symbol=self.symbol,
                exchange="Binance",
                interval="4h",
                limit=1000,
                start_time=start_time,
                end_time=end_time
            )
            
            if not data_list:
                return False
            
            with self.db.get_session() as session:
                saved_count = 0
                for item in data_list:
                    time_ms = int(item.get('time', 0))
                    if time_ms == 0:
                        continue
                    
                    time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
                    
                    if MarketSentimentRepository.insert_sentiment_data(
                        session,
                        symbol=self.symbol,
                        time=time_dt,
                        global_account_long_percent=item.get('global_account_long_percent'),
                        global_account_short_percent=item.get('global_account_short_percent'),
                        global_account_long_short_ratio=item.get('global_account_long_short_ratio')
                    ):
                        saved_count += 1
                
                if saved_count > 0:
                    self.last_sync_time = now
                    return True
                return False
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}市场情绪数据失败: {e}")
            return False
    
    def _sync_initial_data(self):
        """同步初始历史数据（30天4h）"""
        try:
            self._fetch_and_save_sentiment()
        except Exception as e:
            logger.error(f"同步{self.symbol}市场情绪历史数据失败: {e}")
    
    def run(self):
        self._sync_initial_data()  # 初始同步30天历史数据
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_sentiment()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"{self.symbol} 市场情绪同步线程错误: {e}")
                time.sleep(60)

