"""
ETF资金流数据同步管理器
"""
import threading
import time
from datetime import datetime, date, timezone
from typing import Optional
from app.components.coinglass_client import CoinGlassClient
from app.database.connection import db
from app.database.etf_flow import ETFFlowRepository
from app.config import settings
from app.utils.logger import logger


class ETFFlowSyncManager(threading.Thread):
    """ETF资金流数据同步管理器（后台线程）"""
    
    def __init__(self, coinglass_client: CoinGlassClient, symbol: str):
        super().__init__(name=f"ETFFlowSyncThread-{symbol}", daemon=False)
        self.coinglass_client = coinglass_client
        self.symbol = symbol  # BTC或ETH
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
    
    def _fetch_and_save_etf_flow(self) -> bool:
        """获取并保存ETF资金流数据"""
        try:
            data_list = self.coinglass_client.get_etf_flow_history(symbol=self.symbol)
            
            if data_list is None:
                logger.warning(f"获取{self.symbol} ETF资金流数据失败：API返回None（可能是API错误或需要升级计划）")
                return False
            
            if not data_list:
                logger.warning(f"获取{self.symbol} ETF资金流数据为空：返回的列表为空")
                return False
            
            
            # 处理数据
            
            with self.db.get_session() as session:
                saved_count = 0
                skipped_count = 0
                
                for idx, item in enumerate(data_list):
                    try:
                        # 获取时间戳（毫秒）
                        timestamp = int(item.get('timestamp', 0))
                        if timestamp == 0:
                            logger.warning(f"{self.symbol} ETF数据第{idx+1}条缺少timestamp字段，跳过")
                            skipped_count += 1
                            continue
                        
                        # 从时间戳转换为日期
                        date_val = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).date()
                        
                        # 获取新接口返回的字段（不处理价格字段）
                        net_assets_usd = item.get('net_assets_usd')
                        change_usd = item.get('change_usd')
                        
                        # 验证必要字段
                        if net_assets_usd is None:
                            logger.warning(f"{self.symbol} ETF数据第{idx+1}条缺少net_assets_usd字段，跳过")
                            skipped_count += 1
                            continue
                        
                        if change_usd is None:
                            logger.warning(f"{self.symbol} ETF数据第{idx+1}条缺少change_usd字段，跳过")
                            skipped_count += 1
                            continue
                        
                        # 记录第一条数据的详细信息
                        # 处理数据
                        if ETFFlowRepository.insert_etf_flow(
                            session,
                            symbol=self.symbol,
                            date_val=date_val,
                            net_assets_usd=float(net_assets_usd),
                            change_usd=float(change_usd),
                            timestamp=timestamp
                        ):
                            saved_count += 1
                        else:
                            logger.warning(f"{self.symbol} ETF数据第{idx+1}条保存失败（日期: {date_val}）")
                            skipped_count += 1
                            
                    except Exception as e:
                        logger.error(f"{self.symbol} ETF数据第{idx+1}条处理失败: {e}", exc_info=True)
                        skipped_count += 1
                
                if saved_count > 0:
                    self.last_sync_date = datetime.now(timezone.utc).date()
                    return True
                else:
                    logger.warning(f"{self.symbol} ETF资金流数据保存失败: 所有{len(data_list)}条数据都未能保存")
                    return False
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol} ETF资金流数据失败: {e}", exc_info=True)
            return False
    
    def run(self):
        self._fetch_and_save_etf_flow()  # 初始同步
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_etf_flow()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"{self.symbol} ETF资金流同步线程错误: {e}")
                time.sleep(60)

