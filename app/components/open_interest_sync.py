"""
未平仓合约数数据同步管理器
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.components.coinglass_client import CoinGlassClient
from app.database.connection import db
from app.database.open_interest import OpenInterestRepository
from app.config import settings
from app.utils.logger import logger


class OpenInterestSyncManager(threading.Thread):
    """未平仓合约数数据同步管理器（后台线程）"""
    
    def __init__(self, coinglass_client: CoinGlassClient, symbol: str):
        super().__init__(name=f"OpenInterestSyncThread-{symbol}", daemon=False)
        self.coinglass_client = coinglass_client
        self.symbol = symbol  # 币种名称：BTC, ETH等
        self.stop_event = threading.Event()
        self.db = db
        
        # 同步状态
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        """停止同步线程"""
        self.stop_event.set()
    
    def _should_sync_15m(self, now: datetime) -> bool:
        """
        判断是否应该同步15分钟数据
        
        每15分钟同步一次，在00, 15, 30, 45分时同步
        """
        minute = now.minute
        second = now.second
        
        # 在00, 15, 30, 45分的前30秒内
        if minute % 15 == 0 and second < 30:
            # 检查上次同步是否在这个时间点之前
            if self.last_sync_time is None:
                return True
            last_minute = self.last_sync_time.minute
            if last_minute != minute:
                return True
        
        return False
    
    def _fetch_and_save_open_interest(self) -> bool:
        """获取并保存未平仓合约数数据"""
        try:
            now = datetime.now(timezone.utc)
            
            # 计算15分钟前的时间作为查询范围
            end_time = int(now.timestamp() * 1000)
            start_time = int((now - timedelta(minutes=30)).timestamp() * 1000)
            
            data_list = self.coinglass_client.get_open_interest_history(
                symbol=self.symbol,
                exchange="OKX",
                start_time=start_time,
                end_time=end_time
            )
            
            if not data_list:
                logger.warning(f"获取{self.symbol}未平仓合约数据为空")
                return False
            
            # 处理并保存数据
            with self.db.get_session() as session:
                saved_count = 0
                for item in data_list:
                    time_ms = int(item.get('time', 0))
                    if time_ms == 0:
                        continue
                    
                    time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
                    
                    # 转换为数据库格式
                    db_data = {
                        'symbol': self.symbol,
                        'time': time_dt,
                        'oi_open': float(item.get('open', 0)),
                        'oi_high': float(item.get('high', 0)),
                        'oi_low': float(item.get('low', 0)),
                        'oi_close': float(item.get('close', 0)),
                    }
                    
                    if OpenInterestRepository.insert_open_interest(session, **db_data):
                        saved_count += 1
                
                if saved_count > 0:
                    self.last_sync_time = now
                    return True
                else:
                    logger.warning(f"{self.symbol} 未平仓合约数据保存失败或已存在")
                    return False
                    
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}未平仓合约数据失败: {e}")
            return False
    
    def _sync_initial_data(self):
        """同步初始历史数据（30天，4小时间隔）"""
        try:
            
            now = datetime.now(timezone.utc)
            end_time = int(now.timestamp() * 1000)
            # 查询近一个月（30天）的数据
            start_time = int((now - timedelta(days=30)).timestamp() * 1000)
            
            data_list = self.coinglass_client.get_open_interest_history(
                symbol=self.symbol,
                exchange="OKX",
                interval="4h",  # 使用4小时间隔
                start_time=start_time,
                end_time=end_time
            )
            
            if not data_list:
                logger.warning(f"获取{self.symbol}未平仓合约历史数据为空")
                return
            
            # 批量保存
            with self.db.get_session() as session:
                db_data_list = []
                for item in data_list:
                    time_ms = int(item.get('time', 0))
                    if time_ms == 0:
                        continue
                    
                    time_dt = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)
                    db_data_list.append({
                        'symbol': self.symbol,
                        'time': time_dt,
                        'oi_open': float(item.get('open', 0)),
                        'oi_high': float(item.get('high', 0)),
                        'oi_low': float(item.get('low', 0)),
                        'oi_close': float(item.get('close', 0)),
                    })
                
                saved_count = OpenInterestRepository.batch_insert_open_interest(session, db_data_list)
                
        except Exception as e:
            logger.error(f"同步{self.symbol}未平仓合约历史数据失败: {e}")
    
    def run(self):
        """主线程循环"""
        
        # 先同步初始历史数据
        self._sync_initial_data()
        
        # 主循环
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                
                # 检查是否需要同步
                if self._should_sync_15m(now):
                    self._fetch_and_save_open_interest()
                
                # 每30秒检查一次
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"{self.symbol} 未平仓合约同步线程错误: {e}")
                time.sleep(60)  # 出错后等待更长时间

