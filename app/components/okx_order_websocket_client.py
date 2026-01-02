"""
OKX WebSocket私有频道客户端 - 用于测试持仓频道数据
"""
import json
import time
import threading
import queue
import hmac
import base64
from typing import Optional, Dict, Any, List, Tuple
import websocket
from app.config import settings
from app.utils.logger import logger


class OKXOrderWebSocketClient:
    """OKX WebSocket私有频道客户端 - 持仓频道测试"""
    
    def __init__(self, trading_manager=None):
        """初始化WebSocket客户端"""
        self.ws_url = settings.WS_PRIVATE_URL
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        # 状态管理
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        self.running = False
        
        # 持仓数据（存储所有收到的持仓消息）
        self.position_messages: List[Dict[str, Any]] = []
        self.position_lock = threading.Lock()
        self.max_messages = 100  # 最多保存100条消息
        
        # 持仓状态追踪：记录每个posId的上一次持仓信息
        # key: posId (str), value: 持仓数据字典
        self.position_states: Dict[str, Dict[str, Any]] = {}
        
        # 去重处理：记录已处理的(pos_id, u_time)组合，保留近半小时
        # key: (pos_id, u_time), value: 处理时间戳
        self.processed_closes: Dict[Tuple[str, int], float] = {}
        
        # 平仓事件处理队列（异步处理，避免阻塞WebSocket消息）
        # 队列大小限制为100，避免内存无限增长
        self.close_event_queue: queue.Queue = queue.Queue(maxsize=100)
        self.close_processor_thread: Optional[threading.Thread] = None
        
        # 队列去重：记录队列中已有的事件（用于快速检查，避免重复入队）
        # key: (pos_id, u_time), value: 时间戳
        self.queued_closes: Dict[Tuple[str, int], float] = {}
        
        # 持仓数据处理队列（异步处理，避免阻塞WebSocket消息）
        # 队列大小限制为200，避免内存无限增长
        self.position_data_queue: queue.Queue = queue.Queue(maxsize=200)
        self.position_processor_thread: Optional[threading.Thread] = None
        
        # 心跳管理
        self.last_message_time = 0
        self.last_ping_time = 0
        self.pending_pong = False  # 是否在等待pong响应
        self.heartbeat_timer: Optional[threading.Timer] = None
        
        # 重连管理
        self.reconnect_timer: Optional[threading.Timer] = None
        self.reconnect_count = 0
        
        # API凭证
        self.api_key = settings.EXCHANGE_API_KEY
        self.secret = settings.EXCHANGE_SECRET
        self.passphrase = settings.EXCHANGE_PASSPHRASE
        
        # TradingManager依赖（用于处理外部平仓）
        self.trading_manager = trading_manager
    
    def start(self):
        """启动WebSocket连接"""
        if self.running:
            return
        
        self.running = True
        
        # 启动平仓事件处理线程
        self._start_close_processor()
        
        # 启动持仓数据处理线程
        self._start_position_processor()
        
        self._connect()
        logger.info("持仓WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket连接"""
        self.running = False
        
        # 停止平仓事件处理线程
        self._stop_close_processor()
        
        # 停止持仓数据处理线程
        self._stop_position_processor()
        
        # 取消定时器
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        
        # 关闭连接
        if self.ws:
            self.ws.close()
        
        # 等待线程结束
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=3)
        
        logger.info("持仓WebSocket客户端已停止")
    
    def _connect(self):
        """建立WebSocket连接"""
        if not self.running:
            return
        
        try:
            logger.info(f"正在连接持仓WebSocket: {self.ws_url}")
            
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
            logger.error(f"持仓WebSocket连接失败: {e}", exc_info=True)
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
            logger.error(f"持仓WebSocket运行异常: {e}", exc_info=True)
            self._schedule_reconnect()
    
    def _on_open(self, ws):
        """连接打开回调"""
        logger.info("持仓WebSocket连接已建立")
        self.connected = True
        self.reconnect_count = 0
        self.last_message_time = time.time()
        self.pending_pong = False  # 重置等待pong状态
        
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
    
    def _subscribe_positions(self, inst_type: str = "SWAP"):
        """订阅持仓频道"""
        subscribe_msg = {
            "op": "subscribe",
            "args": [{
                "channel": "positions",
                "instType": inst_type
            }]
        }
        
        try:
            self.ws.send(json.dumps(subscribe_msg))
            logger.info(f"已发送持仓订阅请求: {subscribe_msg}")
        except Exception as e:
            logger.error(f"发送订阅消息失败: {e}", exc_info=True)
    
    def _on_message(self, ws, message):
        """接收消息回调"""
        try:
            self.last_message_time = time.time()
            
            # 处理心跳响应 'pong'（字符串，不是JSON）
            # 注意：message可能是字符串'pong'，也可能包含空白字符，需要strip处理
            message_str = message.strip() if isinstance(message, str) else str(message).strip()
            if message_str == 'pong':
                logger.debug("收到pong响应")
                self.pending_pong = False  # 收到pong，清除等待状态
                self.last_message_time = time.time()  # 更新最后消息时间
                return
            
            # 尝试解析JSON消息
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                logger.warning(f"收到非JSON消息，忽略: {message[:100]}")
                return
            
            # 记录所有收到的消息（用于测试）
            self._save_message(data)
            
            # 处理登录响应
            if isinstance(data, dict) and "event" in data:
                if data["event"] == "login":
                    if data.get("code") == "0":
                        logger.info("登录成功")
                        self.logged_in = True
                        # 登录成功后订阅持仓频道
                        self._subscribe_positions()
                    else:
                        logger.error(f"登录失败: {data}")
                elif data["event"] == "subscribe":
                    logger.info(f"订阅成功: {data}")
                    self.subscribed = True
                elif data["event"] == "error":
                    logger.error(f"订阅失败: {data}")
                elif data["event"] == "pong":
                    # JSON格式的pong响应（备用处理）
                    logger.debug("收到pong响应（JSON格式）")
                    self.pending_pong = False  # 收到pong，清除等待状态
                    self.last_message_time = time.time()  # 更新最后消息时间
                return
            
            # 处理持仓数据（异步处理，避免阻塞WebSocket消息接收）
            # OKX持仓数据格式: {"arg": {"channel": "positions", "instType": "SWAP"}, "eventType": "snapshot"/"event_update", "data": [...]}
            if isinstance(data, dict) and "data" in data:
                event_type = data.get("eventType", "event_update")  # 默认为event_update
                if isinstance(data["data"], list):
                    for position_data in data["data"]:
                        # 将持仓数据放入队列，由后台线程异步处理
                        try:
                            self.position_data_queue.put_nowait({
                                "position_data": position_data,
                                "event_type": event_type
                            })
                        except queue.Full:
                            logger.warning("持仓数据处理队列已满，丢弃消息")
                else:
                    logger.debug(f"收到持仓消息但data不是列表: {data}")
        
        except Exception as e:
            logger.error(f"处理持仓WebSocket消息失败: {e}", exc_info=True)
            logger.error(f"原始消息: {message}")
    
    def _save_message(self, message: Dict[str, Any]):
        """保存收到的消息（用于测试）"""
        try:
            with self.position_lock:
                # 添加时间戳
                message_with_time = {
                    "timestamp": time.time(),
                    "data": message
                }
                self.position_messages.append(message_with_time)
                
                # 限制消息数量
                if len(self.position_messages) > self.max_messages:
                    self.position_messages.pop(0)
        except Exception as e:
            logger.error(f"保存消息失败: {e}", exc_info=True)
    
    def _process_position(self, position_data: Dict[str, Any], event_type: str = "event_update"):
        """处理持仓数据"""
        try:
            # 提取关键字段
            pos_id = position_data.get("posId", "")
            inst_id = position_data.get("instId", "")
            pos_side = position_data.get("posSide", "")
            pos = position_data.get("pos", "")
            avail_pos = position_data.get("availPos", "")
            avg_px = position_data.get("avgPx", "")
            upl = position_data.get("upl", "")
            upl_ratio = position_data.get("uplRatio", "")
            lever = position_data.get("lever", "")
            margin = position_data.get("margin", "")
            mgn_mode = position_data.get("mgnMode", "")
            
            logger.info(
                f"持仓详情 - posId: {pos_id}, instId: {inst_id}, "
                f"posSide: {pos_side}, pos: {pos}, availPos: {avail_pos}, "
                f"avgPx: {avg_px}, upl: {upl}, uplRatio: {upl_ratio}, "
                f"lever: {lever}, margin: {margin}, mgnMode: {mgn_mode}"
            )
            
            # 检测持仓变化（平仓检测）- 需要在更新状态之前检测
            # 对于event_update，正常检测
            # 对于snapshot，如果持仓为0，也应该检测（可能是重连后收到的最新状态）
            if pos_id:
                pos_str = position_data.get("pos", "0")
                try:
                    pos_value = float(pos_str) if pos_str else 0.0
                except (ValueError, TypeError):
                    pos_value = 0.0
                
                # event_update 时正常检测，snapshot 时如果持仓为0也检测
                if event_type == "event_update" or (event_type == "snapshot" and pos_value == 0):
                    logger.debug(
                        f"开始检测持仓变化: posId={pos_id}, eventType={event_type}, "
                        f"current_pos={pos_value}"
                    )
                    close_info = self._detect_position_change(pos_id, position_data, event_type)
                    if close_info:
                        logger.info(
                            f"检测到平仓事件: posId={pos_id}, close_amount={close_info.get('close_amount')}, "
                            f"is_full_close={close_info.get('is_full_close')}"
                        )
                        # 检测到平仓，调用TradingManager处理
                        self._handle_detected_close(close_info)
                    else:
                        logger.debug(
                            f"未检测到平仓: posId={pos_id}, eventType={event_type}, current_pos={pos_value}"
                        )
            
            # 更新持仓状态（用于后续检测持仓变化）
            if pos_id:
                self._update_position_state(pos_id, position_data, event_type)
        except Exception as e:
            logger.error(f"处理持仓数据失败: {e}", exc_info=True)
    
    def _update_position_state(self, pos_id: str, position_data: Dict[str, Any], event_type: str):
        """
        更新持仓状态
        
        Args:
            pos_id: 持仓ID
            position_data: 持仓数据字典
            event_type: 事件类型（"snapshot" 或 "event_update"）
        """
        try:
            with self.position_lock:
                # 对于snapshot，直接更新状态（初始化）
                # 对于event_update，更新状态（用于后续检测变化）
                self.position_states[pos_id] = {
                    "pos_id": pos_id,
                    "inst_id": position_data.get("instId", ""),
                    "pos_side": position_data.get("posSide", ""),
                    "pos": position_data.get("pos", ""),
                    "avail_pos": position_data.get("availPos", ""),
                    "avg_px": position_data.get("avgPx", ""),
                    "u_time": position_data.get("uTime", ""),
                    "mark_px": position_data.get("markPx", ""),
                    "trade_id": position_data.get("tradeId", ""),
                    "event_type": event_type,
                    "update_time": time.time()  # 记录更新时间戳
                }
                logger.debug(
                    f"更新持仓状态: posId={pos_id}, pos={position_data.get('pos', '')}, "
                    f"eventType={event_type}"
                )
        except Exception as e:
            logger.error(f"更新持仓状态失败: {e}", exc_info=True)
    
    def _detect_position_change(
        self, 
        pos_id: str, 
        position_data: Dict[str, Any], 
        event_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        检测持仓变化（平仓检测）
        
        Args:
            pos_id: 持仓ID
            position_data: 当前持仓数据
            event_type: 事件类型（"snapshot" 或 "event_update"）
        
        Returns:
            如果检测到平仓，返回包含平仓信息的字典；否则返回None
            格式: {
                "pos_id": str,
                "inst_id": str,
                "pos_side": str,
                "close_amount": float,  # 平仓数量
                "close_price": Optional[float],  # 平仓价格（如果有）
                "is_full_close": bool,  # 是否全部平仓
                "u_time": str,  # 更新时间
                "mark_px": str  # 标记价格
            }
        """
        try:
            # 只在 event_update 时检测变化（snapshot 只用于初始化状态）
            # 但如果是 snapshot 且持仓为0，也应该检测（可能是重连后收到的最新状态）
            current_pos_str = position_data.get("pos", "0")
            try:
                current_pos_value = float(current_pos_str) if current_pos_str else 0.0
            except (ValueError, TypeError):
                current_pos_value = 0.0
            
            if event_type != "event_update" and not (event_type == "snapshot" and current_pos_value == 0):
                return None
            
            # 清理过期的去重记录（30分钟前）
            self._cleanup_processed_closes()
            
            # 获取当前持仓数量
            current_pos_str = position_data.get("pos", "0")
            try:
                current_pos = float(current_pos_str) if current_pos_str else 0.0
            except (ValueError, TypeError):
                current_pos = 0.0
            
            # 如果没有持仓，检查是否全部平仓
            if current_pos == 0:
                # 检查是否有上一次持仓记录（可能从有持仓变为0，即全部平仓）
                with self.position_lock:
                    prev_state = self.position_states.get(pos_id)
                
                prev_pos = 0.0
                if prev_state:
                    prev_pos_str = prev_state.get("pos", "0")
                    try:
                        prev_pos = float(prev_pos_str) if prev_pos_str else 0.0
                    except (ValueError, TypeError):
                        prev_pos = 0.0
                    logger.debug(
                        f"检测到持仓为0，prev_state存在: posId={pos_id}, prev_pos={prev_pos}"
                    )
                else:
                    logger.warning(
                        f"检测到持仓为0，但prev_state不存在: posId={pos_id}, "
                        f"position_states中的keys: {list(self.position_states.keys())}"
                    )
                
                # 如果上一次有持仓，现在变为0，说明全部平仓
                if prev_pos > 0:
                    u_time_str = position_data.get("uTime", "")
                    try:
                        u_time = int(u_time_str) if u_time_str else 0
                    except (ValueError, TypeError):
                        u_time = 0
                    
                    # 去重检查
                    close_key = (pos_id, u_time)
                    if close_key in self.processed_closes:
                        logger.debug(
                            f"跳过重复的平仓事件: posId={pos_id}, uTime={u_time}"
                        )
                        return None
                    
                    # 记录已处理
                    with self.position_lock:
                        self.processed_closes[close_key] = time.time()
                    
                    # 返回全部平仓信息
                    # 【计算close_amount日志】okx_order_websocket_client.py:507 - 持仓WebSocket计算全部平仓数量
                    logger.info(
                        f"【计算close_amount】位置: okx_order_websocket_client.py:507 (_detect_position_change全部平仓) | "
                        f"pos_id: {pos_id} | prev_pos(合约): {prev_pos} | "
                        f"计算出的close_amount(合约): {prev_pos} | "
                        f"注意：这是合约数量，不是币数量！需要转换为币数量 | uTime: {u_time_str}"
                    )
                    return {
                        "pos_id": pos_id,
                        "inst_id": position_data.get("instId", ""),
                        "pos_side": position_data.get("posSide", ""),
                        "close_amount": prev_pos,  # 平仓数量等于上一次持仓数量
                        "close_price": None,  # 需要从position_history获取
                        "is_full_close": True,
                        "u_time": u_time_str,
                        "mark_px": position_data.get("markPx", "")
                    }
                
                # 如果prev_pos为0，但内存中有活跃持仓，也应该检查
                # 这可能是snapshot消息已经更新了状态为0，但event_update消息才到达的情况
                if prev_pos == 0 and self.trading_manager:
                    logger.info(
                        f"prev_pos为0，但检查内存中是否有活跃持仓: posId={pos_id}"
                    )
                    try:
                        if self.trading_manager.has_active_position():
                            cl_ord_id = self.trading_manager._find_cl_ord_id_by_pos_id(
                                pos_id=pos_id,
                                inst_id=position_data.get("instId", ""),
                                pos_side=position_data.get("posSide", "")
                            )
                            
                            if cl_ord_id:
                                logger.warning(
                                    f"检测到持仓为0，prev_pos也为0，但内存中有活跃持仓: "
                                    f"posId={pos_id}, cl_ord_id={cl_ord_id}, "
                                    f"可能是snapshot消息已更新状态，尝试处理全部平仓"
                                )
                                
                                u_time_str = position_data.get("uTime", "")
                                try:
                                    u_time = int(u_time_str) if u_time_str else 0
                                except (ValueError, TypeError):
                                    u_time = 0
                                
                                # 去重检查
                                close_key = (pos_id, u_time)
                                if close_key in self.processed_closes:
                                    logger.debug(
                                        f"跳过重复的平仓事件: posId={pos_id}, uTime={u_time}"
                                    )
                                    return None
                                
                                # 记录已处理
                                with self.position_lock:
                                    self.processed_closes[close_key] = time.time()
                                
                                # 返回全部平仓信息（close_amount设为0，让TradingManager从实际持仓获取）
                                return {
                                    "pos_id": pos_id,
                                    "inst_id": position_data.get("instId", ""),
                                    "pos_side": position_data.get("posSide", ""),
                                    "close_amount": 0.0,  # 设为0，让TradingManager从实际持仓获取
                                    "close_price": None,
                                    "is_full_close": True,
                                    "u_time": u_time_str,
                                    "mark_px": position_data.get("markPx", "")
                                }
                    except Exception as e:
                        logger.error(f"检查TradingManager活跃持仓失败（prev_pos=0）: {e}", exc_info=True)
                
                # 如果prev_state不存在，但内存中有活跃持仓，也应该检查
                # 这可能是WebSocket重连后状态丢失，或者部分平仓消息丢失的情况
                if not prev_state and self.trading_manager:
                    logger.info(
                        f"prev_state不存在，检查TradingManager是否有活跃持仓: posId={pos_id}"
                    )
                    try:
                        # 检查TradingManager是否有活跃持仓
                        has_active = self.trading_manager.has_active_position()
                        logger.info(
                            f"TradingManager.has_active_position()={has_active}, "
                            f"current_cl_ord_id={self.trading_manager.current_cl_ord_id}"
                        )
                        
                        if has_active:
                            # 尝试通过pos_id查找cl_ord_id
                            cl_ord_id = self.trading_manager._find_cl_ord_id_by_pos_id(
                                pos_id=pos_id,
                                inst_id=position_data.get("instId", ""),
                                pos_side=position_data.get("posSide", "")
                            )
                            
                            logger.info(
                                f"通过pos_id查找cl_ord_id结果: posId={pos_id}, cl_ord_id={cl_ord_id}"
                            )
                            
                            if cl_ord_id:
                                logger.warning(
                                    f"检测到持仓为0，但内存中有活跃持仓: posId={pos_id}, "
                                    f"cl_ord_id={cl_ord_id}, 可能是WebSocket状态丢失，尝试处理全部平仓"
                                )
                                
                                u_time_str = position_data.get("uTime", "")
                                try:
                                    u_time = int(u_time_str) if u_time_str else 0
                                except (ValueError, TypeError):
                                    u_time = 0
                                
                                # 去重检查
                                close_key = (pos_id, u_time)
                                if close_key in self.processed_closes:
                                    logger.debug(
                                        f"跳过重复的平仓事件: posId={pos_id}, uTime={u_time}"
                                    )
                                    return None
                                
                                # 记录已处理
                                with self.position_lock:
                                    self.processed_closes[close_key] = time.time()
                                
                                # 返回全部平仓信息（close_amount设为0，让TradingManager从实际持仓获取）
                                return {
                                    "pos_id": pos_id,
                                    "inst_id": position_data.get("instId", ""),
                                    "pos_side": position_data.get("posSide", ""),
                                    "close_amount": 0.0,  # 设为0，让TradingManager从实际持仓获取
                                    "close_price": None,
                                    "is_full_close": True,
                                    "u_time": u_time_str,
                                    "mark_px": position_data.get("markPx", "")
                                }
                            else:
                                logger.warning(
                                    f"检测到持仓为0，内存中有活跃持仓，但无法找到对应的cl_ord_id: "
                                    f"posId={pos_id}, current_cl_ord_id={self.trading_manager.current_cl_ord_id}"
                                )
                        else:
                            logger.debug(
                                f"检测到持仓为0，但TradingManager没有活跃持仓: posId={pos_id}"
                            )
                    except Exception as e:
                        logger.error(f"检查TradingManager活跃持仓失败: {e}", exc_info=True)
                
                logger.debug(
                    f"检测到持仓为0，但无法处理全部平仓: posId={pos_id}, "
                    f"prev_state存在={prev_state is not None}, prev_pos={prev_pos}"
                )
                return None
            
            # 如果有持仓，检查是否减少（部分平仓）
            with self.position_lock:
                prev_state = self.position_states.get(pos_id)
            
            if prev_state:
                prev_pos_str = prev_state.get("pos", "0")
                try:
                    prev_pos = float(prev_pos_str) if prev_pos_str else 0.0
                except (ValueError, TypeError):
                    prev_pos = 0.0
                
                # 如果持仓数量减少（且当前持仓>0），说明部分平仓
                if prev_pos > current_pos > 0:
                    close_amount = prev_pos - current_pos
                    # 【计算close_amount日志】okx_order_websocket_client.py:659 - 持仓WebSocket计算平仓数量
                    logger.info(
                        f"【计算close_amount】位置: okx_order_websocket_client.py:659 (_detect_position_change) | "
                        f"pos_id: {pos_id} | prev_pos(合约): {prev_pos} | current_pos(合约): {current_pos} | "
                        f"计算出的close_amount(合约): {close_amount} | "
                        f"注意：这是合约数量，不是币数量！需要转换为币数量"
                    )
                    u_time_str = position_data.get("uTime", "")
                    try:
                        u_time = int(u_time_str) if u_time_str else 0
                    except (ValueError, TypeError):
                        u_time = 0
                    
                    # 去重检查
                    close_key = (pos_id, u_time)
                    if close_key in self.processed_closes:
                        logger.debug(
                            f"跳过重复的部分平仓事件: posId={pos_id}, uTime={u_time}"
                        )
                        return None
                    
                    # 记录已处理
                    with self.position_lock:
                        self.processed_closes[close_key] = time.time()
                    
                    # 返回部分平仓信息
                    return {
                        "pos_id": pos_id,
                        "inst_id": position_data.get("instId", ""),
                        "pos_side": position_data.get("posSide", ""),
                        "close_amount": close_amount,
                        "close_price": None,  # 需要从position_history获取
                        "is_full_close": False,
                        "u_time": u_time_str,
                        "mark_px": position_data.get("markPx", "")
                    }
            
            return None
        
        except Exception as e:
            logger.error(f"检测持仓变化失败: {e}", exc_info=True)
            return None
    
    def _cleanup_processed_closes(self):
        """清理过期的去重记录"""
        try:
            current_time = time.time()
            expire_time = 30 * 60  # 30分钟（processed_closes）
            queue_expire_time = 5 * 60  # 5分钟（queued_closes）
            
            with self.position_lock:
                # 清理processed_closes（已处理的记录）
                keys_to_delete = [
                    key for key, process_time in self.processed_closes.items()
                    if current_time - process_time > expire_time
                ]
                for key in keys_to_delete:
                    del self.processed_closes[key]
                
                # 清理queued_closes（队列中的记录）
                queue_keys_to_delete = [
                    key for key, queue_time in self.queued_closes.items()
                    if current_time - queue_time > queue_expire_time
                ]
                for key in queue_keys_to_delete:
                    del self.queued_closes[key]
                
                if keys_to_delete or queue_keys_to_delete:
                    logger.debug(
                        f"清理了 {len(keys_to_delete)} 条过期的处理记录，"
                        f"{len(queue_keys_to_delete)} 条过期的队列记录"
                    )
        except Exception as e:
            logger.error(f"清理去重记录失败: {e}", exc_info=True)
    
    def _handle_detected_close(self, close_info: Dict[str, Any]):
        """
        将检测到的平仓事件放入队列（异步处理，不阻塞WebSocket消息）
        
        Args:
            close_info: 平仓信息字典（来自 _detect_position_change）
        """
        try:
            pos_id = close_info.get("pos_id")
            inst_id = close_info.get("inst_id")
            close_amount = close_info.get("close_amount", 0.0)
            is_full_close = close_info.get("is_full_close", False)
            u_time = close_info.get("u_time", "")
            
            # 检查是否已在队列中（去重）
            try:
                u_time_int = int(u_time) if u_time else 0
            except (ValueError, TypeError):
                u_time_int = 0
            
            close_key = (pos_id, u_time_int)
            
            with self.position_lock:
                # 如果已在队列中，跳过
                if close_key in self.queued_closes:
                    logger.debug(
                        f"平仓事件已在队列中，跳过: posId={pos_id}, uTime={u_time}"
                    )
                    return
                
                # 如果已处理过（processed_closes），也跳过
                if close_key in self.processed_closes:
                    logger.debug(
                        f"平仓事件已处理过，跳过: posId={pos_id}, uTime={u_time}"
                    )
                    return
            
            logger.info(
                f"检测到外部平仓，加入处理队列: posId={pos_id}, instId={inst_id}, "
                f"平仓数量={close_amount}, 全部平仓={is_full_close}, uTime={u_time}"
            )
            
            # 将事件放入队列（非阻塞，如果队列满则记录警告）
            queued = False
            try:
                self.close_event_queue.put(close_info, block=False)
                queued = True
                
                # 记录到队列去重集合（只有成功入队才记录）
                with self.position_lock:
                    self.queued_closes[close_key] = time.time()
                
                logger.debug(f"平仓事件已加入队列，当前队列大小: {self.close_event_queue.qsize()}")
            except queue.Full:
                logger.error(f"平仓事件队列已满，无法加入: posId={pos_id}")
            except Exception as e:
                # 如果入队后添加 queued_closes 时出错，需要从队列中移除（如果已入队）
                if queued:
                    try:
                        # 尝试移除（但队列不支持直接移除，只能记录错误）
                        logger.error(f"平仓事件入队后记录失败，可能导致重复处理: posId={pos_id}, 错误: {e}")
                    except:
                        pass
        
        except Exception as e:
            logger.error(f"将平仓事件加入队列失败: {e}", exc_info=True)
    
    def _start_heartbeat(self):
        """
        启动心跳检查
        根据OKX建议：
        1. 每次接收到消息后，设置定时器N秒（N < 30）
        2. 如果N秒内没有收到新消息，发送'ping'
        3. 期待'pong'作为回应，如果N秒内未收到，重新连接
        """
        if not self.running:
            return
        
        current_time = time.time()
        heartbeat_interval = settings.WS_HEARTBEAT_INTERVAL  # 默认20秒，小于30秒
        ping_timeout = settings.WS_PING_TIMEOUT  # 默认5秒
        
        # 检查是否在等待pong响应
        if self.pending_pong:
            # 如果发送ping后，在ping_timeout秒内未收到pong，则重连
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
                    # 发送失败，准备重连
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
        
        logger.info(f"将在 {reconnect_interval} 秒后重连持仓WebSocket（第 {self.reconnect_count} 次）")
        
        self.reconnect_timer = threading.Timer(reconnect_interval, self._reconnect)
        self.reconnect_timer.start()
    
    def _reconnect(self):
        """执行重连"""
        self.reconnect_timer = None
        
        if not self.running:
            return
        
        logger.info("开始重连持仓WebSocket...")
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
        logger.error(f"持仓WebSocket错误: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """连接关闭回调"""
        logger.warning(f"持仓WebSocket连接已关闭: code={close_status_code}, msg={close_msg}")
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        
        if self.running:
            self._schedule_reconnect()
    
    def get_position_messages(self) -> List[Dict[str, Any]]:
        """获取所有收到的持仓消息（用于测试）"""
        with self.position_lock:
            return self.position_messages.copy()
    
    def clear_messages(self):
        """清空消息记录"""
        with self.position_lock:
            self.position_messages.clear()
            logger.info("已清空持仓消息记录")
    
    def _start_close_processor(self):
        """启动平仓事件处理线程"""
        if self.close_processor_thread and self.close_processor_thread.is_alive():
            return
        
        self.close_processor_thread = threading.Thread(
            target=self._close_processor_loop,
            name="CloseEventProcessor",
            daemon=True
        )
        self.close_processor_thread.start()
        logger.debug("平仓事件处理线程已启动")
    
    def _stop_close_processor(self):
        """停止平仓事件处理线程"""
        # 放入停止标记
        try:
            self.close_event_queue.put(None, timeout=1)
        except queue.Full:
            pass
        
        # 等待线程结束
        if self.close_processor_thread and self.close_processor_thread.is_alive():
            self.close_processor_thread.join(timeout=3)
            logger.debug("平仓事件处理线程已停止")
    
    def _start_position_processor(self):
        """启动持仓数据处理线程"""
        if self.position_processor_thread and self.position_processor_thread.is_alive():
            return
        
        self.position_processor_thread = threading.Thread(
            target=self._position_processor_loop,
            name="PositionDataProcessor",
            daemon=True
        )
        self.position_processor_thread.start()
        logger.debug("持仓数据处理线程已启动")
    
    def _stop_position_processor(self):
        """停止持仓数据处理线程"""
        # 放入停止标记
        try:
            self.position_data_queue.put(None, timeout=1)
        except queue.Full:
            pass
        
        # 等待线程结束
        if self.position_processor_thread and self.position_processor_thread.is_alive():
            self.position_processor_thread.join(timeout=3)
            logger.debug("持仓数据处理线程已停止")
    
    def _close_processor_loop(self):
        """平仓事件处理循环（后台线程）"""
        logger.debug("平仓事件处理循环已启动")
        
        while self.running:
            try:
                # 从队列获取事件（阻塞等待，最多1秒）
                try:
                    close_info = self.close_event_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 如果收到None，表示停止信号
                if close_info is None:
                    break
                
                # 处理平仓事件
                self._process_close_event(close_info)
                
                # 处理完成后，从队列去重集合中移除
                pos_id = close_info.get("pos_id", "")
                u_time = close_info.get("u_time", "")
                try:
                    u_time_int = int(u_time) if u_time else 0
                except (ValueError, TypeError):
                    u_time_int = 0
                
                close_key = (pos_id, u_time_int)
                with self.position_lock:
                    if close_key in self.queued_closes:
                        del self.queued_closes[close_key]
                
            except Exception as e:
                logger.error(f"平仓事件处理循环异常: {e}", exc_info=True)
        
        logger.debug("平仓事件处理循环已退出")
    
    def _position_processor_loop(self):
        """持仓数据处理循环（后台线程）"""
        logger.debug("持仓数据处理循环已启动")
        
        while self.running:
            try:
                # 从队列获取数据（阻塞等待，最多1秒）
                try:
                    item = self.position_data_queue.get(timeout=1)
                except queue.Empty:
                    continue
                
                # 如果收到None，表示停止信号
                if item is None:
                    break
                
                # 处理持仓数据
                position_data = item.get("position_data")
                event_type = item.get("event_type", "event_update")
                
                if position_data:
                    self._process_position(position_data, event_type)
                
            except Exception as e:
                logger.error(f"持仓数据处理循环异常: {e}", exc_info=True)
        
        logger.debug("持仓数据处理循环已退出")
    
    def _process_close_event(self, close_info: Dict[str, Any]):
        """
        处理平仓事件（在后台线程中执行）
        
        Args:
            close_info: 平仓信息字典
        """
        try:
            pos_id = close_info.get("pos_id")
            inst_id = close_info.get("inst_id")
            pos_side = close_info.get("pos_side")
            close_amount = close_info.get("close_amount", 0.0)
            is_full_close = close_info.get("is_full_close", False)
            u_time = close_info.get("u_time", "")
            
            logger.info(
                f"开始处理外部平仓: posId={pos_id}, instId={inst_id}, "
                f"posSide={pos_side}, 平仓数量={close_amount}, "
                f"全部平仓={is_full_close}, uTime={u_time}"
            )
            
            # 如果没有注入TradingManager，只记录日志
            if not self.trading_manager:
                logger.warning(
                    f"TradingManager未注入，无法处理外部平仓: posId={pos_id}"
                )
                return
            
            # 调用TradingManager查找cl_ord_id
            try:
                cl_ord_id = self.trading_manager._find_cl_ord_id_by_pos_id(
                    pos_id=pos_id,
                    inst_id=inst_id,
                    pos_side=pos_side
                )
                
                if not cl_ord_id:
                    logger.warning(
                        f"无法找到cl_ord_id: posId={pos_id}, instId={inst_id}, "
                        f"posSide={pos_side}, uTime={u_time}"
                    )
                    return
                
                logger.info(
                    f"找到cl_ord_id: {cl_ord_id}, 开始处理外部平仓"
                )
                
                # 如果close_amount为0，说明是全部平仓但无法从prev_state获取数量
                # 尝试从内存中的current_position_amount获取
                actual_close_amount = close_amount
                if actual_close_amount == 0.0 and is_full_close:
                    if self.trading_manager.current_position_amount is not None:
                        actual_close_amount = self.trading_manager.current_position_amount
                        logger.info(
                            f"close_amount为0，从内存获取持仓数量: {actual_close_amount}"
                        )
                    else:
                        # 如果内存中也没有，尝试从OKX API查询（虽然可能已经为0）
                        try:
                            symbol = inst_id.replace("-USDT-SWAP", "").replace("-USDT", "")
                            position_info = self.trading_manager._get_current_position_from_okx(symbol)
                            # 如果查询失败或持仓为0，使用一个很小的值作为标记
                            # 因为handle_external_close_position需要close_amount > 0
                            if position_info and position_info.get('pos', 0) > 0:
                                actual_close_amount = abs(position_info.get('pos', 0))
                            else:
                                # 如果查询不到，使用一个很小的值（0.0001），让系统知道是全部平仓
                                actual_close_amount = 0.0001
                                logger.warning(
                                    f"无法获取实际持仓数量，使用默认值: {actual_close_amount}"
                                )
                        except Exception as e:
                            logger.error(f"查询实际持仓失败: {e}", exc_info=True)
                            # 使用一个很小的值
                            actual_close_amount = 0.0001
                
                # 调用TradingManager处理外部平仓
                success = self.trading_manager.handle_external_close_position(
                    pos_id=pos_id,
                    cl_ord_id=cl_ord_id,
                    close_amount=actual_close_amount,
                    close_price=None,  # 需要从position_history获取
                    is_full_close=is_full_close,
                    inst_id=inst_id,
                    pos_side=pos_side,
                    u_time=u_time  # 传递u_time用于精确去重
                )
                
                if success:
                    logger.info(
                        f"外部平仓处理成功: posId={pos_id}, cl_ord_id={cl_ord_id}, "
                        f"平仓数量={close_amount}"
                    )
                else:
                    logger.error(
                        f"外部平仓处理失败: posId={pos_id}, cl_ord_id={cl_ord_id}"
                    )
            
            except Exception as e:
                logger.error(
                    f"处理外部平仓时发生错误: {e}", exc_info=True
                )
        
        except Exception as e:
            logger.error(f"处理平仓事件失败: {e}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        with self.position_lock:
            return {
                "running": self.running,
                "connected": self.connected,
                "logged_in": self.logged_in,
                "subscribed": self.subscribed,
                "reconnect_count": self.reconnect_count,
                "message_count": len(self.position_messages),
                "close_queue_size": self.close_event_queue.qsize()
            }

