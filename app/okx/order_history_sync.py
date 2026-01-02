"""
OKX历史订单同步管理器
"""
import threading
import time
import requests
import hmac
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.order_history import OrderHistoryRepository
from app.config import settings
from app.utils.logger import logger


class OrderHistorySyncManager(threading.Thread):
    """OKX历史订单同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager):
        super().__init__(name="OrderHistorySyncThread", daemon=False)
        self.api_manager = api_manager
        self.stop_event = threading.Event()
        self.db = db
        
        # 同步状态
        self.last_sync_time: Optional[datetime] = None
        self.sync_symbols: List[str] = []  # 要同步的币种列表
        self.is_syncing = False  # 是否正在同步（防止并发执行）
        self.sync_lock = threading.Lock()  # 同步锁
        
        # 同步间隔（秒）- 订单数据仅通过API拉取，每10秒执行一次
        self.sync_interval = 10  # 10秒
        
        # 初始化同步币种列表
        self._init_sync_symbols()
    
    def _init_sync_symbols(self):
        """初始化同步币种列表"""
        try:
            symbols_str = settings._get('OKX_ORDER_HISTORY_SYMBOLS', 'BTC,ETH', 'string')
            self.sync_symbols = [s.strip().upper() for s in symbols_str.split(',') if s.strip()]
        except Exception as e:
            logger.warning(f"读取OKX_ORDER_HISTORY_SYMBOLS配置失败，使用默认值: {e}")
            self.sync_symbols = ['BTC', 'ETH']
    
    def _get_start_time_ms(self) -> int:
        """获取同步开始时间（毫秒时间戳）"""
        try:
            start_time_str = settings._get('OKX_ORDER_HISTORY_START_TIME', '', 'string')
            if start_time_str and start_time_str.strip():
                return int(start_time_str.strip())
            else:
                # 如果未配置，默认从当前时间往前推30天
                now = datetime.now(timezone.utc)
                start_time = now - timedelta(days=30)
                return int(start_time.timestamp() * 1000)
        except Exception as e:
            logger.warning(f"读取OKX_ORDER_HISTORY_START_TIME配置失败，使用默认值（30天前）: {e}")
            now = datetime.now(timezone.utc)
            start_time = now - timedelta(days=30)
            return int(start_time.timestamp() * 1000)
    
    def stop(self):
        """停止同步线程"""
        self.stop_event.set()
    
    def _symbol_to_inst_id(self, symbol: str) -> str:
        """将币种转换为OKX instId格式（永续合约）"""
        return f"{symbol}-USDT-SWAP"
    
    def _build_okx_signature(
        self,
        timestamp: str,
        method: str,
        request_path: str,
        body: str = ''
    ) -> str:
        """
        构建OKX API签名
        
        Args:
            timestamp: ISO 8601格式的时间戳（如：2020-12-08T09:08:57.715Z）
            method: HTTP方法（GET/POST）
            request_path: 请求路径，GET请求包含查询参数（如 /api/v5/trade/orders-history-archive?instType=SWAP&instId=ETH-USDT-SWAP）
            body: 请求体（GET请求为空字符串，POST请求为JSON字符串）
            
        Returns:
            签名字符串（Base64编码）
        """
        message = timestamp + method + request_path + body
        secret = settings.EXCHANGE_SECRET
        if not secret:
            raise ValueError("EXCHANGE_SECRET未配置")
        
        signature = base64.b64encode(
            hmac.new(
                secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return signature
    
    def _fetch_orders_history(
        self,
        inst_id: str,
        after: Optional[str] = None,
        limit: int = 100,
        begin: Optional[int] = None,
        end: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        调用OKX原始API获取历史订单
        
        Args:
            inst_id: 产品ID（如BTC-USDT-SWAP）
            after: 分页参数，请求此ID之前（更旧的数据）的分页内容
            limit: 返回结果的数量，最大100
            begin: 开始时间（Unix时间戳，毫秒），可选
            end: 结束时间（Unix时间戳，毫秒），可选
            
        Returns:
            订单列表
        """
        try:
            # 检查API密钥配置
            api_key = settings.EXCHANGE_API_KEY
            secret = settings.EXCHANGE_SECRET
            passphrase = settings.EXCHANGE_PASSPHRASE
            
            if not all([api_key, secret, passphrase]):
                logger.warning("OKX API密钥未配置，无法获取历史订单")
                return []
            
            # 构建请求参数
            params = {
                'instType': 'SWAP',  # 只同步永续合约
                'instId': inst_id,
                'ordType': 'market',  # 只查询市价单
                'state': 'filled',  # 查询完全成交的订单（默认，实际会通过_fetch_orders_history_multi_state拉取两种状态）
                'limit': str(min(limit, 100))  # 最大100
            }
            
            # 添加时间参数
            if begin:
                params['begin'] = str(begin)
            if end:
                params['end'] = str(end)
            
            # 如果有after参数，添加分页
            if after:
                params['after'] = after
            
            # 构建查询字符串
            query_string = urlencode(params)
            
            # 构建请求路径（GET请求的查询参数包含在requestPath中）
            request_path = '/api/v5/trade/orders-history-archive'
            if query_string:
                request_path += '?' + query_string
            
            # 确定API基础URL
            # OKX API v5统一使用www.okx.com，沙箱和生产环境通过API Key区分
            base_url = 'https://www.okx.com'
            
            # 构建完整URL
            url = base_url + request_path
            
            
            # 直接发送请求，避免通过API管理器队列导致时间戳过期
            # 注意：时间戳必须在实际发送请求的瞬间生成
            try:
                # 在实际发送请求时生成时间戳（避免过期）
                now = datetime.now(timezone.utc)
                timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'  # ISO 8601格式，保留毫秒
                
                # 构建签名
                # OKX API签名规则：timestamp + method + requestPath + body
                # GET请求：查询参数包含在requestPath中，body为空字符串
                signature = self._build_okx_signature(
                    timestamp=timestamp,
                    method='GET',
                    request_path=request_path,  # 包含查询参数
                    body=''  # GET请求body为空字符串
                )
                
                # 构建请求头
                # 注意：Passphrase使用明文，不需要加密
                headers = {
                    'Content-Type': 'application/json',
                    'OK-ACCESS-KEY': api_key,
                    'OK-ACCESS-SIGN': signature,
                    'OK-ACCESS-TIMESTAMP': timestamp,
                    'OK-ACCESS-PASSPHRASE': passphrase
                }
                
                # 如果是模拟盘，添加模拟盘标记头
                if settings.EXCHANGE_SANDBOX:
                    headers['x-simulated-trading'] = '1'
                
                
                # 简单限流：避免请求过快
                time.sleep(0.2)
                
                http_response = requests.get(url, headers=headers, timeout=30)
                http_response.raise_for_status()
                response = http_response.json()
            except requests.exceptions.RequestException as e:
                logger.error(f"调用OKX API失败: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        logger.error(f"错误响应: {error_data}")
                        # 如果是401或50102错误，记录更详细的信息
                        if e.response.status_code == 401:
                            logger.error(
                                f"401认证失败，请检查:\n"
                                f"  1. API Key是否正确\n"
                                f"  2. Secret Key是否正确\n"
                                f"  3. Passphrase是否正确\n"
                                f"  4. 是否使用了正确的环境（模拟盘/实盘）\n"
                                f"  5. 时间戳格式: {timestamp}\n"
                                f"  6. 请求路径: {request_path}\n"
                                f"  7. 签名: {signature}"
                            )
                        elif error_data.get('code') == '50102':
                            logger.error(
                                f"50102时间戳过期错误，请检查:\n"
                                f"  1. 系统时间是否与OKX服务器时间同步\n"
                                f"  2. 时间戳: {timestamp}\n"
                                f"  3. 当前UTC时间: {datetime.now(timezone.utc).isoformat()}\n"
                                f"  4. 建议：确保系统时间与标准时间同步（NTP）"
                            )
                    except:
                        logger.error(f"错误响应内容: {e.response.text[:500]}")
                return []
            except Exception as e:
                logger.error(f"调用OKX API异常: {e}", exc_info=True)
                return []
            
            if not response:
                return []
            
            if not response or response.get('code') != '0':
                error_msg = response.get('msg', '未知错误') if response else '返回结果为空'
                logger.warning(f"获取{inst_id}历史订单失败: {error_msg}")
                return []
            
            data = response.get('data', [])
            if not data:
                logger.debug(f"{inst_id} 历史订单数据为空")
                return []
            
            return data
            
        except Exception as e:
            logger.error(f"调用OKX API获取{inst_id}历史订单失败: {e}", exc_info=True)
            return []
    
    def _save_orders(self, orders: List[Dict[str, Any]]) -> int:
        """
        保存订单到数据库
        
        Args:
            orders: 订单列表
            
        Returns:
            成功保存的订单数量
        """
        if not orders:
            return 0
        
        saved_count = 0
        with self.db.get_session() as session:
            try:
                for order_data in orders:
                    try:
                        # 保存完整原始数据
                        if OrderHistoryRepository.insert_order(session, order_data, raw_data=order_data):
                            saved_count += 1
                    except Exception as e:
                        logger.warning(f"保存订单失败 ordId={order_data.get('ordId', 'N/A')}: {e}")
                        continue
                
                session.commit()
                
            except Exception as e:
                session.rollback()
                logger.error(f"保存历史订单到数据库失败: {e}", exc_info=True)
        
        return saved_count
    
    def _sync_symbol_initial(self, symbol: str) -> bool:
        """
        首次同步某个币种的历史订单（从配置的开始时间拉取）
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            
        Returns:
            是否同步成功
        """
        try:
            inst_id = self._symbol_to_inst_id(symbol)
            # 获取开始时间
            start_time_ms = self._get_start_time_ms()
            
            # 获取数据库最新订单ID
            with self.db.get_session() as session:
                latest_ord_id = OrderHistoryRepository.get_latest_order_id(session, symbol=symbol)
            
            if latest_ord_id:
                return self._sync_symbol_incremental(symbol, latest_ord_id)
            
            # 首次同步：从开始时间拉取
            total_saved = 0
            after = None
            max_iterations = 1000  # 防止无限循环
            iteration = 0
            
            # 获取当前时间作为结束时间（毫秒时间戳）
            end_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            while iteration < max_iterations:
                iteration += 1
                
                # 获取订单（所有分页请求都传递开始时间和结束时间，确保只拉取指定时间范围内的数据）
                orders = self._fetch_orders_history(
                    inst_id, 
                    after=after, 
                    limit=100,
                    begin=start_time_ms,
                    end=end_time_ms
                )
                
                if not orders:
                    break
                
                # 保存订单
                saved_count = self._save_orders(orders)
                total_saved += saved_count
                
                # 如果返回的订单数少于limit，说明已经拉取完
                if len(orders) < 100:
                    break
                
                # 使用最后一个订单的ordId作为after参数（继续拉取更旧的数据）
                last_order = orders[-1]
                after = last_order.get('ordId')
                
                if not after:
                    break
                
                # 避免请求过快
                time.sleep(0.2)
            
            logger.info(f"{symbol} 订单历史同步完成，共保存 {total_saved} 条")
            
            # 同步完成后，自动修复未关联cl_ord_id的订单和缺失的trading_relations记录
            if total_saved > 0:
                try:
                    with self.db.get_session() as session:
                        # 先修复cl_ord_id
                        fixed_cl_ord_id_count = OrderHistoryRepository.fix_missing_cl_ord_id(
                            session, symbol=symbol, limit=50
                        )
                        if fixed_cl_ord_id_count > 0:
                            logger.info(f"{symbol} 自动修复了 {fixed_cl_ord_id_count} 个未关联cl_ord_id的订单")
                        
                        # 再修复trading_relations
                        fixed_tr_count = OrderHistoryRepository.fix_missing_trading_relations(
                            session, symbol=symbol, limit=50
                        )
                        if fixed_tr_count > 0:
                            logger.info(f"{symbol} 自动修复了 {fixed_tr_count} 个缺失trading_relations的订单")
                except Exception as e:
                    logger.warning(f"{symbol} 自动修复订单关联失败: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"{symbol} 历史订单首次同步失败: {e}", exc_info=True)
            return False
    
    def _sync_symbol_incremental(self, symbol: str, after_ord_id: Optional[str] = None) -> bool:
        """
        增量同步某个币种的历史订单（拉取数据库最新订单之后的新订单）
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            after_ord_id: 上次同步的最新订单ID（可选，如果不提供则从数据库查询）
            
        Returns:
            是否同步成功
        """
        try:
            inst_id = self._symbol_to_inst_id(symbol)
            
            # 如果没有提供after_ord_id，从数据库查询
            if not after_ord_id:
                with self.db.get_session() as session:
                    after_ord_id = OrderHistoryRepository.get_latest_order_id(session, symbol=symbol)
            
            if not after_ord_id:
                return self._sync_symbol_initial(symbol)
            
            # 获取数据库最新订单的创建时间，作为增量同步的开始时间
            with self.db.get_session() as session:
                from sqlalchemy import text
                sql = text("""
                    SELECT c_time_ms, c_time
                    FROM order_history
                    WHERE symbol = :symbol AND ord_id = :ord_id
                """)
                result = session.execute(sql, {'symbol': symbol, 'ord_id': after_ord_id}).fetchone()
                
                if not result:
                    return self._sync_symbol_initial(symbol)
                
                latest_order_time_ms = result[0]
                latest_order_time = result[1]
            
            # 增量同步：从数据库最新订单的时间开始，到当前时间
            # 注意：begin 使用最新订单的时间+1毫秒，避免重复拉取
            begin_time_ms = latest_order_time_ms + 1
            now = datetime.now(timezone.utc)
            # 拉取到当前时间
            end_time_ms = int(now.timestamp() * 1000)
            
            # 如果时间窗口已经超过最新订单时间，说明没有需要拉取的数据
            if end_time_ms <= begin_time_ms:
                logger.debug(
                    f"{symbol} 增量同步：时间窗口内无新数据需要拉取 "
                    f"(最新订单时间: {latest_order_time}, 当前时间: {now})"
                )
                return True
            
            
            # 增量同步：使用时间范围拉取新订单，不使用after参数
            # after参数是拉取更旧的数据，不适合增量同步
            # 使用时间范围分页：记录已拉取的最大时间，下次从这个时间继续拉取
            total_saved = 0
            current_begin_time_ms = begin_time_ms
            max_iterations = 100  # 增量同步通常数据量不大，限制迭代次数
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                
                # 使用时间范围拉取新订单（不使用after参数，因为after是拉取更旧的数据）
                orders = self._fetch_orders_history(
                    inst_id,
                    after=None,  # 不使用after参数
                    limit=100,
                    begin=current_begin_time_ms,
                    end=end_time_ms
                )
                
                if not orders:
                    break
                
                # 保存订单
                saved_count = self._save_orders(orders)
                total_saved += saved_count
                
                # 如果返回的订单数少于limit，说明已经拉取完
                if len(orders) < 100:
                    break
                
                # 找到已拉取订单中的最大时间，下次从这个时间+1毫秒继续拉取
                max_time_ms = current_begin_time_ms
                for order in orders:
                    order_time_ms = None
                    try:
                        # 尝试从fillTime获取时间（成交时间更准确）
                        fill_time_str = order.get('fillTime', '')
                        if fill_time_str:
                            order_time_ms, _ = OrderHistoryRepository.parse_timestamp_ms(fill_time_str)
                        # 如果没有fillTime，使用cTime
                        if order_time_ms is None:
                            c_time_str = order.get('cTime', '')
                            if c_time_str:
                                order_time_ms, _ = OrderHistoryRepository.parse_timestamp_ms(c_time_str)
                        if order_time_ms and order_time_ms > max_time_ms:
                            max_time_ms = order_time_ms
                    except:
                        continue
                
                # 如果所有订单的时间都相同或更早，说明已经拉取完
                if max_time_ms <= current_begin_time_ms:
                    break
                
                # 下次从这个时间+1毫秒继续拉取
                current_begin_time_ms = max_time_ms + 1
                
                # 避免请求过快
                time.sleep(0.2)
            
            if total_saved > 0:
                logger.info(f"{symbol} 订单历史同步完成，新增 {total_saved} 条")
                
                # 同步完成后，自动修复未关联cl_ord_id的订单和缺失的trading_relations记录
                try:
                    with self.db.get_session() as session:
                        # 先修复cl_ord_id
                        fixed_cl_ord_id_count = OrderHistoryRepository.fix_missing_cl_ord_id(
                            session, symbol=symbol, limit=50
                        )
                        if fixed_cl_ord_id_count > 0:
                            logger.info(f"{symbol} 自动修复了 {fixed_cl_ord_id_count} 个未关联cl_ord_id的订单")
                        
                        # 再修复trading_relations
                        fixed_tr_count = OrderHistoryRepository.fix_missing_trading_relations(
                            session, symbol=symbol, limit=50
                        )
                        if fixed_tr_count > 0:
                            logger.info(f"{symbol} 自动修复了 {fixed_tr_count} 个缺失trading_relations的订单")
                except Exception as e:
                    logger.warning(f"{symbol} 自动修复订单关联失败: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"{symbol} 历史订单增量同步失败: {e}", exc_info=True)
            return False
    
    def _sync_all_symbols(self):
        """同步所有配置的币种"""
        # 检查是否正在同步，避免并发执行
        with self.sync_lock:
            if self.is_syncing:
                logger.warning("上一次同步尚未完成，跳过本次同步")
                return
            self.is_syncing = True
        
        try:
            for symbol in self.sync_symbols:
                try:
                    # 增量同步
                    self._sync_symbol_incremental(symbol)
                except Exception as e:
                    logger.error(f"{symbol} 历史订单同步异常: {e}", exc_info=True)
                    continue
            
            self.last_sync_time = datetime.now(timezone.utc)
        finally:
            # 确保无论成功或失败都释放同步标志
            with self.sync_lock:
                self.is_syncing = False
    
    def run(self):
        """线程主循环"""
        # 启动时先执行一次首次同步（如果需要）
        try:
            # 检查是否需要首次同步
            need_initial_sync = False
            for symbol in self.sync_symbols:
                with self.db.get_session() as session:
                    latest_ord_id = OrderHistoryRepository.get_latest_order_id(session, symbol=symbol)
                    if not latest_ord_id:
                        need_initial_sync = True
                        break
            
            if need_initial_sync:
                for symbol in self.sync_symbols:
                    self._sync_symbol_initial(symbol)
        except Exception as e:
            logger.error(f"首次同步检查失败: {e}", exc_info=True)
        
        # 主循环：每10秒执行一次同步（订单数据仅通过API拉取）
        while not self.stop_event.is_set():
            try:
                self._sync_all_symbols()
                # 等待10秒后继续
                self.stop_event.wait(self.sync_interval)
                
            except Exception as e:
                logger.error(f"历史订单同步循环异常: {e}", exc_info=True)
                # 出错时等待10秒再继续
                self.stop_event.wait(self.sync_interval)

