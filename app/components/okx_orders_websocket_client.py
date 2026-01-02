"""
OKX WebSocket私有频道客户端 - 订单频道
用于实时接收订单更新，作为订单数据的主要来源
"""
import json
import time
import threading
import queue
import hmac
import base64
from typing import Optional, Dict, Any, Tuple
import websocket
from app.config import settings
from app.utils.logger import logger
from app.database.connection import db
from app.database.order_history import OrderHistoryRepository


class OKXOrdersWebSocketClient:
    """OKX WebSocket私有频道客户端 - 订单频道"""
    
    def __init__(self):
        """初始化WebSocket客户端"""
        self.ws_url = settings.WS_PRIVATE_URL
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        # 状态管理
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        self.running = False
        
        # 心跳管理
        self.last_message_time = 0
        self.last_ping_time = 0
        self.pending_pong = False
        self.heartbeat_timer: Optional[threading.Timer] = None
        
        # 重连管理
        self.reconnect_timer: Optional[threading.Timer] = None
        self.reconnect_count = 0
        
        # 去重处理：记录已处理的(ord_id, u_time)组合，保留近1小时
        # key: (ord_id, u_time), value: 处理时间戳
        self.processed_orders: Dict[Tuple[str, int], float] = {}
        self.order_lock = threading.Lock()
        
        # 清理定时器：定期清理过期的去重记录
        self.cleanup_timer: Optional[threading.Timer] = None
        
        # 订单处理队列（异步处理，避免阻塞WebSocket消息）
        # 队列大小限制为500，避免内存无限增长（增加大小以减少队列满的情况）
        self.order_queue: queue.Queue = queue.Queue(maxsize=500)
        self.order_processor_thread: Optional[threading.Thread] = None
        
        # 队列去重：记录队列中已有的订单（用于快速检查，避免重复入队）
        # key: (ord_id, u_time), value: 时间戳
        self.queued_orders: Dict[Tuple[str, int], float] = {}
        
        # 失败订单重试记录：记录写入失败的订单及重试次数
        # key: (ord_id, u_time), value: (重试次数, 最后重试时间)
        self.failed_orders: Dict[Tuple[str, int], Tuple[int, float]] = {}
        self.max_retry_count = 3  # 最大重试次数
        
        # API凭证
        self.api_key = settings.EXCHANGE_API_KEY
        self.secret = settings.EXCHANGE_SECRET
        self.passphrase = settings.EXCHANGE_PASSPHRASE
    
    def start(self):
        """启动WebSocket连接"""
        if self.running:
            return
        
        self.running = True
        
        # 启动订单处理线程
        self._start_order_processor()
        
        # 启动清理定时器
        self._start_cleanup_timer()
        
        self._connect()
        logger.info("订单WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket连接"""
        self.running = False
        
        # 停止订单处理线程
        self._stop_order_processor()
        
        # 取消定时器
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        if self.cleanup_timer:
            self.cleanup_timer.cancel()
        
        # 关闭连接
        if self.ws:
            self.ws.close()
        
        # 等待线程结束
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=3)
        
        logger.info("订单WebSocket客户端已停止")
    
    def _connect(self):
        """建立WebSocket连接"""
        if not self.running:
            return
        
        try:
            logger.info(f"正在连接订单WebSocket: {self.ws_url}")
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            # 在新线程中运行WebSocket
            self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
            self.ws_thread.start()
            
        except Exception as e:
            logger.error(f"订单WebSocket连接失败: {e}", exc_info=True)
            self._schedule_reconnect()
    
    def _run_websocket(self):
        """运行WebSocket（在独立线程中）"""
        try:
            ssl_verify = settings.WS_SSL_VERIFY
            cert_path = settings.WS_SSL_CERT_PATH
            
            import ssl
            import certifi
            ssl_options = {}
            
            if not ssl_verify:
                ssl_options = {
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False
                }
                logger.warning("SSL证书验证已禁用（仅用于测试环境）")
            elif cert_path:
                ssl_options = {"ca_certs": cert_path}
            else:
                try:
                    ssl_options = {
                        "cert_reqs": ssl.CERT_REQUIRED,
                        "check_hostname": True,
                        "ca_certs": certifi.where()
                    }
                    logger.debug(f"使用certifi证书: {certifi.where()}")
                except Exception as e:
                    logger.warning(f"无法使用certifi证书，使用系统默认: {e}")
                    ssl_options = {
                        "cert_reqs": ssl.CERT_REQUIRED,
                        "check_hostname": True
                    }
            
            self.ws.run_forever(sslopt=ssl_options)
        except Exception as e:
            logger.error(f"订单WebSocket运行异常: {e}", exc_info=True)
            self._schedule_reconnect()
    
    def _on_open(self, ws):
        """连接打开回调"""
        logger.info("订单WebSocket连接已建立")
        self.connected = True
        self.reconnect_count = 0
        self.last_message_time = time.time()
        self.pending_pong = False
        
        # 先登录
        self._login()
        
        # 启动心跳检查
        self._start_heartbeat()
    
    def _login(self):
        """登录私有频道"""
        try:
            timestamp = str(int(time.time()))
            message = timestamp + "GET" + "/users/self/verify"
            
            # 生成签名
            mac = hmac.new(
                bytes(self.secret, encoding='utf8'),
                bytes(message, encoding='utf-8'),
                digestmod='sha256'
            )
            sign = base64.b64encode(mac.digest()).decode()
            
            # 构建登录消息
            login_msg = {
                "op": "login",
                "args": [
                    {
                        "apiKey": self.api_key,
                        "passphrase": self.passphrase,
                        "timestamp": timestamp,
                        "sign": sign
                    }
                ]
            }
            
            self.ws.send(json.dumps(login_msg))
            logger.info("已发送登录请求")
        except Exception as e:
            logger.error(f"发送登录消息失败: {e}", exc_info=True)
    
    def _subscribe_orders(self, inst_type: str = "SWAP"):
        """订阅订单频道"""
        subscribe_msg = {
            "op": "subscribe",
            "args": [{
                "channel": "orders",
                "instType": inst_type
            }]
        }
        
        try:
            self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"已发送订单订阅请求: {subscribe_msg}")
        except Exception as e:
            logger.error(f"发送订阅消息失败: {e}", exc_info=True)
    
    def _on_message(self, ws, message):
        """接收消息回调"""
        try:
            self.last_message_time = time.time()
            
            # 处理心跳响应 'pong'（字符串，不是JSON）
            message_str = message.strip() if isinstance(message, str) else str(message).strip()
            if message_str == 'pong':
                logger.debug("收到pong响应")
                self.pending_pong = False
                self.last_message_time = time.time()
                return
            
            # 尝试解析JSON消息
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                logger.warning(f"收到非JSON消息，忽略: {message[:100]}")
                return
            
            # 处理登录响应
            if isinstance(data, dict) and "event" in data:
                if data["event"] == "login":
                    if data.get("code") == "0":
                        logger.info("登录成功")
                        self.logged_in = True
                        # 登录成功后订阅订单频道
                        self._subscribe_orders()
                    else:
                        logger.error(f"登录失败: {data}")
                elif data["event"] == "subscribe":
                    logger.info(f"订阅成功: {data}")
                    self.subscribed = True
                elif data["event"] == "error":
                    logger.error(f"订阅失败: {data}")
                elif data["event"] == "pong":
                    logger.debug("收到pong响应（JSON格式）")
                    self.pending_pong = False
                    self.last_message_time = time.time()
                return
            
            # 处理订单数据
            # OKX订单数据格式: {"arg": {"channel": "orders", "instType": "SWAP"}, "eventType": "snapshot"/"update", "data": [...]}
            if isinstance(data, dict) and "data" in data:
                event_type = data.get("eventType", "update")  # snapshot 或 update
                if isinstance(data["data"], list):
                    for order_data in data["data"]:
                        self._process_order(order_data, event_type)
                else:
                    logger.debug(f"收到订单消息但data不是列表: {data}")
        
        except Exception as e:
            logger.error(f"处理订单WebSocket消息失败: {e}", exc_info=True)
            logger.error(f"原始消息: {message}")
    
    def _process_order(self, order_data: Dict[str, Any], event_type: str):
        """
        处理订单数据（解析和验证，不写入数据库）
        
        Args:
            order_data: 订单数据字典
            event_type: 事件类型（"snapshot" 或 "update"）
        """
        try:
            # 提取关键字段
            ord_id = order_data.get("ordId", "")
            inst_id = order_data.get("instId", "")
            state = order_data.get("state", "")
            side = order_data.get("side", "")
            pos_side = order_data.get("posSide", "")
            cl_ord_id = order_data.get("clOrdId", "")
            
            # 验证必要字段
            if not ord_id:
                logger.warning(f"订单数据缺少ordId，跳过处理: {order_data}")
                return
            
            if not inst_id:
                logger.warning(f"订单数据缺少instId，跳过处理: ordId={ord_id}")
                return
            
            # 解析u_time用于去重
            u_time = order_data.get("uTime", "")
            u_time_ms = 0
            if u_time:
                try:
                    u_time_ms = int(u_time)
                except (ValueError, TypeError):
                    logger.warning(f"订单更新时间格式错误: ordId={ord_id}, uTime={u_time}")
                    # 如果u_time无效，使用当前时间戳（毫秒）作为备选，避免去重失效
                    u_time_ms = int(time.time() * 1000)
            
            # 去重检查：使用(ord_id, u_time)作为唯一标识
            # 因为同一个订单可能会多次更新（u_time会变化），所以需要同时使用ord_id和u_time
            order_key = (ord_id, u_time_ms)
            
            # 检查是否已处理过
            with self.order_lock:
                if order_key in self.processed_orders:
                    logger.debug(
                        f"订单已处理过，跳过: ordId={ord_id}, uTime={u_time_ms}"
                    )
                    return
                
                # 检查是否已在队列中
                if order_key in self.queued_orders:
                    logger.debug(
                        f"订单已在队列中，跳过: ordId={ord_id}, uTime={u_time_ms}"
                    )
                    return
            
            # 将订单放入队列（异步处理，避免阻塞WebSocket消息）
            try:
                # 构建订单信息字典（包含原始数据和元数据）
                order_info = {
                    "order_data": order_data,
                    "event_type": event_type,
                    "ord_id": ord_id,
                    "u_time_ms": u_time_ms,
                    "order_key": order_key
                }
                
                # 尝试放入队列（使用超时，避免长时间阻塞）
                # 如果队列满，等待最多0.1秒，如果还是满则记录错误
                try:
                    self.order_queue.put(order_info, block=True, timeout=0.1)
                    
                    # 记录到队列去重集合
                    with self.order_lock:
                        self.queued_orders[order_key] = time.time()
                    
                    logger.debug(
                        f"订单已加入处理队列: ordId={ord_id}, uTime={u_time_ms}, "
                        f"队列大小: {self.order_queue.qsize()}"
                    )
                except queue.Full:
                    # 队列满且超时，记录错误并尝试标记为已处理（避免重复尝试）
                    logger.error(
                        f"订单队列已满且超时，订单可能丢失: ordId={ord_id}, uTime={u_time_ms}, "
                        f"队列大小: {self.order_queue.qsize()}"
                    )
                    # 标记为已处理，避免重复尝试（虽然丢失了，但至少不会无限重试）
                    with self.order_lock:
                        self.processed_orders[order_key] = time.time()
            except Exception as e:
                logger.error(
                    f"将订单加入队列失败: ordId={ord_id}, 错误: {e}", 
                    exc_info=True
                )
            
        except Exception as e:
            logger.error(f"解析订单数据失败: {e}", exc_info=True)
            logger.error(f"订单数据: {order_data}")
    
    def _start_heartbeat(self):
        """启动心跳检查"""
        if not self.running:
            return
        
        current_time = time.time()
        heartbeat_interval = settings.WS_HEARTBEAT_INTERVAL
        ping_timeout = settings.WS_PING_TIMEOUT
        
        # 检查是否在等待pong响应
        if self.pending_pong:
            if current_time - self.last_ping_time > ping_timeout:
                logger.warning(
                    f"发送ping后{ping_timeout}秒内未收到pong响应，准备重连"
                )
                if self.ws:
                    self.ws.close()
                return
        else:
            # 如果heartbeat_interval秒内没有收到任何消息，发送ping
            if current_time - self.last_message_time > heartbeat_interval:
                try:
                    if self.ws:
                        self.ws.send('ping')
                        self.last_ping_time = current_time
                        self.pending_pong = True
                        logger.debug("已发送ping心跳")
                except Exception as e:
                    logger.error(f"发送ping心跳失败: {e}", exc_info=True)
                    if self.ws:
                        self.ws.close()
                    return
        
        # 继续心跳检查（每秒检查一次）
        self.heartbeat_timer = threading.Timer(1.0, self._start_heartbeat)
        self.heartbeat_timer.start()
    
    def _schedule_reconnect(self):
        """安排重连"""
        if not self.running:
            return
        
        if self.reconnect_timer:
            return
        
        reconnect_interval = settings.WS_RECONNECT_INTERVAL
        self.reconnect_count += 1
        
        logger.info(f"将在 {reconnect_interval} 秒后重连订单WebSocket（第 {self.reconnect_count} 次）")
        
        self.reconnect_timer = threading.Timer(reconnect_interval, self._reconnect)
        self.reconnect_timer.start()
    
    def _reconnect(self):
        """执行重连"""
        self.reconnect_timer = None
        
        if not self.running:
            return
        
        logger.info("开始重连订单WebSocket...")
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        self._connect()
    
    def _on_error(self, ws, error):
        """错误回调"""
        logger.error(f"订单WebSocket错误: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """连接关闭回调"""
        logger.warning(f"订单WebSocket连接已关闭: code={close_status_code}, msg={close_msg}")
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        
        if self.running:
            self._schedule_reconnect()
    
    def _start_order_processor(self):
        """启动订单处理线程"""
        if self.order_processor_thread and self.order_processor_thread.is_alive():
            return
        
        self.order_processor_thread = threading.Thread(
            target=self._order_processor_loop,
            name="OrderProcessor",
            daemon=True
        )
        self.order_processor_thread.start()
        logger.debug("订单处理线程已启动")
    
    def _stop_order_processor(self):
        """停止订单处理线程"""
        # 放入停止标记
        try:
            self.order_queue.put(None, timeout=1)
        except queue.Full:
            pass
        
        # 等待线程结束
        if self.order_processor_thread and self.order_processor_thread.is_alive():
            self.order_processor_thread.join(timeout=3)
            logger.debug("订单处理线程已停止")
    
    def _order_processor_loop(self):
        """订单处理循环（后台线程）"""
        logger.debug("订单处理循环已启动")
        
        while self.running:
            try:
                # 从队列获取订单（阻塞等待，最多1秒）
                try:
                    order_info = self.order_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 如果收到None，表示停止信号
                if order_info is None:
                    break
                
                # 处理订单（写入数据库）
                self._handle_order(order_info)
                
                # 处理完成后，从队列去重集合中移除
                order_key = order_info.get("order_key")
                if order_key:
                    with self.order_lock:
                        if order_key in self.queued_orders:
                            del self.queued_orders[order_key]
                
            except Exception as e:
                logger.error(f"订单处理循环异常: {e}", exc_info=True)
        
        logger.debug("订单处理循环已退出")
    
    def _handle_order(self, order_info: Dict[str, Any]):
        """
        处理订单（在后台线程中执行，写入数据库）
        
        Args:
            order_info: 订单信息字典，包含order_data, event_type等
        """
        try:
            order_data = order_info.get("order_data")
            event_type = order_info.get("event_type", "update")
            ord_id = order_info.get("ord_id", "")
            order_key = order_info.get("order_key")
            
            if not order_data or not ord_id:
                logger.warning(f"订单信息不完整，跳过处理: {order_info}")
                return
            
            # 提取关键字段用于日志
            inst_id = order_data.get("instId", "")
            state = order_data.get("state", "")
            side = order_data.get("side", "")
            pos_side = order_data.get("posSide", "")
            cl_ord_id = order_data.get("clOrdId", "")
            
            logger.info(
                f"开始处理订单: ordId={ord_id}, instId={inst_id}, "
                f"state={state}, side={side}, posSide={pos_side}, "
                f"clOrdId={cl_ord_id}, eventType={event_type}"
            )
            
            # 验证订单状态（只处理已成交或部分成交的订单）
            if state not in ["filled"]:
                logger.debug(
                    f"订单状态为{state}，暂不写入数据库: ordId={ord_id}"
                )
                # 即使不写入数据库，也标记为已处理（避免重复处理）
                if order_key:
                    with self.order_lock:
                        self.processed_orders[order_key] = time.time()
                return
            
            # 检查重试次数
            retry_count = 0
            with self.order_lock:
                if order_key in self.failed_orders:
                    retry_count, last_retry_time = self.failed_orders[order_key]
                    # 如果超过最大重试次数，标记为已处理（避免无限重试）
                    if retry_count >= self.max_retry_count:
                        logger.warning(
                            f"订单重试次数已达上限({self.max_retry_count})，放弃处理: "
                            f"ordId={ord_id}, instId={inst_id}"
                        )
                        # 标记为已处理，避免无限重试
                        self.processed_orders[order_key] = time.time()
                        # 移除失败记录
                        del self.failed_orders[order_key]
                        return
            
            # 写入数据库
            try:
                with db.get_session() as session:
                    success = OrderHistoryRepository.insert_order(
                        session=session,
                        order_data=order_data,
                        raw_data=order_data  # 使用完整原始数据
                    )
                    
                    if success:
                        logger.info(
                            f"订单写入数据库成功: ordId={ord_id}, instId={inst_id}, "
                            f"state={state}, clOrdId={cl_ord_id}"
                        )
                        
                        # 标记为已处理
                        if order_key:
                            with self.order_lock:
                                self.processed_orders[order_key] = time.time()
                                # 清除失败记录（如果存在）
                                if order_key in self.failed_orders:
                                    del self.failed_orders[order_key]
                    else:
                        logger.warning(
                            f"订单写入数据库失败: ordId={ord_id}, instId={inst_id}, "
                            f"重试次数: {retry_count + 1}/{self.max_retry_count}"
                        )
                        # 记录失败，增加重试次数
                        with self.order_lock:
                            self.failed_orders[order_key] = (retry_count + 1, time.time())
                        # 不标记为已处理，允许重试（但会检查重试次数）
                        
            except Exception as e:
                logger.error(
                    f"写入订单到数据库时发生错误: ordId={ord_id}, 错误: {e}, "
                    f"重试次数: {retry_count + 1}/{self.max_retry_count}",
                    exc_info=True
                )
                # 记录失败，增加重试次数
                with self.order_lock:
                    self.failed_orders[order_key] = (retry_count + 1, time.time())
                # 不标记为已处理，允许重试（但会检查重试次数）
            
        except Exception as e:
            logger.error(f"处理订单失败: {e}", exc_info=True)
    
    def _start_cleanup_timer(self):
        """启动清理定时器（定期清理过期的去重记录）"""
        if not self.running:
            return
        
        # 每10分钟清理一次
        self.cleanup_timer = threading.Timer(600.0, self._start_cleanup_timer)
        self.cleanup_timer.start()
        
        # 执行清理
        self._cleanup_processed_orders()
    
    def _cleanup_processed_orders(self):
        """清理过期的去重记录（保留近1小时）"""
        try:
            current_time = time.time()
            expire_time = 60 * 60  # 1小时
            queue_expire_time = 5 * 60  # 5分钟（队列去重记录）
            failed_expire_time = 30 * 60  # 30分钟（失败订单记录）
            
            with self.order_lock:
                # 清理processed_orders（已处理的记录）
                keys_to_delete = [
                    key for key, process_time in self.processed_orders.items()
                    if current_time - process_time > expire_time
                ]
                for key in keys_to_delete:
                    del self.processed_orders[key]
                
                # 清理queued_orders（队列中的记录）
                queue_keys_to_delete = [
                    key for key, queue_time in self.queued_orders.items()
                    if current_time - queue_time > queue_expire_time
                ]
                for key in queue_keys_to_delete:
                    del self.queued_orders[key]
                
                # 清理failed_orders（失败订单记录）
                failed_keys_to_delete = [
                    key for key, (retry_count, last_retry_time) in self.failed_orders.items()
                    if current_time - last_retry_time > failed_expire_time
                ]
                for key in failed_keys_to_delete:
                    del self.failed_orders[key]
                
                if keys_to_delete or queue_keys_to_delete or failed_keys_to_delete:
                    logger.debug(
                        f"清理了 {len(keys_to_delete)} 条过期的处理记录，"
                        f"{len(queue_keys_to_delete)} 条过期的队列记录，"
                        f"{len(failed_keys_to_delete)} 条过期的失败记录，"
                        f"当前剩余 {len(self.processed_orders)} 条处理记录，"
                        f"{len(self.queued_orders)} 条队列记录，"
                        f"{len(self.failed_orders)} 条失败记录"
                    )
        except Exception as e:
            logger.error(f"清理订单去重记录失败: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        with self.order_lock:
            return {
                "running": self.running,
                "connected": self.connected,
                "logged_in": self.logged_in,
                "subscribed": self.subscribed,
                "reconnect_count": self.reconnect_count,
                "processed_orders_count": len(self.processed_orders),
                "queued_orders_count": len(self.queued_orders),
                "order_queue_size": self.order_queue.qsize()
            }

