# WebSocket架构文档

## 一、概述

### 1.1 WebSocket模块职责

WebSocket模块负责与OKX交易所建立实时连接，接收订单和持仓的实时更新。

**主要职责**：
- 建立和维护WebSocket连接
- 接收实时订单状态更新
- 接收实时持仓状态更新
- 检测外部平仓事件（手动平仓、爆仓等）
- 自动重连和心跳保活
- 消息去重和异步处理

**设计特点**：
- **实时性**：通过WebSocket实时接收数据，无需轮询
- **可靠性**：自动重连、心跳保活、消息去重
- **异步处理**：使用队列和后台线程，避免阻塞WebSocket消息接收
- **状态追踪**：追踪持仓状态变化，检测外部平仓

### 1.2 核心组件

**OKXOrderWebSocketClient**：
- 持仓频道WebSocket客户端
- 订阅持仓频道，接收持仓实时更新
- 检测持仓变化，识别外部平仓事件
- 与TradingManager集成，处理外部平仓

**OKXOrdersWebSocketClient**：
- 订单频道WebSocket客户端
- 订阅订单频道，接收订单实时更新
- 同步订单状态到order_history表
- 与OrderHistorySyncManager协调

**OKXWebSocketClient**：
- 公共频道WebSocket客户端
- 订阅价格频道，获取实时价格
- 用于挂单监控服务

### 1.3 设计理念

**可靠性优先**：
- 自动重连机制
- 心跳保活机制
- 消息去重机制
- 错误恢复机制

**性能优化**：
- 异步处理，避免阻塞
- 队列大小限制，防止内存溢出
- 定期清理过期记录

**状态一致性**：
- 追踪持仓状态变化
- 检测外部平仓事件
- 与TradingManager状态同步

## 二、OKXOrderWebSocketClient 设计

### 2.1 类结构

**核心属性**：
- `ws_url`：WebSocket连接URL（私有频道）
- `ws`：WebSocketApp实例
- `ws_thread`：WebSocket运行线程
- `connected`：连接状态
- `logged_in`：登录状态
- `subscribed`：订阅状态
- `running`：运行状态

**状态管理**：
- `position_states`：持仓状态字典（key: posId, value: 持仓数据）
- `position_messages`：收到的持仓消息列表（用于测试）
- `processed_closes`：已处理的平仓事件（去重）

**队列管理**：
- `close_event_queue`：平仓事件队列（maxsize=100）
- `position_data_queue`：持仓数据队列（maxsize=200）
- `queued_closes`：队列去重集合

**线程管理**：
- `close_processor_thread`：平仓事件处理线程
- `position_processor_thread`：持仓数据处理线程
- `heartbeat_timer`：心跳定时器
- `reconnect_timer`：重连定时器

**API凭证**：
- `api_key`：API密钥
- `secret`：密钥
- `passphrase`：密码短语

**依赖注入**：
- `trading_manager`：TradingManager实例（用于处理外部平仓）

### 2.2 初始化流程

1. **设置WebSocket URL**：从配置读取`WS_PRIVATE_URL`
2. **初始化状态变量**：connected、logged_in、subscribed、running设为False
3. **初始化队列**：创建平仓事件队列和持仓数据队列
4. **初始化去重集合**：创建processed_closes和queued_closes
5. **读取API凭证**：从配置读取API密钥、密钥、密码短语
6. **注入依赖**：接收TradingManager实例（可选）

### 2.3 依赖注入

**TradingManager注入**：
- 通过构造函数注入（可选）
- 用于处理外部平仓事件
- 如果未注入，只记录日志，不处理平仓

**初始化代码**：
```python
def __init__(self, trading_manager=None):
    self.trading_manager = trading_manager
    # ... 其他初始化
```

## 三、连接管理

### 3.1 WebSocket连接建立

**3.1.1 连接URL选择**：
- **私有频道URL**：`WS_PRIVATE_URL`（用于持仓和订单频道）
- **公共频道URL**：`WS_URL`（用于价格频道）
- **环境切换**：根据`EXCHANGE_SANDBOX`配置选择沙箱或生产环境

**3.1.2 连接建立流程**：
```
1. 调用start()方法
   ↓
2. 设置running=True
   ↓
3. 启动后台处理线程（平仓事件处理、持仓数据处理）
   ↓
4. 调用_connect()建立连接
   ↓
5. 创建WebSocketApp实例
   ↓
6. 在新线程中运行WebSocket（_run_websocket）
   ↓
7. 连接成功后触发_on_open回调
```

**SSL配置**：
- `WS_SSL_VERIFY`：是否验证SSL证书
- `WS_SSL_CERT_PATH`：SSL证书路径
- 支持使用certifi证书或系统默认证书

### 3.2 登录认证

**3.2.1 API密钥签名**：
- **时间戳**：当前Unix时间戳（秒）
- **消息**：`timestamp + "GET" + "/users/self/verify"`
- **签名算法**：HMAC-SHA256
- **签名编码**：Base64编码

**签名代码**：
```python
timestamp = str(int(time.time()))
message = timestamp + "GET" + "/users/self/verify"
mac = hmac.new(
    bytes(secret, encoding='utf8'),
    bytes(message, encoding='utf-8'),
    digestmod='sha256'
)
sign = base64.b64encode(mac.digest()).decode()
```

**3.2.2 登录消息格式**：
```json
{
    "op": "login",
    "args": [
        {
            "apiKey": "your_api_key",
            "passphrase": "your_passphrase",
            "timestamp": "1234567890",
            "sign": "base64_encoded_signature"
        }
    ]
}
```

**3.2.3 认证响应处理**：
- **成功响应**：`{"event": "login", "code": "0"}`
  - 设置`logged_in = True`
  - 自动订阅持仓频道
- **失败响应**：`{"event": "login", "code": "错误码"}`
  - 记录错误日志
  - 不设置logged_in，等待重连

### 3.3 频道订阅

**3.3.1 订阅消息格式**：
```json
{
    "op": "subscribe",
    "args": [
        {
            "channel": "positions",
            "instType": "SWAP"
        }
    ]
}
```

**订阅频道**：
- **持仓频道**：`positions`（instType: SWAP）
- **订单频道**：`orders`（instType: SWAP）

**3.3.2 订阅确认**：
- **成功响应**：`{"event": "subscribe", "code": "0"}`
  - 设置`subscribed = True`
- **失败响应**：`{"event": "error", "code": "错误码"}`
  - 记录错误日志
  - 不设置subscribed，等待重连后重新订阅

**3.3.3 订阅频道列表**：
- **持仓频道**：`positions`（用于OKXOrderWebSocketClient）
- **订单频道**：`orders`（用于OKXOrdersWebSocketClient）
- **价格频道**：`tickers`（用于OKXWebSocketClient）

## 四、消息接收和处理

### 4.1 消息接收机制

**4.1.1 WebSocket消息回调**：
- **回调函数**：`_on_message(ws, message)`
- **触发时机**：每次收到WebSocket消息时触发
- **处理方式**：立即处理心跳响应，其他消息放入队列异步处理

**消息类型**：
- **心跳响应**：字符串`'pong'`（非JSON）
- **JSON消息**：登录响应、订阅响应、数据消息

**4.1.2 消息解析**：
- **心跳响应**：直接处理，不解析JSON
- **JSON消息**：使用`json.loads()`解析
- **解析失败**：记录警告日志，忽略消息

### 4.2 持仓消息处理

**4.2.1 持仓数据结构**：
```json
{
    "arg": {
        "channel": "positions",
        "instType": "SWAP"
    },
    "eventType": "snapshot" | "event_update",
    "data": [
        {
            "posId": "123456",
            "instId": "ETH-USDT-SWAP",
            "posSide": "long" | "short",
            "pos": "1.0",
            "availPos": "1.0",
            "avgPx": "3000.0",
            "upl": "100.0",
            "uplRatio": "0.01",
            "lever": "10",
            "margin": "300.0",
            "mgnMode": "cross",
            "uTime": "1234567890123",
            "markPx": "3100.0"
        }
    ]
}
```

**关键字段**：
- `posId`：持仓ID
- `instId`：交易对ID
- `posSide`：持仓方向（long/short）
- `pos`：持仓数量（合约张数）
- `availPos`：可用持仓数量
- `avgPx`：平均开仓价格
- `uTime`：更新时间（毫秒时间戳）
- `markPx`：标记价格

**4.2.2 持仓变化检测**：
- **检测时机**：收到`event_update`消息时
- **检测逻辑**：
  1. 获取上一次持仓状态（从`position_states`字典）
  2. 比较当前持仓数量和上一次持仓数量
  3. 如果数量减少或变为0，检测为平仓事件
- **检测方法**：`_detect_position_change()`

**检测场景**：
- **全部平仓**：持仓数量从 >0 变为 0
- **部分平仓**：持仓数量减少（且当前持仓 >0）
- **snapshot处理**：如果snapshot时持仓为0，也检测（可能是重连后收到的最新状态）

**4.2.3 外部平仓检测**：
- **检测流程**：
  ```
  收到持仓消息
      ↓
  解析持仓数据
      ↓
  检测持仓变化（_detect_position_change）
      ↓
  如果检测到平仓，创建平仓事件
      ↓
  放入平仓事件队列（_handle_detected_close）
      ↓
  后台线程处理（_process_close_event）
      ↓
  调用TradingManager处理外部平仓
  ```

**平仓事件信息**：
```python
{
    "pos_id": str,  # 持仓ID
    "inst_id": str,  # 交易对ID
    "pos_side": str,  # 持仓方向
    "close_amount": float,  # 平仓数量（合约张数）
    "close_price": Optional[float],  # 平仓价格
    "is_full_close": bool,  # 是否全部平仓
    "u_time": str,  # 更新时间
    "mark_px": str  # 标记价格
}
```

**去重机制**：
- **去重键**：`(pos_id, u_time)`
- **去重集合**：`processed_closes`（已处理）、`queued_closes`（队列中）
- **过期时间**：30分钟（processed_closes）、5分钟（queued_closes）

### 4.3 订单消息处理

**4.3.1 订单数据结构**：
```json
{
    "arg": {
        "channel": "orders",
        "instType": "SWAP"
    },
    "data": [
        {
            "ordId": "123456",
            "clOrdId": "client_order_id",
            "instId": "ETH-USDT-SWAP",
            "side": "buy" | "sell",
            "posSide": "long" | "short",
            "state": "filled" | "partially_filled" | "canceled",
            "accFillSz": "1.0",
            "fillTime": "1234567890123",
            "uTime": "1234567890123"
        }
    ]
}
```

**关键字段**：
- `ordId`：订单ID（OKX）
- `clOrdId`：客户端订单ID
- `instId`：交易对ID
- `side`：买卖方向（buy/sell）
- `posSide`：持仓方向（long/short）
- `state`：订单状态
- `accFillSz`：累计成交数量
- `fillTime`：成交时间

**4.3.2 订单状态更新**：
- **更新方式**：通过`OKXOrdersWebSocketClient`接收订单消息
- **存储位置**：`order_history`表
- **更新时机**：收到订单状态变化消息时
- **去重机制**：通过`(ord_id, u_time)`组合去重

**4.3.3 订单回调触发**：
- **回调时机**：订单状态变化时（filled、partially_filled、canceled）
- **回调方式**：通过WebSocket消息实时触发
- **处理方式**：异步处理，写入数据库

## 五、异步处理机制

### 5.1 平仓事件队列

**5.1.1 队列设计**：
- **队列类型**：`queue.Queue`（线程安全）
- **队列大小**：`maxsize=100`（防止内存无限增长）
- **队列用途**：存储检测到的外部平仓事件
- **入队时机**：检测到持仓变化（平仓）时

**5.1.2 队列大小限制**：
- **限制原因**：防止内存无限增长
- **满队列处理**：如果队列满，记录错误日志，丢弃消息
- **监控**：记录队列大小，便于监控

**5.1.3 事件入队逻辑**：
- **去重检查**：入队前检查是否已在队列中或已处理过
- **去重键**：`(pos_id, u_time)`
- **入队方式**：`put_nowait()`（非阻塞，如果队列满则丢弃）

### 5.2 持仓数据队列

**5.2.1 队列设计**：
- **队列类型**：`queue.Queue`（线程安全）
- **队列大小**：`maxsize=200`（比平仓事件队列大，因为持仓消息更频繁）
- **队列用途**：存储收到的持仓数据消息
- **入队时机**：收到持仓消息时

**5.2.2 数据处理逻辑**：
- **处理方式**：后台线程从队列取出数据，调用`_process_position()`处理
- **处理内容**：
  1. 解析持仓数据
  2. 检测持仓变化
  3. 更新持仓状态
  4. 如果检测到平仓，放入平仓事件队列

### 5.3 异步处理线程

**5.3.1 线程启动**：
- **启动时机**：`start()`方法调用时
- **线程类型**：守护线程（`daemon=True`）
- **线程数量**：
  - 平仓事件处理线程：1个
  - 持仓数据处理线程：1个
  - 订单处理线程：1个（OKXOrdersWebSocketClient）

**5.3.2 线程停止**：
- **停止方式**：向队列放入`None`作为停止标记
- **等待时间**：最多等待3秒
- **停止时机**：`stop()`方法调用时

**5.3.3 线程安全**：
- **锁机制**：使用`threading.Lock()`保护共享数据
- **保护对象**：
  - `position_states`：持仓状态字典
  - `processed_closes`：已处理的平仓事件
  - `queued_closes`：队列去重集合

## 六、去重机制

### 6.1 持仓消息去重

**6.1.1 去重键（pos_id, u_time）**：
- **去重键组成**：`(pos_id, u_time)`
- **唯一性保证**：同一个持仓的同一时间更新只处理一次
- **使用场景**：平仓事件去重

**6.1.2 去重记录管理**：
- **存储位置**：`processed_closes`字典
- **键格式**：`(pos_id, u_time)`
- **值格式**：处理时间戳（用于过期清理）
- **记录时机**：处理完平仓事件后记录

**6.1.3 过期清理**：
- **清理时机**：检测持仓变化时自动清理
- **过期时间**：30分钟
- **清理方法**：`_cleanup_processed_closes()`
- **清理对象**：
  - `processed_closes`：30分钟过期
  - `queued_closes`：5分钟过期

### 6.2 订单消息去重

**6.2.1 去重键（订单ID）**：
- **去重键组成**：`(ord_id, u_time)`
- **唯一性保证**：同一个订单的同一时间更新只处理一次
- **使用场景**：订单状态更新去重

**6.2.2 去重记录管理**：
- **存储位置**：`processed_orders`字典（OKXOrdersWebSocketClient）
- **键格式**：`(ord_id, u_time)`
- **值格式**：处理时间戳
- **过期时间**：1小时（定期清理）

### 6.3 队列去重

**6.3.1 队列去重键**：
- **平仓事件队列**：`(pos_id, u_time)`
- **订单队列**：`(ord_id, u_time)`
- **用途**：避免重复入队

**6.3.2 快速检查机制**：
- **检查集合**：`queued_closes`、`queued_orders`
- **检查时机**：入队前检查
- **检查方式**：快速字典查找，避免遍历队列

## 七、心跳机制

### 7.1 心跳设计

**7.1.1 心跳间隔（20秒）**：
- **配置项**：`WS_HEARTBEAT_INTERVAL`（默认20秒）
- **设计原则**：小于30秒（OKX要求）
- **检查频率**：每秒检查一次（通过定时器）

**7.1.2 ping发送逻辑**：
- **发送条件**：如果`heartbeat_interval`秒内没有收到任何消息
- **发送内容**：字符串`'ping'`（非JSON）
- **发送后**：设置`pending_pong = True`，记录`last_ping_time`

**7.1.3 pong接收处理**：
- **接收格式**：字符串`'pong'`（非JSON）或JSON格式`{"event": "pong"}`
- **处理方式**：设置`pending_pong = False`，更新`last_message_time`
- **超时处理**：如果发送ping后5秒内未收到pong，触发重连

### 7.2 心跳超时

**7.2.1 ping超时时间（5秒）**：
- **配置项**：`WS_PING_TIMEOUT`（默认5秒）
- **超时检测**：如果`pending_pong = True`且距离`last_ping_time`超过5秒
- **超时处理**：关闭连接，触发重连

**7.2.2 超时处理**：
- **处理方式**：关闭WebSocket连接
- **触发重连**：自动触发重连机制
- **日志记录**：记录警告日志

### 7.3 心跳定时器

**7.3.1 定时器管理**：
- **定时器类型**：`threading.Timer`
- **定时器间隔**：1秒（每秒检查一次）
- **定时器启动**：连接建立后启动
- **定时器停止**：连接关闭时取消

**7.3.2 定时器重置**：
- **重置时机**：每次收到消息时更新`last_message_time`
- **重置方式**：不需要重置定时器，只需更新时间戳
- **定时器循环**：每次检查后重新创建定时器（1秒后再次检查）

## 八、重连机制

### 8.1 连接断开检测

**8.1.1 断开原因分析**：
- **正常断开**：主动调用`stop()`方法
- **异常断开**：网络异常、服务器关闭、心跳超时
- **检测方式**：`_on_close()`回调触发

**8.1.2 断开事件处理**：
- **状态重置**：`connected = False`、`logged_in = False`、`subscribed = False`
- **定时器清理**：取消心跳定时器和重连定时器
- **重连触发**：如果`running = True`，自动触发重连

### 8.2 自动重连

**8.2.1 重连间隔（5秒）**：
- **配置项**：`WS_RECONNECT_INTERVAL`（默认5秒）
- **重连方式**：使用定时器延迟重连
- **重连次数**：无限制（只要`running = True`）

**8.2.2 重连次数限制**：
- **当前实现**：无限制重连
- **重连计数**：记录`reconnect_count`（用于日志）
- **设计考虑**：确保连接可靠性，不限制重连次数

**8.2.3 重连流程**：
```
检测到连接断开
    ↓
调用_schedule_reconnect()
    ↓
等待重连间隔（5秒）
    ↓
调用_reconnect()
    ↓
重置状态变量
    ↓
关闭旧连接（如果存在）
    ↓
调用_connect()重新连接
    ↓
重新登录和订阅
```

### 8.3 重连后恢复

**8.3.1 重新登录**：
- **登录时机**：连接建立后（`_on_open`回调）
- **登录方式**：自动发送登录消息
- **登录确认**：等待登录响应，设置`logged_in = True`

**8.3.2 重新订阅**：
- **订阅时机**：登录成功后自动订阅
- **订阅频道**：持仓频道（positions）或订单频道（orders）
- **订阅确认**：等待订阅响应，设置`subscribed = True`

**8.3.3 状态恢复**：
- **状态恢复**：重新建立连接后，状态自动恢复
- **数据恢复**：收到snapshot消息时，更新持仓状态
- **去重恢复**：去重记录保留，避免重复处理

## 九、状态管理

### 9.1 连接状态

**9.1.1 connected状态**：
- **含义**：WebSocket连接是否已建立
- **设置时机**：`_on_open`回调时设为True，`_on_close`回调时设为False
- **用途**：判断连接是否可用

**9.1.2 logged_in状态**：
- **含义**：是否已登录成功
- **设置时机**：收到登录成功响应时设为True
- **用途**：判断是否可以订阅频道

**9.1.3 subscribed状态**：
- **含义**：是否已订阅频道
- **设置时机**：收到订阅成功响应时设为True
- **用途**：判断是否可以接收数据

**9.1.4 running状态**：
- **含义**：WebSocket客户端是否正在运行
- **设置时机**：`start()`时设为True，`stop()`时设为False
- **用途**：控制重连和心跳机制

### 9.2 持仓状态追踪

**9.2.1 position_states字典**：
- **键**：`posId`（持仓ID）
- **值**：持仓数据字典（包含pos、posSide、uTime等）
- **用途**：追踪每个持仓的上一次状态，用于检测持仓变化

**9.2.2 状态更新逻辑**：
- **更新时机**：收到持仓消息时（snapshot或event_update）
- **更新方式**：直接覆盖上一次状态
- **更新内容**：持仓数量、持仓方向、更新时间等

### 9.3 状态同步

**状态同步机制**：
- **内存状态**：`position_states`字典（WebSocket客户端）
- **数据库状态**：`position_history`表（通过PositionHistorySyncManager同步）
- **TradingManager状态**：`current_cl_ord_id`等（内存状态）
- **同步方式**：通过WebSocket消息实时更新，定期与数据库同步

## 十、与TradingManager集成

### 10.1 订单回调

**10.1.1 回调触发时机**：
- **触发方式**：通过WebSocket消息实时触发
- **触发条件**：订单状态变化时（filled、partially_filled、canceled）
- **处理方式**：异步处理，写入数据库

**10.1.2 回调参数**：
- **订单数据**：包含ordId、clOrdId、state等
- **事件类型**：snapshot或update
- **处理结果**：写入order_history表

### 10.2 外部平仓处理

**10.2.1 平仓事件传递**：
- **检测位置**：WebSocket客户端（`_detect_position_change`）
- **传递方式**：放入平仓事件队列
- **处理位置**：后台线程（`_process_close_event`）

**10.2.2 TradingManager调用**：
- **调用方法**：`trading_manager.handle_external_close_position()`
- **调用参数**：
  - `pos_id`：持仓ID
  - `cl_ord_id`：客户端订单ID（通过pos_id查找）
  - `close_amount`：平仓数量
  - `is_full_close`：是否全部平仓
  - `u_time`：更新时间
- **处理结果**：更新交易记录和内存状态

### 10.3 依赖注入

**10.3.1 构造函数注入**：
- **注入方式**：通过构造函数参数注入
- **注入对象**：`TradingManager`实例
- **可选性**：如果未注入，只记录日志，不处理平仓

**10.3.2 回调设置**：
- **回调方式**：直接调用TradingManager方法
- **回调时机**：检测到外部平仓时
- **错误处理**：如果调用失败，记录错误日志

## 十一、OKXOrdersWebSocketClient 设计

### 11.1 类结构

**核心属性**：
- `ws_url`：WebSocket连接URL（私有频道）
- `ws`：WebSocketApp实例
- `order_queue`：订单处理队列（maxsize=500）
- `processed_orders`：已处理的订单（去重）
- `queued_orders`：队列中的订单（去重）

**与OKXOrderWebSocketClient的区别**：
- **订阅频道**：订单频道（orders）而非持仓频道（positions）
- **处理数据**：订单数据而非持仓数据
- **队列大小**：500（比持仓队列大，因为订单消息更频繁）

### 11.2 初始化流程

1. **设置WebSocket URL**：从配置读取`WS_PRIVATE_URL`
2. **初始化状态变量**：connected、logged_in、subscribed、running
3. **初始化队列**：创建订单处理队列（maxsize=500）
4. **初始化去重集合**：创建processed_orders和queued_orders
5. **读取API凭证**：从配置读取API密钥

### 11.3 与OrderHistorySyncManager协调

**协调机制**：
- **数据来源**：WebSocket实时订单消息
- **数据存储**：写入order_history表
- **去重机制**：通过(ord_id, u_time)去重
- **协调方式**：WebSocket作为主要数据源，OrderHistorySyncManager作为补充（历史数据同步）

## 十二、订单频道订阅

### 12.1 订阅机制

**订阅消息**：
```json
{
    "op": "subscribe",
    "args": [{
        "channel": "orders",
        "instType": "SWAP"
    }]
}
```

**订阅流程**：
1. 连接建立后登录
2. 登录成功后自动订阅订单频道
3. 等待订阅确认响应

### 12.2 订单状态同步

**同步方式**：
- **实时同步**：通过WebSocket消息实时接收订单状态
- **存储位置**：`order_history`表
- **同步内容**：订单状态、成交数量、成交时间等

### 12.3 与历史同步协调

**协调策略**：
- **WebSocket优先**：WebSocket消息作为主要数据源
- **历史同步补充**：OrderHistorySyncManager定期同步历史数据，补充缺失数据
- **去重机制**：通过(ord_id, u_time)去重，避免重复写入

## 十三、错误处理

### 13.1 连接错误

**13.1.1 连接失败处理**：
- **检测方式**：`_on_error`回调或连接异常
- **处理方式**：记录错误日志，触发重连
- **重连机制**：自动重连，无限制次数

**13.1.2 网络异常处理**：
- **检测方式**：连接断开、心跳超时
- **处理方式**：关闭连接，触发重连
- **恢复机制**：自动重连，重新登录和订阅

### 13.2 认证错误

**13.2.1 认证失败处理**：
- **检测方式**：登录响应中code != "0"
- **处理方式**：记录错误日志，不设置logged_in
- **恢复机制**：重连后重新尝试登录

**13.2.2 密钥错误处理**：
- **检测方式**：认证失败，错误码表示密钥错误
- **处理方式**：记录严重错误日志，停止重连（需要人工修复）
- **恢复机制**：修复配置后重启服务

### 13.3 消息错误

**13.3.1 消息解析失败**：
- **检测方式**：`json.loads()`抛出异常
- **处理方式**：记录警告日志，忽略消息
- **恢复机制**：继续接收下一条消息

**13.3.2 消息格式错误**：
- **检测方式**：消息缺少必要字段
- **处理方式**：记录警告日志，跳过处理
- **恢复机制**：继续接收下一条消息

### 13.4 错误恢复

**恢复策略**：
- **自动恢复**：连接错误、网络异常自动重连
- **人工介入**：认证错误需要人工修复配置
- **日志记录**：所有错误都记录详细日志，便于排查

## 十四、性能优化

### 14.1 消息队列大小限制

**限制策略**：
- **平仓事件队列**：maxsize=100
- **持仓数据队列**：maxsize=200
- **订单处理队列**：maxsize=500
- **限制原因**：防止内存无限增长

### 14.2 异步处理优化

**优化措施**：
- **异步处理**：使用队列和后台线程，避免阻塞WebSocket消息接收
- **批量处理**：一次处理一个消息，避免批量处理导致延迟
- **优先级处理**：平仓事件优先处理

### 14.3 内存管理

**管理策略**：
- **消息限制**：`position_messages`最多保存100条（用于测试）
- **去重记录清理**：定期清理过期的去重记录
- **状态字典清理**：不需要清理，因为持仓数量有限

### 14.4 去重记录清理

**清理机制**：
- **清理时机**：检测持仓变化时自动清理
- **清理对象**：
  - `processed_closes`：30分钟过期
  - `queued_closes`：5分钟过期
  - `processed_orders`：1小时过期（定期清理）
- **清理方法**：遍历字典，删除过期记录

## 十五、配置说明

### 15.1 WebSocket URL配置

**15.1.1 公共频道URL**：
- **配置项**：`WS_URL`
- **默认值**：`wss://ws.okx.com:8443/ws/v5/public`
- **用途**：公共频道（价格、行情等）

**15.1.2 私有频道URL**：
- **配置项**：`WS_PRIVATE_URL`
- **默认值**：`wss://ws.okx.com:8443/ws/v5/private`
- **用途**：私有频道（持仓、订单等，需要登录）

**15.1.3 沙箱/生产环境切换**：
- **配置项**：`EXCHANGE_SANDBOX`
- **默认值**：`True`（沙箱环境）
- **URL切换**：根据此配置自动切换URL

### 15.2 心跳配置

**15.2.1 WS_HEARTBEAT_INTERVAL**：
- **默认值**：20秒
- **说明**：心跳检查间隔，如果此时间内没有收到消息，发送ping
- **要求**：必须小于30秒（OKX要求）

**15.2.2 WS_PING_TIMEOUT**：
- **默认值**：5秒
- **说明**：发送ping后等待pong的超时时间
- **超时处理**：如果超时未收到pong，触发重连

### 15.3 重连配置

**15.3.1 WS_RECONNECT_INTERVAL**：
- **默认值**：5秒
- **说明**：连接断开后，等待多少秒后重连
- **重连次数**：无限制（只要running=True）

### 15.4 超时配置

**15.4.1 WS_CONNECT_TIMEOUT**：
- **默认值**：30秒
- **说明**：WebSocket连接超时时间

**15.4.2 WS_SUBSCRIBE_TIMEOUT**：
- **默认值**：30秒
- **说明**：订阅频道超时时间

**15.4.3 WS_PRICE_TIMEOUT**：
- **默认值**：30秒
- **说明**：获取价格超时时间（用于OKXWebSocketClient）

### 15.5 队列配置

**15.5.1 WS_QUEUE_MAXSIZE**：
- **默认值**：100
- **说明**：队列最大大小（用于某些队列的默认值）
- **实际使用**：不同队列有不同的maxsize设置

### 15.6 SSL配置

**15.6.1 WS_SSL_VERIFY**：
- **默认值**：`True`
- **说明**：是否验证SSL证书
- **推荐**：生产环境必须为True

**15.6.2 WS_SSL_CERT_PATH**：
- **默认值**：`None`
- **说明**：SSL证书文件路径（可选）
- **使用方式**：如果为None，使用系统默认证书或certifi证书

## 十六、消息格式

### 16.1 登录消息格式

**请求消息**：
```json
{
    "op": "login",
    "args": [
        {
            "apiKey": "your_api_key",
            "passphrase": "your_passphrase",
            "timestamp": "1234567890",
            "sign": "base64_encoded_signature"
        }
    ]
}
```

**响应消息**：
```json
{
    "event": "login",
    "code": "0",
    "msg": ""
}
```

### 16.2 订阅消息格式

**请求消息**：
```json
{
    "op": "subscribe",
    "args": [
        {
            "channel": "positions",
            "instType": "SWAP"
        }
    ]
}
```

**响应消息**：
```json
{
    "event": "subscribe",
    "arg": {
        "channel": "positions",
        "instType": "SWAP"
    },
    "code": "0",
    "msg": ""
}
```

### 16.3 持仓消息格式

**数据消息**：
```json
{
    "arg": {
        "channel": "positions",
        "instType": "SWAP"
    },
    "eventType": "snapshot" | "event_update",
    "data": [
        {
            "posId": "123456",
            "instId": "ETH-USDT-SWAP",
            "posSide": "long",
            "pos": "1.0",
            "availPos": "1.0",
            "avgPx": "3000.0",
            "upl": "100.0",
            "uplRatio": "0.01",
            "lever": "10",
            "margin": "300.0",
            "mgnMode": "cross",
            "uTime": "1234567890123",
            "markPx": "3100.0"
        }
    ]
}
```

### 16.4 订单消息格式

**数据消息**：
```json
{
    "arg": {
        "channel": "orders",
        "instType": "SWAP"
    },
    "eventType": "snapshot" | "update",
    "data": [
        {
            "ordId": "123456",
            "clOrdId": "client_order_id",
            "instId": "ETH-USDT-SWAP",
            "side": "buy",
            "posSide": "long",
            "state": "filled",
            "accFillSz": "1.0",
            "fillTime": "1234567890123",
            "uTime": "1234567890123"
        }
    ]
}
```

### 16.5 心跳消息格式

**ping消息**：
- **格式**：字符串`'ping'`（非JSON）
- **发送方式**：`ws.send('ping')`

**pong响应**：
- **格式1**：字符串`'pong'`（非JSON）
- **格式2**：JSON格式`{"event": "pong"}`
- **接收方式**：在`_on_message`回调中处理

## 十七、测试和调试

### 17.1 连接测试

**测试方法**：
- **启动测试**：调用`start()`方法，检查连接是否建立
- **状态检查**：检查`connected`、`logged_in`、`subscribed`状态
- **日志检查**：查看日志，确认连接、登录、订阅成功

### 17.2 消息接收测试

**测试方法**：
- **消息保存**：`position_messages`列表保存最近100条消息（用于测试）
- **消息查询**：调用`get_position_messages()`获取消息列表
- **消息清空**：调用`clear_messages()`清空消息记录

### 17.3 重连测试

**测试方法**：
- **模拟断开**：手动关闭连接，观察是否自动重连
- **重连日志**：查看日志，确认重连流程
- **状态恢复**：确认重连后状态是否正确恢复

### 17.4 日志记录

**日志级别**：
- **DEBUG**：详细调试信息（心跳、消息处理等）
- **INFO**：重要操作信息（连接、登录、订阅、平仓检测等）
- **WARNING**：警告信息（队列满、去重跳过等）
- **ERROR**：错误信息（连接失败、认证失败、处理异常等）

**日志内容**：
- **连接日志**：连接建立、断开、重连
- **认证日志**：登录请求、登录响应
- **订阅日志**：订阅请求、订阅响应
- **消息日志**：收到的消息、处理结果
- **错误日志**：所有错误的详细信息
