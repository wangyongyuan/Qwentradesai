"""
资金费率数据同步管理器
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.funding_rate import FundingRateRepository
from app.config import settings
from app.utils.logger import logger


class FundingRateSyncManager(threading.Thread):
    """资金费率数据同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager, symbol: str):
        super().__init__(name=f"FundingRateSyncThread-{symbol}", daemon=False)
        self.api_manager = api_manager
        self.symbol = symbol  # 币种名称：BTC, ETH等
        self.ccxt_symbol = settings.symbol_to_ccxt_format(symbol)  # 转换为CCXT格式
        self.stop_event = threading.Event()
        self.db = db
        
        # 同步状态
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        """停止同步线程"""
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """
        判断是否应该同步资金费率
        
        资金费率每8小时更新一次，更新时间点为：00:00, 08:00, 16:00 UTC
        """
        # 如果从未同步过，需要同步
        if self.last_sync_time is None:
            return True
        
        # 计算距离上次同步的时间
        time_diff = (now - self.last_sync_time).total_seconds()
        
        # 最小间隔：至少间隔1小时才检查一次，避免频繁重复检查
        if time_diff < 3600:
            return False
        
        # 如果距离上次同步超过7.5小时，需要同步（提前一点，避免错过）
        if time_diff >= 7.5 * 3600:
            return True
        
        # 检查是否在资金费率更新时间点（00:00, 08:00, 16:00 UTC）
        hour = now.hour
        minute = now.minute
        
        # 在更新时间点前后5分钟内
        if hour in [0, 8, 16] and minute < 5:
            # 检查上次同步是否在这个时间点之前
            last_hour = self.last_sync_time.hour
            if last_hour != hour:
                return True
        
        return False
    
    def _fetch_and_save_funding_rate(self) -> bool:
        """获取并保存资金费率"""
        try:
            # 调用API获取资金费率
            funding_data = self.api_manager.get_funding_rate(self.ccxt_symbol)
            
            if not funding_data:
                logger.warning(f"获取{self.symbol}资金费率数据为空")
                return False
            
            # 解析数据
            if isinstance(funding_data, dict):
                funding_rate = float(funding_data.get('fundingRate', 0))
                next_funding_time = funding_data.get('nextFundingTime', 0)
                
                # 将时间戳转换为datetime（毫秒转秒）
                if next_funding_time:
                    funding_time = datetime.fromtimestamp(next_funding_time / 1000, tz=timezone.utc)
                else:
                    # 如果没有下次时间，使用当前时间（向上取整到8小时）
                    now = datetime.now(timezone.utc)
                    hour = (now.hour // 8) * 8
                    funding_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            else:
                logger.warning(f"{self.symbol} 资金费率数据格式异常: {funding_data}")
                return False
            
            # 保存到数据库
            session = self.db.get_session()
            try:
                success = FundingRateRepository.insert_funding_rate(
                    session, self.symbol, funding_time, funding_rate
                )
                
                # 数据已保存
                
                return success
                
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}资金费率失败: {e}", exc_info=True)
            return False
    
    def _sync_initial_data(self):
        """同步初始历史数据"""
        
        session = self.db.get_session()
        try:
            # 计算开始时间
            now = datetime.now(timezone.utc)
            start_days = settings.FUNDING_RATE_START_DAYS
            start_time = now - timedelta(days=start_days)
            
            # 获取数据库最新资金费率时间
            latest_time = FundingRateRepository.get_latest_funding_rate_time(session, self.symbol)
            
            # 确保latest_time有时区信息
            if latest_time and latest_time.tzinfo is None:
                latest_time = latest_time.replace(tzinfo=timezone.utc)
            
            # 计算需要同步的时间范围
            if latest_time is None:
                # 数据库为空，从开始时间补全到当前
                sync_start = start_time
                sync_end = now
            else:
                # 从最新时间到当前时间
                sync_start = latest_time + timedelta(hours=8)  # 资金费率每8小时一次
                sync_end = now
            
            # 批量获取历史数据
            if sync_start < sync_end:
                funding_history = self.api_manager.get_funding_rate_history(
                    self.ccxt_symbol, limit=100
                )
                
                if funding_history:
                    inserted_count = 0
                    for item in funding_history:
                        try:
                            # OKX API返回格式：{'fundingTime': '1234567890000', 'fundingRate': '0.0001', ...}
                            # 解析时间戳（毫秒）
                            funding_time_str = item.get('fundingTime') or item.get('ts', '0')
                            if isinstance(funding_time_str, str):
                                funding_time = datetime.fromtimestamp(
                                    int(funding_time_str) / 1000, 
                                    tz=timezone.utc
                                )
                            else:
                                funding_time = datetime.fromtimestamp(
                                    int(funding_time_str) / 1000, 
                                    tz=timezone.utc
                                )
                            
                            # 只保存时间范围内的数据
                            if sync_start <= funding_time <= sync_end:
                                funding_rate = float(item.get('fundingRate', 0))
                                open_interest_str = item.get('openInterest') or item.get('oi')
                                open_interest = float(open_interest_str) if open_interest_str else None
                                
                                success = FundingRateRepository.insert_funding_rate(
                                    session, self.symbol, funding_time, funding_rate, open_interest
                                )
                                if success:
                                    inserted_count += 1
                        except Exception as e:
                            logger.warning(f"解析资金费率历史数据失败: {item}, 错误: {e}")
                            continue
                    
                else:
                    logger.warning(f"{self.symbol} 资金费率历史数据为空")
            
        except Exception as e:
            logger.error(f"{self.symbol} 同步资金费率历史数据失败: {e}", exc_info=True)
        finally:
            session.close()
    
    def run(self):
        """线程主循环"""
        
        # 启动时先同步初始数据
        self._sync_initial_data()
        
        # 主循环：每分钟检查一次是否需要同步
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                
                # 检查是否需要同步
                if self._should_sync(now):
                    self._fetch_and_save_funding_rate()
                    # 无论是否成功插入，都更新同步时间，避免重复检查
                    self.last_sync_time = now
                
                # 等待1分钟后继续检查
                self.stop_event.wait(60)
                
            except Exception as e:
                logger.error(f"{self.symbol} 资金费率同步循环异常: {e}", exc_info=True)
                self.stop_event.wait(300)  # 出错时等待5分钟
        

