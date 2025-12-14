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
from app.utils.logger import logger


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
                logger.warning("获取恐惧贪婪指数数据失败：API返回None（可能是API错误或需要升级计划）")
                return False
            
            # 检查返回数据的类型
            if not isinstance(data, dict):
                logger.error(f"恐惧贪婪指数API返回数据类型错误：期望dict，实际{type(data)}，数据前100字符: {str(data)[:100]}")
                return False
            
            # 记录返回数据的结构
            
            # 根据实际API返回数据，直接获取字段：data_list, price_list, time_list
            data_list = data.get('data_list')
            price_list = data.get('price_list')
            time_list = data.get('time_list')
            
            # 详细记录每个字段的状态
            
            # 检查字段是否存在
            if data_list is None:
                logger.error(f"恐惧贪婪指数数据格式不正确 - 缺少data_list字段。可用字段: {list(data.keys())}")
                logger.error(f"完整API返回数据: {data}")
                return False
            
            if price_list is None:
                logger.error(f"恐惧贪婪指数数据格式不正确 - 缺少price_list字段。可用字段: {list(data.keys())}")
                logger.error(f"完整API返回数据: {data}")
                return False
            
            if time_list is None:
                logger.error(f"恐惧贪婪指数数据格式不正确 - 缺少time_list字段。可用字段: {list(data.keys())}")
                logger.error(f"完整API返回数据: {data}")
                return False
            
            # 检查字段类型
            if not isinstance(data_list, list):
                logger.error(f"恐惧贪婪指数数据格式不正确 - data_list不是列表类型: {type(data_list)}")
                logger.error(f"data_list值（前100字符）: {str(data_list)[:100]}")
                return False
            
            if not isinstance(price_list, list):
                logger.error(f"恐惧贪婪指数数据格式不正确 - price_list不是列表类型: {type(price_list)}")
                logger.error(f"price_list值（前100字符）: {str(price_list)[:100]}")
                return False
            
            if not isinstance(time_list, list):
                logger.error(f"恐惧贪婪指数数据格式不正确 - time_list不是列表类型: {type(time_list)}")
                logger.error(f"time_list值（前100字符）: {str(time_list)[:100]}")
                return False
            
            # 检查长度
            if len(data_list) == 0:
                logger.warning(f"恐惧贪婪指数数据格式不正确 - data_list长度为0")
                return False
            
            if len(price_list) == 0:
                logger.warning(f"恐惧贪婪指数数据格式不正确 - price_list长度为0")
                return False
            
            if len(time_list) == 0:
                logger.warning(f"恐惧贪婪指数数据格式不正确 - time_list长度为0")
                return False
            
            # 记录第一条数据的示例
            
            # 确保三个数组长度一致
            min_len = min(len(data_list), len(price_list), len(time_list))
            if min_len == 0:
                logger.warning("恐惧贪婪指数数据格式不正确：三个数组长度都为0")
                return False
            
            
            with self.db.get_session() as session:
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
                        
                        if FearGreedRepository.insert_fear_greed(
                            session,
                            date_val=date_val,
                            value=value,
                            price=price
                        ):
                            saved_count += 1
                        else:
                            logger.warning(f"恐惧贪婪指数数据第{i+1}条保存失败（日期: {date_val}）")
                            skipped_count += 1
                            
                    except (ValueError, TypeError, IndexError) as e:
                        logger.error(f"恐惧贪婪指数数据第{i+1}条处理失败: {e}, data_list[{i}]={data_list[i] if i < len(data_list) else 'N/A'}, "
                                   f"price_list[{i}]={price_list[i] if i < len(price_list) else 'N/A'}, "
                                   f"time_list[{i}]={time_list[i] if i < len(time_list) else 'N/A'}")
                        skipped_count += 1
                
                if saved_count > 0:
                    self.last_sync_date = datetime.now(timezone.utc).date()
                    return True
                else:
                    logger.warning(f"恐惧贪婪指数数据保存失败: 所有{min_len}条数据都未能保存")
                    return False
                
        except Exception as e:
            logger.error(f"获取并保存恐惧贪婪指数数据失败: {e}", exc_info=True)
            return False
    
    def run(self):
        self._fetch_and_save_fear_greed()  # 初始同步
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_fear_greed()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"恐惧贪婪指数同步线程错误: {e}")
                time.sleep(60)

