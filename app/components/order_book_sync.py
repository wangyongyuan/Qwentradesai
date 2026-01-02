"""
盘口挂单分布同步管理器
"""
import threading
import time
from datetime import datetime, timezone
from typing import Optional
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.order_book import OrderBookRepository
from app.config import settings
from app.utils.logger import logger


class OrderBookSyncManager(threading.Thread):
    """盘口挂单分布同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager, symbol: str):
        super().__init__(name=f"OrderBookSyncThread-{symbol}", daemon=False)
        self.api_manager = api_manager
        self.symbol = symbol
        self.ccxt_symbol = settings.symbol_to_ccxt_format(symbol)
        self.stop_event = threading.Event()
        self.db = db
        self.last_sync_time: Optional[datetime] = None
    
    def stop(self):
        self.stop_event.set()
    
    def _should_sync(self, now: datetime) -> bool:
        """每1小时同步一次"""
        if self.last_sync_time is None:
            return True
        time_diff = (now - self.last_sync_time).total_seconds()
        return time_diff >= 3600  # 1小时
    
    def _fetch_and_save_order_book(self) -> bool:
        """获取并保存盘口挂单分布数据"""
        try:
            # 使用OKX API /api/v5/market/books-full 获取完整订单簿
            exchange = self.api_manager.exchange
            
            # 调用OKX原始API: GET /api/v5/market/books-full
            # 将CCXT格式转换为OKX格式：BTC/USDT:USDT -> BTC-USDT-SWAP
            inst_id = self.ccxt_symbol.replace('/', '-').replace(':USDT', '-SWAP')
            
            # 参数: sz=1000 (返回1000档深度)
            params = {
                'instId': inst_id,
                'sz': '1000'  # 返回1000档深度
            }
            
            logger.debug(f"调用OKX API: /api/v5/market/books-full, 参数: {params}")
            response = exchange.public_get_market_books_full(params)
            
            if not response or response.get('code') != '0' or not response.get('data'):
                logger.warning(f"获取{self.symbol}盘口挂单数据失败: {response}")
                return False
            
            # OKX返回格式: {"code":"0","data":[{"asks":[...],"bids":[...],...}],...}
            data = response['data'][0] if response['data'] else {}
            
            if 'asks' not in data or 'bids' not in data:
                logger.warning(f"获取{self.symbol}盘口挂单数据为空")
                return False
            
            now = datetime.now(timezone.utc)
            
            # OKX books-full接口返回的格式：["价格", "数量", "订单数"] (3个字段)
            asks = data.get('asks', [])
            bids = data.get('bids', [])
            
            # 计算大单金额（档位数量超过平均值的2倍的档位，用于分析大单压力/支撑）
            large_ask_amount = None
            large_bid_amount = None
            
            if asks and len(asks) > 0:
                # 计算所有asks的平均档位数量
                total_ask_qty = sum(float(ask[1]) for ask in asks if len(ask) >= 2)
                avg_ask_qty_per_level = total_ask_qty / len(asks) if len(asks) > 0 else 0
                # 大单阈值：档位数量超过平均档位数量的2倍
                threshold = avg_ask_qty_per_level * 2.0
                if threshold > 0:
                    large_ask_amount = sum(
                        float(ask[1]) for ask in asks 
                        if len(ask) >= 2 and float(ask[1]) >= threshold
                    )
                    if large_ask_amount == 0:
                        large_ask_amount = None
            
            if bids and len(bids) > 0:
                # 计算所有bids的平均档位数量
                total_bid_qty = sum(float(bid[1]) for bid in bids if len(bid) >= 2)
                avg_bid_qty_per_level = total_bid_qty / len(bids) if len(bids) > 0 else 0
                # 大单阈值：档位数量超过平均档位数量的2倍
                threshold = avg_bid_qty_per_level * 2.0
                if threshold > 0:
                    large_bid_amount = sum(
                        float(bid[1]) for bid in bids 
                        if len(bid) >= 2 and float(bid[1]) >= threshold
                    )
                    if large_bid_amount == 0:
                        large_bid_amount = None
            
            with self.db.get_session() as session:
                if OrderBookRepository.insert_order_book(
                    session,
                    symbol=self.symbol,
                    time=now,
                    asks=asks,
                    bids=bids,
                    large_ask_amount=large_ask_amount,
                    large_bid_amount=large_bid_amount
                ):
                    self.last_sync_time = now
                    logger.info(f"{self.symbol} 盘口挂单数据保存成功")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"获取并保存{self.symbol}盘口挂单数据失败: {e}", exc_info=True)
            return False
    
    def run(self):
        
        while not self.stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self._should_sync(now):
                    self._fetch_and_save_order_book()
                time.sleep(300)  # 每5分钟检查一次
            except Exception as e:
                logger.error(f"{self.symbol} 盘口挂单同步线程错误: {e}")
                time.sleep(60)

