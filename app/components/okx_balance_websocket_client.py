"""
OKX WebSocket私有频道客户端 - 用于实时账户余额监控
"""
import json
import time
import threading
import hmac
import base64
from typing import Optional, Dict, Any
import websocket
from app.config import settings
from app.utils.logger import logger


class OKXBalanceWebSocketClient:
    """OKX WebSocket私有频道客户端 - 实时账户余额"""
    
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
        
        # 余额数据
        self.latest_balance: Optional[Dict[str, Any]] = None
        self.balance_lock = threading.Lock()
        
        # 心跳管理
        self.last_message_time = 0
        self.last_ping_time = 0
        self.pending_pong = False  # 是否在等待pong响应
        self.heartbeat_timer: Optional[threading.Timer] = None
        
        # 余额输出定时器
        self.balance_log_timer: Optional[threading.Timer] = None
        
        # 重连管理
        self.reconnect_timer: Optional[threading.Timer] = None
        self.reconnect_count = 0
        
        # API凭证
        self.api_key = settings.EXCHANGE_API_KEY
        self.secret = settings.EXCHANGE_SECRET
        self.passphrase = settings.EXCHANGE_PASSPHRASE
    
    def start(self):
        """启动WebSocket连接"""
        if self.running:
            return
        
        self.running = True
        self._connect()
        logger.info("账户余额WebSocket客户端已启动")
    
    def stop(self):
        """停止WebSocket连接"""
        self.running = False
        
        # 取消定时器
        if self.heartbeat_timer:
            self.heartbeat_timer.cancel()
        if self.balance_log_timer:
            self.balance_log_timer.cancel()
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        
        # 关闭连接
        if self.ws:
            self.ws.close()
        
        # 等待线程结束
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=3)
        
        logger.info("账户余额WebSocket客户端已停止")
    
    def _connect(self):
        """建立WebSocket连接"""
        if not self.running:
            return
        
        try:
            logger.info(f"正在连接账户余额WebSocket: {self.ws_url}")
            
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
            logger.error(f"账户余额WebSocket连接失败: {e}", exc_info=True)
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
                # 使用certifi提供的CA证书包
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
            logger.error(f"账户余额WebSocket运行异常: {e}", exc_info=True)
            self._schedule_reconnect()
    
    def _on_open(self, ws):
        """连接打开回调"""
        logger.info("账户余额WebSocket连接已建立")
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
    
    def _subscribe_balance(self):
        """订阅账户余额频道"""
        subscribe_msg = {
            "op": "subscribe",
            "args": [{
                "channel": "account"
            }]
        }
        
        try:
            self.ws.send(json.dumps(subscribe_msg))
            logger.info("已发送账户余额订阅请求")
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
            
            # 处理登录响应
            if isinstance(data, dict) and "event" in data:
                if data["event"] == "login":
                    if data.get("code") == "0":
                        logger.info("登录成功")
                        self.logged_in = True
                        # 登录成功后订阅账户余额
                        self._subscribe_balance()
                    else:
                        logger.error(f"登录失败: {data}")
                elif data["event"] == "subscribe":
                    logger.info(f"订阅成功: {data}")
                    self.subscribed = True
                    # 订阅成功后启动余额日志输出
                    self._start_balance_log()
                elif data["event"] == "error":
                    logger.error(f"订阅失败: {data}")
                elif data["event"] == "pong":
                    # JSON格式的pong响应（备用处理）
                    logger.debug("收到pong响应（JSON格式）")
                    self.pending_pong = False  # 收到pong，清除等待状态
                    self.last_message_time = time.time()  # 更新最后消息时间
                return
            
            # 处理账户余额数据
            # OKX账户余额数据格式: {"arg": {"channel": "account"}, "data": [...]}
            if isinstance(data, dict) and "data" in data:
                if isinstance(data["data"], list) and len(data["data"]) > 0:
                    self._process_balance(data["data"][0])
        
        except Exception as e:
            logger.error(f"处理账户余额WebSocket消息失败: {e}", exc_info=True)
            logger.error(f"原始消息: {message}")
    
    def _process_balance(self, balance_data: Dict[str, Any]):
        """处理账户余额数据"""
        try:
            with self.balance_lock:
                # 提取总权益（处理空字符串）
                total_eq_str = balance_data.get("totalEq", "0")
                total_eq = float(total_eq_str) if total_eq_str and total_eq_str != "" else 0.0
                
                # 提取可用余额（处理空字符串）
                avail_eq_str = balance_data.get("availEq", "0")
                avail_eq = float(avail_eq_str) if avail_eq_str and avail_eq_str != "" else 0.0
                
                # 提取冻结余额（处理空字符串）
                frozen_bal_str = balance_data.get("frozenBal", "0")
                frozen_bal = float(frozen_bal_str) if frozen_bal_str and frozen_bal_str != "" else 0.0
                
                # 提取币种余额详情
                details = balance_data.get("details", [])
                
                self.latest_balance = {
                    "total_eq": total_eq,
                    "avail_eq": avail_eq,
                    "frozen_bal": frozen_bal,
                    "details": details,
                    "update_time": time.time()
                }
        except Exception as e:
            logger.error(f"处理账户余额数据失败: {e}", exc_info=True)
            logger.error(f"余额数据: {balance_data}")
    
    def _start_balance_log(self):
        """启动余额日志输出（每秒输出一次）"""
        if not self.running:
            return
        
        self._log_balance()
        
        # 每秒输出一次
        self.balance_log_timer = threading.Timer(1.0, self._start_balance_log)
        self.balance_log_timer.start()
    
    def _log_balance(self):
        """输出余额到日志"""
        with self.balance_lock:
            if self.latest_balance:
                total_eq = self.latest_balance.get("total_eq", 0)
                avail_eq = self.latest_balance.get("avail_eq", 0)
                frozen_bal = self.latest_balance.get("frozen_bal", 0)
                
                logger.info(
                    f"账户余额 - 总权益: {total_eq:.2f} USDT, "
                    f"可用余额: {avail_eq:.2f} USDT, "
                    f"冻结余额: {frozen_bal:.2f} USDT"
                )
    
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
                        # OKX私有频道使用字符串'ping'（根据OKX建议）
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
        
        logger.info(f"将在 {reconnect_interval} 秒后重连账户余额WebSocket（第 {self.reconnect_count} 次）")
        
        self.reconnect_timer = threading.Timer(reconnect_interval, self._reconnect)
        self.reconnect_timer.start()
    
    def _reconnect(self):
        """执行重连"""
        self.reconnect_timer = None
        
        if not self.running:
            return
        
        logger.info("开始重连账户余额WebSocket...")
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
        logger.error(f"账户余额WebSocket错误: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """连接关闭回调"""
        logger.warning(f"账户余额WebSocket连接已关闭: code={close_status_code}, msg={close_msg}")
        self.connected = False
        self.logged_in = False
        self.subscribed = False
        
        if self.running:
            self._schedule_reconnect()
    
    def get_latest_balance(self) -> Optional[Dict[str, Any]]:
        """获取最新余额"""
        with self.balance_lock:
            if self.latest_balance:
                return self.latest_balance.copy()
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        return {
            "running": self.running,
            "connected": self.connected,
            "logged_in": self.logged_in,
            "subscribed": self.subscribed,
            "reconnect_count": self.reconnect_count,
            "has_balance": self.latest_balance is not None
        }

