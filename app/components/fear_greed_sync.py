"""
恐惧贪婪指数数据同步管理器
"""
import threading
import time
from datetime import datetime, date, timezone
from typing import Optional
from app.components.coinglass_client import CoinGlassClient
from app.database.connection import db
from app.database.fear_greed import FearGreedRepository
from app.config import settings


class FearGreedSyncManager(threading.Thread):
    """恐惧贪婪指数数据同步管理器（后台线程）"""
    
    def __init__(self, coinglass_client: CoinGlassClient):
        super().__init__(name="FearGreedSyncThread", daemon=False)
        self.coinglass_client = coinglass_client
        self.stop_event = threading.Event()
        self.db = db
        self.last_sync_date: Optional[date] = None
    
    def stop(self):
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """每天早上8点同步"""
        hour = now.hour
        minute = now.minute
        return hour == 8 and minute < 5
    
    def _fetch_and_save_fear_greed(self) -> bool:
        """获取并保存恐惧贪婪指数数据"""
        try:
            data = self.coinglass_client.get_fear_greed_history()
            
            if data is None:
                return False
            
            # 检查返回数据的类型
            if not isinstance(data, dict):
                return False
            
            # 记录返回数据的结构
            
            # 根据实际API返回数据，直接获取字段：data_list, price_list, time_list
            data_list = data.get('data_list')
            price_list = data.get('price_list')
            time_list = data.get('time_list')
            
            # 详细记录每个字段的状态
            
            # 检查字段是否存在
            if data_list is None or price_list is None or time_list is None:
                return False
            
            # 检查字段类型
            if not isinstance(data_list, list) or not isinstance(price_list, list) or not isinstance(time_list, list):
                return False
            
            # 检查长度
            if len(data_list) == 0 or len(price_list) == 0 or len(time_list) == 0:
                return False
            
            # 确保三个数组长度一致
            min_len = min(len(data_list), len(price_list), len(time_list))
            if min_len == 0:
                return False
            
            
            # 每条记录使用独立事务，减少死锁风险
            saved_count = 0
            skipped_count = 0
            
            for i in range(min_len):
                try:
                    time_ms = int(time_list[i])
                    if time_ms == 0:
                        skipped_count += 1
                        continue
                    
                    date_val = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc).date()
                    value = int(data_list[i])
                    price = float(price_list[i])
                    
                    # 每条记录使用独立的事务
                    with self.db.get_session() as session:
                        if FearGreedRepository.insert_fear_greed(
                            session,
                            date_val=date_val,
                            value=value,
                            price=price
                        ):
                            saved_count += 1
                        else:
                            skipped_count += 1
                            
                except (ValueError, TypeError, IndexError):
                    skipped_count += 1
                except Exception as e:
                    logger.warning(f"插入恐惧贪婪指数数据失败: date={date_val if 'date_val' in locals() else 'N/A'}, {e}")
                    skipped_count += 1
            
            if saved_count > 0:
                self.last_sync_date = datetime.now(timezone.utc).date()
                return True
            else:
                return False
                
        except Exception:
            return False
    
    def run(self):
        self._fetch_and_save_fear_greed()  # 初始同步
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_fear_greed()
                time.sleep(300)  # 每5分钟检查一次
            except Exception:
                time.sleep(60)

