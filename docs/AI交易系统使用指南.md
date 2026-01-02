# QwenTradeAI 使用指南

> **版本**: 2.0
> **更新日期**: 2026-01-02
> **系统定位**: 低频量化交易系统 | 数据同步 | 市场检测 | 交易执行

---

## 📋 目录

- [系统概述](#系统概述)
- [快速开始](#快速开始)
- [环境配置](#环境配置)
- [数据库初始化](#数据库初始化)
- [核心功能使用](#核心功能使用)
- [API接口说明](#api接口说明)
- [配置参数详解](#配置参数详解)
- [数据表结构](#数据表结构)
- [故障排查](#故障排查)
- [最佳实践](#最佳实践)
- [常见问题FAQ](#常见问题faq)

---

## 系统概述

### 什么是 QwenTradeAI？

QwenTradeAI 是一个基于技术指标的**低频量化交易系统**，提供完整的数据同步、市场检测和交易执行功能。系统支持OKX交易所，可用于模拟盘和实盘交易。

### 核心特性

✅ **多维度数据同步**
- K线数据（15分钟、4小时、日线）
- 资金费率、未平仓合约
- 市场情绪、爆仓历史
- ETF资金流、恐惧贪婪指数

✅ **智能市场检测**
- 三层过滤机制（环境层、触发层、确认层）
- 多时间框架共振分析
- 15+技术指标自动计算
- 信号评分系统（0-30分）

✅ **完善的交易管理**
- 开仓、加仓、减仓、平仓
- 自动止损止盈（OKX条件单）
- 外部平仓检测
- 完整的状态追踪

✅ **实时WebSocket监控**
- 订单状态实时推送
- 持仓变化监控
- 账户余额更新

### 技术栈

| 分类 | 技术 | 版本 |
|-----|------|------|
| **后端框架** | FastAPI | 0.104.1 |
| **数据库** | PostgreSQL + SQLAlchemy | 2.0.23 |
| **交易所** | CCXT (OKX) | 4.0+ |
| **数据处理** | Pandas + NumPy | 2.0+ / 1.24+ |
| **WebSocket** | websocket-client | 1.6.x |
| **配置管理** | Pydantic | 2.5.0 |
| **日志** | Loguru | 0.7.2 |

### 重要说明

⚠️ **当前版本暂不包含AI模型**
- 系统基于**技术指标规则引擎**进行市场检测
- 未集成机器学习模型进行决策
- AI集成接口已预留，计划未来版本实现

---

## 快速开始

### 前置条件

```bash
# 系统要求
Python >= 3.10
PostgreSQL >= 13
Git

# 硬件要求
内存: 2GB+
磁盘: 10GB+
网络: 稳定连接到OKX和CoinGlass
```

### 5分钟部署

#### 1️⃣ 克隆代码

```bash
git clone https://github.com/wangyongyuan/Qwentradesai.git
cd Qwentradesai
```

#### 2️⃣ 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

#### 3️⃣ 初始化数据库

```bash
# 连接到PostgreSQL
psql -U postgres

# 创建数据库和用户
CREATE DATABASE qwentradeai;
CREATE USER qwentradeai WITH PASSWORD 'qwentradeai';
GRANT ALL PRIVILEGES ON DATABASE qwentradeai TO qwentradeai;
\q

# 导入表结构
psql -U qwentradeai -d qwentradeai -f database/all_tables.sql
```

#### 4️⃣ 配置OKX API

在数据库 `system_config` 表中插入配置：

```sql
INSERT INTO system_config (config_key, config_value, value_type, description) VALUES
('EXCHANGE_API_KEY', '你的API_KEY', 'string', 'OKX API Key'),
('EXCHANGE_SECRET', '你的SECRET', 'string', 'OKX Secret Key'),
('EXCHANGE_PASSPHRASE', '你的PASSPHRASE', 'string', 'OKX Passphrase'),
('EXCHANGE_SANDBOX', 'true', 'bool', '是否使用模拟盘（true=模拟，false=实盘）');
```

#### 5️⃣ 启动系统

```bash
# 开发模式（自动重载）
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 6️⃣ 验证运行

访问 API 文档：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

检查健康状态：
```bash
curl http://localhost:8000/health
```

---

## 环境配置

### 配置优先级

```
数据库 system_config 表 > 环境变量 > 代码默认值
```

### 方式1：数据库配置（推荐）

在 `system_config` 表中配置参数：

```sql
-- 查看当前配置
SELECT * FROM system_config ORDER BY config_key;

-- 修改配置
UPDATE system_config SET config_value = 'new_value' WHERE config_key = 'EXCHANGE_SANDBOX';

-- 添加新配置
INSERT INTO system_config (config_key, config_value, value_type, description)
VALUES ('TRADING_SYMBOLS', 'ETH,BTC', 'string', '交易币种列表');
```

**优势**：
- 无需重启应用即可生效（部分配置）
- 支持多环境管理
- 配置历史可追溯

### 方式2：环境变量

创建 `.env` 文件：

```bash
# 数据库配置
DATABASE_URL=postgresql://qwentradeai:qwentradeai@localhost:5432/qwentradeai

# OKX交易所配置
EXCHANGE_NAME=okx
EXCHANGE_API_KEY=your_api_key
EXCHANGE_SECRET=your_secret
EXCHANGE_PASSPHRASE=your_passphrase
EXCHANGE_SANDBOX=true

# CoinGlass API
COINGLASS_API_KEY=95c31ba79d054646b2ca68c23bfb4839

# 交易币种
TRADING_SYMBOLS=ETH

# 日志级别
LOG_LEVEL=INFO
```

### OKX API 申请

1. 登录 [OKX官网](https://www.okx.com)
2. 进入 **账户 → API管理**
3. 创建API Key（选择权限：读取、交易）
4. **重要**：
   - 开启模拟盘测试（`EXCHANGE_SANDBOX=true`）
   - 绑定IP白名单
   - 保管好Secret和Passphrase（不可恢复）

### CoinGlass API 申请

1. 访问 [CoinGlass](https://www.coinglass.com)
2. 注册账户并申请API Key
3. 将Key配置到 `COINGLASS_API_KEY`

---

## 数据库初始化

### 表结构概览

系统包含 **16 个数据表**，分为5类：

| 分类 | 表名 | 用途 |
|-----|------|------|
| **K线数据** | klines_15m, klines_4h, klines_1d | 多时间周期K线+技术指标 |
| **市场数据** | funding_rate_history, open_interest_15m, market_sentiment_data, order_book_distribution, etf_flow_data, fear_greed_index, liquidation_history | 市场全维度数据 |
| **市场检测** | market_detection_snapshots, market_signals | 检测快照+交易信号 |
| **交易数据** | order_history, position_history, trading_relations, pending_orders | 订单、持仓、关系追踪 |
| **系统配置** | system_config | 系统配置参数 |

### 完整SQL脚本

```bash
# 执行完整建表脚本
psql -U qwentradeai -d qwentradeai -f database/all_tables.sql
```

### 验证数据表

```sql
-- 查看所有表
\dt

-- 查看表结构
\d klines_15m
\d market_signals
\d trading_relations

-- 检查索引
SELECT tablename, indexname FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename;
```

### 初始化配置数据

```sql
-- 插入默认系统配置
INSERT INTO system_config (config_key, config_value, value_type, description) VALUES
('APP_NAME', 'QwenTradeAI', 'string', '应用名称'),
('APP_VERSION', '2.0', 'string', '应用版本'),
('EXCHANGE_SANDBOX', 'true', 'bool', '是否使用模拟盘'),
('TRADING_SYMBOLS', 'ETH', 'string', '交易币种'),
('DETECTOR_SIGNAL_EXPIRE_HOURS', '4', 'int', '信号有效期（小时）');
```

---

## 核心功能使用

### 1. 数据同步

系统启动后会自动执行数据同步，无需手动触发。

#### 同步频率

| 数据类型 | 同步频率 | 历史补全 |
|---------|---------|---------|
| K线（15分钟） | 每15分钟 | 30天 |
| K线（4小时） | 每4小时 | 180天 |
| K线（日线） | 每天0点 | 600天 |
| 资金费率 | 每8小时 | 30天 |
| 未平仓合约 | 每15分钟 | 支持 |
| 市场情绪 | 每小时 | 支持 |
| 订单簿 | 每小时 | 不支持 |
| ETF资金流 | 每天8点 | 支持（仅BTC/ETH） |
| 恐惧贪婪指数 | 每天8点 | 支持 |
| 爆仓历史 | 每4小时 | 支持 |
| 订单/持仓历史 | 每30秒 | 支持 |

#### 手动触发同步（通过API）

```bash
# 触发K线同步
curl -X POST http://localhost:8000/api/sync/klines

# 触发资金费率同步
curl -X POST http://localhost:8000/api/sync/funding-rate
```

#### 查看同步状态

```sql
-- 查看最新K线数据
SELECT * FROM klines_15m WHERE symbol = 'ETH-USDT-SWAP' ORDER BY time DESC LIMIT 10;

-- 查看数据完整性
SELECT
    symbol,
    COUNT(*) as data_points,
    MIN(time) as earliest,
    MAX(time) as latest
FROM klines_15m
GROUP BY symbol;
```

### 2. 市场检测

系统每15分钟自动执行一次市场检测。

#### 检测机制

**三层过滤模型**：

1. **环境层（Filter Layer）**
   - 判断市场模式：BULL（牛市）/ BEAR（熊市）/ NEUTRAL（震荡）
   - 检测市场活跃度（基于布林带宽度）
   - 多时间框架趋势对齐（15m + 4h）

2. **触发层（Trigger Layer）**
   - MACD动量转折检测
   - RSI超买超卖过滤
   - 仓位倍数调整

3. **确认层（Confirm Layer）**
   - 成交量确认
   - 布林带确认
   - 多时间框架共振

#### 信号评分

| 条件 | 得分 | 说明 |
|-----|------|------|
| 环境层通过 | +10 | 基础分 |
| MACD转折 | +5 | 动量确认 |
| RSI符合区间 | +3 | 超买超卖过滤 |
| 成交量放大 | +5 | 成交量确认 |
| 布林带扩张 | +3 | 波动率确认 |
| 多时间框架共振 | +4 | 4h同时触发 |
| **总分范围** | **0-30** | **≥15分生成信号** |

#### 查看检测结果

```sql
-- 查看最新检测快照
SELECT * FROM market_detection_snapshots
WHERE symbol = 'ETH-USDT-SWAP'
ORDER BY detected_at DESC
LIMIT 1;

-- 查看生成的信号
SELECT
    id,
    symbol,
    signal_type,
    score,
    status,
    signal_time,
    expire_time
FROM market_signals
WHERE status = 'PENDING'
ORDER BY signal_time DESC;
```

#### 手动触发检测

```bash
curl -X POST http://localhost:8000/api/market/detect
```

### 3. 交易执行

#### 3.1 开仓（Open Position）

**API调用**：

```bash
curl -X POST http://localhost:8000/api/trading/open \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "side": "LONG",
    "amount": 0.1,
    "leverage": 3,
    "stop_loss_trigger": 3200,
    "take_profit_trigger": 3500,
    "signal_id": 123
  }'
```

**参数说明**：
- `symbol`: 交易对（格式：币种-计价币-SWAP）
- `side`: 方向（`LONG` 做多 / `SHORT` 做空）
- `amount`: 数量（币的数量，非USDT）
- `leverage`: 杠杆倍数（1-125）
- `stop_loss_trigger`: 止损触发价（可选）
- `take_profit_trigger`: 止盈触发价（可选）
- `signal_id`: 关联的信号ID（可选）

**响应示例**：

```json
{
  "status": "success",
  "cl_ord_id": "ETH_LONG_20260102_120000_abc123",
  "order_id": "671234567890",
  "message": "开仓成功",
  "position": {
    "symbol": "ETH-USDT-SWAP",
    "side": "LONG",
    "amount": 0.1,
    "avg_price": 3350.5
  }
}
```

#### 3.2 加仓（Add Position）

```bash
curl -X POST http://localhost:8000/api/trading/add \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "amount": 0.05
  }'
```

**注意**：
- 必须有活跃持仓才能加仓
- 加仓方向自动与当前持仓一致
- 会复用原来的 `cl_ord_id`

#### 3.3 减仓（Reduce Position）

```bash
curl -X POST http://localhost:8000/api/trading/reduce \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "amount": 0.03
  }'
```

**注意**：
- 减仓数量不能超过当前持仓
- 部分平仓，剩余持仓继续保持

#### 3.4 平仓（Close Position）

```bash
curl -X POST http://localhost:8000/api/trading/close \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP"
  }'
```

**注意**：
- 全部平仓，持仓归零
- 自动取消关联的止损止盈单

#### 3.5 修改止损止盈

```bash
curl -X POST http://localhost:8000/api/trading/set-sl-tp \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "stop_loss_trigger": 3250,
    "take_profit_trigger": 3600
  }'
```

#### 3.6 查询持仓

```bash
# 查询当前持仓
curl http://localhost:8000/api/trading/position?symbol=ETH-USDT-SWAP

# 查询订单状态
curl http://localhost:8000/api/trading/order?order_id=671234567890
```

### 4. WebSocket实时监控

系统启动后会自动启动WebSocket连接，监控订单和持仓变化。

#### 监控的事件

1. **订单状态变化**
   - 订单创建
   - 订单成交
   - 订单取消
   - 订单失败

2. **持仓变化**
   - 开仓
   - 加仓
   - 减仓
   - 平仓（包括外部平仓）

3. **账户余额变化**
   - 资金增加
   - 资金减少

#### 外部平仓检测

系统会自动检测外部平仓（通过OKX网页、APP等手动平仓），并执行以下操作：

1. 更新内存状态
2. 记录到 `trading_relations` 表（action_type='EXTERNAL_CLOSE'）
3. 取消关联的止损止盈单
4. 记录日志

### 5. 挂单管理

支持价格触发挂单（到价开仓）。

#### 创建挂单

```bash
curl -X POST http://localhost:8000/api/pending-order/create \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "side": "LONG",
    "trigger_price": 3300,
    "amount": 0.1,
    "leverage": 3,
    "stop_loss_trigger": 3200,
    "take_profit_trigger": 3500,
    "signal_id": 123
  }'
```

#### 查询挂单

```bash
# 查询所有挂单
curl http://localhost:8000/api/pending-order/list

# 查询指定币种挂单
curl http://localhost:8000/api/pending-order/list?symbol=ETH-USDT-SWAP
```

#### 取消挂单

```bash
curl -X POST http://localhost:8000/api/pending-order/cancel \
  -H "Content-Type: application/json" \
  -d '{
    "pending_order_id": 456
  }'
```

---

## API接口说明

### 健康检查

```http
GET /health
```

响应：
```json
{
  "status": "ok",
  "version": "2.0",
  "database": "connected"
}
```

### 数据库管理

#### 获取配置

```http
GET /api/database/config
```

响应：
```json
{
  "config": [
    {
      "config_key": "TRADING_SYMBOLS",
      "config_value": "ETH",
      "value_type": "string",
      "description": "交易币种"
    }
  ]
}
```

#### 更新配置

```http
POST /api/database/config
Content-Type: application/json

{
  "config_key": "EXCHANGE_SANDBOX",
  "config_value": "false",
  "value_type": "bool",
  "description": "是否使用模拟盘"
}
```

### 交易测试

#### 测试市价下单

```http
POST /api/trading-test/market-order
Content-Type: application/json

{
  "symbol": "ETH-USDT-SWAP",
  "side": "buy",
  "amount": 0.01,
  "position_side": "long"
}
```

#### 测试限价下单

```http
POST /api/trading-test/limit-order
Content-Type: application/json

{
  "symbol": "ETH-USDT-SWAP",
  "side": "buy",
  "price": 3300,
  "amount": 0.01,
  "position_side": "long"
}
```

#### 测试止损止盈

```http
POST /api/trading-test/stop-order
Content-Type: application/json

{
  "symbol": "ETH-USDT-SWAP",
  "side": "sell",
  "trigger_price": 3200,
  "amount": 0.01,
  "position_side": "long",
  "order_type": "stop_loss"
}
```

### 持仓历史查询

```http
GET /api/position-history/test?symbol=ETH-USDT-SWAP&limit=10
```

### 订单历史查询

```http
GET /api/order-history/test?symbol=ETH-USDT-SWAP&limit=10
```

---

## 配置参数详解

### 应用配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| APP_NAME | QwenTradeAI | 应用名称 |
| APP_VERSION | 2.0 | 应用版本 |
| DEBUG | false | 调试模式 |
| LOG_LEVEL | INFO | 日志级别（DEBUG/INFO/WARNING/ERROR） |

### 交易所配置

| 参数 | 必填 | 说明 |
|-----|------|------|
| EXCHANGE_NAME | 是 | 交易所名称（okx） |
| EXCHANGE_API_KEY | 是 | OKX API Key |
| EXCHANGE_SECRET | 是 | OKX Secret Key |
| EXCHANGE_PASSPHRASE | 是 | OKX Passphrase |
| EXCHANGE_SANDBOX | 否 | 是否使用模拟盘（默认true） |
| TRADING_SYMBOLS | 否 | 交易币种（默认ETH） |

### RSI配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| RSI_15M_PERIOD | 7 | 15分钟RSI周期 |
| RSI_15M_OVERSOLD | 20.0 | 15分钟RSI超卖线 |
| RSI_15M_OVERBOUGHT | 80.0 | 15分钟RSI超买线 |
| RSI_4H_PERIOD | 14 | 4小时RSI周期 |
| RSI_4H_OVERSOLD | 30.0 | 4小时RSI超卖线 |
| RSI_4H_OVERBOUGHT | 70.0 | 4小时RSI超买线 |

### MACD配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| MACD_15M_FAST | 8 | 15分钟MACD快线周期 |
| MACD_15M_SLOW | 17 | 15分钟MACD慢线周期 |
| MACD_15M_SIGNAL | 9 | 15分钟MACD信号线周期 |
| MACD_4H_FAST | 12 | 4小时MACD快线周期 |
| MACD_4H_SLOW | 26 | 4小时MACD慢线周期 |
| MACD_4H_SIGNAL | 9 | 4小时MACD信号线周期 |

### EMA配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| EMA_SHORT | 9 | 短期EMA周期 |
| EMA_MID | 21 | 中期EMA周期 |
| EMA_LONG | 55 | 长期EMA周期（趋势判断） |

### 布林带配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| BB_PERIOD | 20 | 布林带周期 |
| BB_STD | 2.0 | 布林带标准差倍数 |

### ATR配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| ATR_15M_PERIOD | 14 | 15分钟ATR周期 |

### 市场检测器配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| DETECTOR_EMA_TREND_PERIOD | 55 | 趋势判断EMA周期 |
| DETECTOR_BB_WIDTH_THRESHOLD | 0.5 | 布林带宽度阈值（活跃度判断） |
| DETECTOR_RSI_LONG_THRESHOLD | 80.0 | 做多时RSI上限 |
| DETECTOR_RSI_SHORT_THRESHOLD | 20.0 | 做空时RSI下限 |
| DETECTOR_RSI_DOUBLE_POSITION_LONG | 50.0 | 做多加倍仓位RSI阈值 |
| DETECTOR_RSI_DOUBLE_POSITION_SHORT | 50.0 | 做空加倍仓位RSI阈值 |
| DETECTOR_VOLUME_STD_MULTIPLIER | 1.5 | 成交量确认倍数 |
| DETECTOR_BB_CONFIRM_THRESHOLD | 1.2 | 布林带确认倍数 |
| DETECTOR_KLINE_15M_COUNT | 100 | 检测用15分钟K线数量 |
| DETECTOR_KLINE_4H_COUNT | 60 | 检测用4小时K线数量 |
| DETECTOR_ENABLE_MULTI_TF | true | 是否启用多时间框架 |
| DETECTOR_SIGNAL_EXPIRE_HOURS | 4 | 信号有效期（小时） |

### WebSocket配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| WS_RECONNECT_INTERVAL | 5 | 重连间隔（秒） |
| WS_HEARTBEAT_INTERVAL | 20 | 心跳间隔（秒） |
| WS_PING_TIMEOUT | 5 | Ping超时（秒） |
| WS_CONNECT_TIMEOUT | 30 | 连接超时（秒） |
| WS_SUBSCRIBE_TIMEOUT | 30 | 订阅超时（秒） |
| WS_PRICE_TIMEOUT | 30 | 价格超时（秒） |

### API管理器配置

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| API_RATE_LIMIT | 10 | 每时间窗口最大请求数 |
| API_RATE_WINDOW | 2.0 | 限流时间窗口（秒） |
| API_MIN_INTERVAL | 0.2 | 最小请求间隔（秒） |
| API_REQUEST_TIMEOUT | 30 | 请求超时（秒） |
| API_MAX_RETRIES | 3 | 最大重试次数 |

---

## 数据表结构

### K线数据表

#### klines_15m（15分钟K线）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | K线时间（主键） |
| open | NUMERIC(20,8) | 开盘价 |
| high | NUMERIC(20,8) | 最高价 |
| low | NUMERIC(20,8) | 最低价 |
| close | NUMERIC(20,8) | 收盘价 |
| volume | NUMERIC(20,8) | 成交量 |
| ema_9 | NUMERIC(20,8) | EMA(9) |
| ema_21 | NUMERIC(20,8) | EMA(21) |
| ema_55 | NUMERIC(20,8) | EMA(55) |
| rsi_7 | NUMERIC(20,8) | RSI(7) |
| macd_line | NUMERIC(20,8) | MACD快线 |
| signal_line | NUMERIC(20,8) | MACD慢线 |
| histogram | NUMERIC(20,8) | MACD柱状图 |
| bb_upper | NUMERIC(20,8) | 布林带上轨 |
| bb_middle | NUMERIC(20,8) | 布林带中轨 |
| bb_lower | NUMERIC(20,8) | 布林带下轨 |
| atr_14 | NUMERIC(20,8) | ATR(14) |
| obv | NUMERIC(30,8) | OBV指标 |
| obv_ema_9 | NUMERIC(30,8) | OBV的EMA(9) |
| adx_14 | NUMERIC(20,8) | ADX(14) |
| bb_width | NUMERIC(20,8) | 布林带宽度 |

**索引**：
- PRIMARY KEY (symbol, time)
- INDEX idx_klines_15m_time (time)

#### klines_4h（4小时K线）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | K线时间（主键） |
| open | NUMERIC(20,8) | 开盘价 |
| high | NUMERIC(20,8) | 最高价 |
| low | NUMERIC(20,8) | 最低价 |
| close | NUMERIC(20,8) | 收盘价 |
| volume | NUMERIC(20,8) | 成交量 |
| ema_9 | NUMERIC(20,8) | EMA(9) |
| ema_21 | NUMERIC(20,8) | EMA(21) |
| rsi_14 | NUMERIC(20,8) | RSI(14) |
| macd_line | NUMERIC(20,8) | MACD快线 |
| signal_line | NUMERIC(20,8) | MACD慢线 |
| histogram | NUMERIC(20,8) | MACD柱状图 |
| bb_upper | NUMERIC(20,8) | 布林带上轨 |
| bb_middle | NUMERIC(20,8) | 布林带中轨 |
| bb_lower | NUMERIC(20,8) | 布林带下轨 |
| obv | NUMERIC(30,8) | OBV指标 |

**索引**：
- PRIMARY KEY (symbol, time)
- INDEX idx_klines_4h_time (time)

#### klines_1d（日线K线）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | K线时间（主键） |
| open | NUMERIC(20,8) | 开盘价 |
| high | NUMERIC(20,8) | 最高价 |
| low | NUMERIC(20,8) | 最低价 |
| close | NUMERIC(20,8) | 收盘价 |
| volume | NUMERIC(20,8) | 成交量 |
| ema_9 | NUMERIC(20,8) | EMA(9) |
| ema_21 | NUMERIC(20,8) | EMA(21) |

**索引**：
- PRIMARY KEY (symbol, time)
- INDEX idx_klines_1d_time (time)

### 市场数据表

#### funding_rate_history（资金费率历史）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | 时间（主键） |
| funding_rate | NUMERIC(20,8) | 资金费率 |
| open_interest | NUMERIC(20,8) | 未平仓合约（USDT） |

**索引**：
- PRIMARY KEY (symbol, time)

#### open_interest_15m（未平仓合约15分钟）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | 时间（主键） |
| oi_open | NUMERIC(20,2) | 未平仓开 |
| oi_high | NUMERIC(20,2) | 未平仓高 |
| oi_low | NUMERIC(20,2) | 未平仓低 |
| oi_close | NUMERIC(20,2) | 未平仓收 |
| oi_change | NUMERIC(20,2) | 未平仓变化 |
| oi_change_pct | NUMERIC(10,4) | 未平仓变化百分比 |

**索引**：
- PRIMARY KEY (symbol, time)

#### market_sentiment_data（市场情绪）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | 时间（主键） |
| global_account_long_percent | NUMERIC(10,4) | 全球账户多头占比 |
| global_account_short_percent | NUMERIC(10,4) | 全球账户空头占比 |
| global_account_long_short_ratio | NUMERIC(10,4) | 多空比 |

**索引**：
- PRIMARY KEY (symbol, time)

#### order_book_distribution（盘口挂单分布）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | 时间（主键） |
| asks | JSONB | 卖单分布（价格:[数量,订单数]） |
| bids | JSONB | 买单分布（价格:[数量,订单数]） |
| total_ask_amount | NUMERIC(20,8) | 总卖单数量 |
| total_bid_amount | NUMERIC(20,8) | 总买单数量 |
| total_ask_orders | INTEGER | 总卖单订单数 |
| total_bid_orders | INTEGER | 总买单订单数 |
| bid_ask_ratio | NUMERIC(10,4) | 买卖比 |
| large_ask_amount | NUMERIC(20,8) | 大额卖单（>10 BTC） |
| large_bid_amount | NUMERIC(20,8) | 大额买单（>10 BTC） |

**索引**：
- PRIMARY KEY (symbol, time)

#### etf_flow_data（ETF资金流）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 币种（BTC/ETH）（主键） |
| date | DATE | 日期（主键） |
| net_assets_usd | NUMERIC(20,2) | 净资产（USD） |
| change_usd | NUMERIC(20,2) | 变化（USD） |
| price_usd | NUMERIC(20,8) | 价格（USD） |
| timestamp | TIMESTAMP | 时间戳 |

**索引**：
- PRIMARY KEY (symbol, date)

#### fear_greed_index（恐惧贪婪指数）

| 字段 | 类型 | 说明 |
|-----|------|------|
| date | DATE | 日期（主键） |
| value | INTEGER | 指数值（0-100） |
| price | NUMERIC(20,8) | BTC价格 |
| classification | VARCHAR(50) | 分类（Extreme Fear/Fear/Neutral/Greed/Extreme Greed） |
| previous_value | INTEGER | 前一日值 |
| change | INTEGER | 变化 |

**索引**：
- PRIMARY KEY (date)

#### liquidation_history（爆仓历史）

| 字段 | 类型 | 说明 |
|-----|------|------|
| symbol | VARCHAR(50) | 交易对（主键） |
| time | TIMESTAMP | 时间（主键） |
| aggregated_long_liquidation_usd | NUMERIC(20,2) | 多头爆仓（USD） |
| aggregated_short_liquidation_usd | NUMERIC(20,2) | 空头爆仓（USD） |

**索引**：
- PRIMARY KEY (symbol, time)

### 市场检测表

#### market_detection_snapshots（市场检测快照）

| 字段 | 类型 | 说明 |
|-----|------|------|
| id | SERIAL | 主键 |
| symbol | VARCHAR(50) | 交易对 |
| detected_at | TIMESTAMP | 检测时间 |
| price | NUMERIC(20,8) | 当前价格 |
| price_change_24h | NUMERIC(10,4) | 24h价格变化 |
| kline_15m_time | TIMESTAMP | 15m K线时间 |
| kline_4h_time | TIMESTAMP | 4h K线时间 |
| kline_1d_time | TIMESTAMP | 日线时间 |
| market_mode | VARCHAR(20) | 市场模式（BULL/BEAR/NEUTRAL） |
| market_active | BOOLEAN | 市场活跃度 |
| trend_15m | VARCHAR(20) | 15m趋势 |
| trend_4h | VARCHAR(20) | 4h趋势 |
| multi_tf_aligned | BOOLEAN | 多时间框架对齐 |
| macd_histogram_15m | NUMERIC(20,8) | MACD柱状图 |
| rsi_15m | NUMERIC(20,8) | RSI(15m) |
| volume_15m | NUMERIC(20,8) | 成交量(15m) |
| volume_confirmed | BOOLEAN | 成交量确认 |
| bb_confirmed | BOOLEAN | 布林带确认 |
| multi_tf_confirmed | BOOLEAN | 多时间框架确认 |
| final_score | INTEGER | 最终评分 |
| signal_generated | VARCHAR(20) | 生成的信号（LONG/SHORT/NONE） |

**索引**：
- PRIMARY KEY (id)
- INDEX idx_detection_symbol_time (symbol, detected_at DESC)

#### market_signals（市场信号）

| 字段 | 类型 | 说明 |
|-----|------|------|
| id | SERIAL | 主键 |
| symbol | VARCHAR(50) | 交易对 |
| signal_type | VARCHAR(20) | 信号类型（LONG/SHORT） |
| signal_time | TIMESTAMP | 信号时间 |
| expire_time | TIMESTAMP | 过期时间 |
| score | INTEGER | 评分 |
| status | VARCHAR(20) | 状态（PENDING/EXECUTED/EXPIRED/CANCELLED） |
| detection_snapshot_id | INTEGER | 关联的检测快照ID |
| triggered_at | TIMESTAMP | 触发时间 |

**索引**：
- PRIMARY KEY (id)
- INDEX idx_signal_symbol_status (symbol, status)
- FOREIGN KEY (detection_snapshot_id) REFERENCES market_detection_snapshots(id)

### 交易数据表

#### order_history（订单历史）

| 字段 | 类型 | 说明 |
|-----|------|------|
| order_id | VARCHAR(100) | 订单ID（主键） |
| symbol | VARCHAR(50) | 交易对 |
| inst_id | VARCHAR(50) | 产品ID |
| ord_type | VARCHAR(20) | 订单类型（market/limit/...） |
| side | VARCHAR(20) | 方向（buy/sell） |
| px | NUMERIC(20,8) | 委托价格 |
| sz | NUMERIC(20,8) | 委托数量 |
| fill_px | NUMERIC(20,8) | 成交均价 |
| fill_sz | NUMERIC(20,8) | 成交数量 |
| state | VARCHAR(20) | 状态（live/filled/canceled/...） |
| lever | VARCHAR(20) | 杠杆倍数 |
| td_mode | VARCHAR(20) | 交易模式（cross/isolated） |
| pos_side | VARCHAR(20) | 持仓方向（long/short/net） |
| cl_ord_id | VARCHAR(100) | 客户端订单ID |
| tag | VARCHAR(100) | 订单标签 |
| created_time | TIMESTAMP | 创建时间 |
| updated_time | TIMESTAMP | 更新时间 |

**索引**：
- PRIMARY KEY (order_id)
- INDEX idx_order_symbol_time (symbol, created_time DESC)
- INDEX idx_order_cl_ord_id (cl_ord_id)

#### position_history（持仓历史）

| 字段 | 类型 | 说明 |
|-----|------|------|
| pos_id | VARCHAR(100) | 持仓ID（主键） |
| symbol | VARCHAR(50) | 交易对 |
| inst_id | VARCHAR(50) | 产品ID |
| pos_side | VARCHAR(20) | 持仓方向（long/short/net） |
| pos | NUMERIC(20,8) | 持仓数量 |
| avg_px | NUMERIC(20,8) | 持仓均价 |
| upl | NUMERIC(20,8) | 未实现盈亏 |
| upl_ratio | NUMERIC(10,4) | 未实现盈亏比例 |
| lever | VARCHAR(20) | 杠杆倍数 |
| margin | NUMERIC(20,8) | 保证金 |
| margin_ratio | NUMERIC(10,4) | 保证金率 |
| created_time | TIMESTAMP | 创建时间 |
| updated_time | TIMESTAMP | 更新时间 |
| u_time | TIMESTAMP | OKX更新时间（主键） |

**索引**：
- PRIMARY KEY (pos_id, u_time)
- INDEX idx_position_symbol_time (symbol, u_time DESC)

#### trading_relations（交易关系）

| 字段 | 类型 | 说明 |
|-----|------|------|
| id | SERIAL | 主键 |
| cl_ord_id | VARCHAR(100) | 客户端订单ID |
| signal_id | INTEGER | 关联的信号ID |
| symbol | VARCHAR(50) | 交易对 |
| position_side | VARCHAR(20) | 持仓方向（LONG/SHORT） |
| action_type | VARCHAR(50) | 操作类型（OPEN/ADD/REDUCE/CLOSE/EXTERNAL_CLOSE） |
| order_id | VARCHAR(100) | OKX订单ID |
| amount | NUMERIC(20,8) | 数量 |
| created_at | TIMESTAMP | 创建时间 |

**索引**：
- PRIMARY KEY (id)
- INDEX idx_relation_cl_ord_id (cl_ord_id)
- INDEX idx_relation_signal_id (signal_id)
- FOREIGN KEY (signal_id) REFERENCES market_signals(id)

#### pending_orders（挂单）

| 字段 | 类型 | 说明 |
|-----|------|------|
| id | SERIAL | 主键 |
| symbol | VARCHAR(50) | 交易对 |
| side | VARCHAR(20) | 方向（LONG/SHORT） |
| trigger_price | NUMERIC(20,8) | 触发价格 |
| amount | NUMERIC(20,8) | 数量 |
| stop_loss_trigger | NUMERIC(20,8) | 止损触发价 |
| take_profit_trigger | NUMERIC(20,8) | 止盈触发价 |
| leverage | INTEGER | 杠杆倍数 |
| signal_id | INTEGER | 关联的信号ID |
| status | VARCHAR(20) | 状态（PENDING/TRIGGERED/CANCELLED/EXPIRED） |
| created_at | TIMESTAMP | 创建时间 |
| triggered_at | TIMESTAMP | 触发时间 |
| expired_at | TIMESTAMP | 过期时间 |

**索引**：
- PRIMARY KEY (id)
- INDEX idx_pending_symbol_status (symbol, status)
- FOREIGN KEY (signal_id) REFERENCES market_signals(id)

### 系统配置表

#### system_config（系统配置）

| 字段 | 类型 | 说明 |
|-----|------|------|
| config_key | VARCHAR(100) | 配置键（主键） |
| config_value | TEXT | 配置值 |
| value_type | VARCHAR(20) | 值类型（string/int/float/bool） |
| description | TEXT | 描述 |

**索引**：
- PRIMARY KEY (config_key)

---

## 故障排查

### 常见问题

#### 1. 数据库连接失败

**错误信息**：
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**解决方法**：
```bash
# 检查PostgreSQL是否运行
sudo systemctl status postgresql

# 检查数据库是否存在
psql -U postgres -c "\l" | grep qwentradeai

# 检查用户权限
psql -U postgres -c "\du" | grep qwentradeai

# 重启PostgreSQL
sudo systemctl restart postgresql
```

#### 2. OKX API认证失败

**错误信息**：
```
OKXAPIException: Invalid API Key
```

**解决方法**：
```sql
-- 检查配置是否正确
SELECT * FROM system_config WHERE config_key LIKE 'EXCHANGE_%';

-- 更新API配置
UPDATE system_config SET config_value = '新的API_KEY' WHERE config_key = 'EXCHANGE_API_KEY';
```

**注意**：
- 检查API Key是否正确
- 检查IP白名单是否包含服务器IP
- 检查API权限（需要读取+交易权限）
- 检查是否选择了正确的环境（模拟盘/实盘）

#### 3. WebSocket断线

**错误信息**：
```
WebSocket connection failed: Connection refused
```

**解决方法**：
- 检查网络连接（能否访问 ws.okx.com）
- 检查防火墙设置
- 系统会自动重连（5秒后）
- 查看日志：`tail -f logs/qwentradeai.log`

#### 4. K线数据同步失败

**错误信息**：
```
Failed to sync klines: No data returned
```

**解决方法**：
```sql
-- 检查最新K线时间
SELECT symbol, MAX(time) as latest FROM klines_15m GROUP BY symbol;

-- 手动删除错误数据
DELETE FROM klines_15m WHERE symbol = 'ETH-USDT-SWAP' AND time > '2026-01-01';
```

**可能原因**：
- 交易对格式错误（应为 币种-USDT-SWAP）
- API限流（等待2秒后重试）
- 历史数据范围过大（调整补全天数）

#### 5. 市场检测不生成信号

**现象**：
- `market_detection_snapshots` 有数据
- `market_signals` 没有数据

**排查步骤**：
```sql
-- 查看最新检测快照
SELECT * FROM market_detection_snapshots ORDER BY detected_at DESC LIMIT 1;

-- 检查评分是否达标（≥15分）
SELECT final_score, signal_generated FROM market_detection_snapshots
WHERE detected_at > NOW() - INTERVAL '1 day'
ORDER BY final_score DESC;
```

**可能原因**：
- 评分未达到15分（调整配置参数）
- 市场不活跃（布林带宽度不足）
- 多时间框架不对齐
- RSI超买超卖过滤

#### 6. 交易下单失败

**错误信息**：
```
TradingError: Insufficient margin
```

**解决方法**：
```bash
# 查询账户余额
curl http://localhost:8000/api/trading/balance

# 查询持仓
curl http://localhost:8000/api/trading/position?symbol=ETH-USDT-SWAP
```

**可能原因**：
- 账户余额不足
- 杠杆倍数过高
- 已有反向持仓（OKX单向持仓模式）
- API权限不足（需要交易权限）

### 日志查看

```bash
# 实时查看日志
tail -f logs/qwentradeai.log

# 查看最近100行
tail -n 100 logs/qwentradeai.log

# 过滤错误日志
grep "ERROR" logs/qwentradeai.log

# 过滤交易日志
grep "Trading" logs/qwentradeai.log
```

### 性能监控

```bash
# 查看数据库连接数
psql -U qwentradeai -d qwentradeai -c "SELECT count(*) FROM pg_stat_activity;"

# 查看表大小
psql -U qwentradeai -d qwentradeai -c "
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
"

# 查看慢查询
psql -U qwentradeai -d qwentradeai -c "
SELECT query, calls, total_time, mean_time
FROM pg_stat_statements
ORDER BY mean_time DESC
LIMIT 10;
"
```

---

## 最佳实践

### 1. 模拟盘测试

⚠️ **强烈建议先在模拟盘测试**

```sql
-- 确认使用模拟盘
UPDATE system_config SET config_value = 'true' WHERE config_key = 'EXCHANGE_SANDBOX';
```

**测试步骤**：
1. 在OKX开通模拟盘（免费）
2. 创建模拟盘API Key
3. 配置到系统
4. 运行至少7天
5. 检查数据完整性和交易逻辑
6. 确认无误后再切换实盘

### 2. 风险控制

#### 仓位管理
```python
# 推荐配置
单笔开仓：不超过账户的10%
杠杆倍数：3-5倍（不建议超过10倍）
同时持仓：不超过3个币种
```

#### 止损止盈
```python
# 必须设置止损
stop_loss = entry_price * 0.95  # 5%止损
take_profit = entry_price * 1.15  # 15%止盈

# 或基于ATR动态设置
stop_loss = entry_price - 2 * atr_14
take_profit = entry_price + 3 * atr_14
```

#### 资金管理
```python
# 总资金分配
交易资金：60%
储备资金：30%（应对极端行情）
套利资金：10%
```

### 3. 参数优化

#### 信号评分阈值

```sql
-- 保守型（高质量信号）
UPDATE system_config SET config_value = '20' WHERE config_key = 'DETECTOR_MIN_SCORE';

-- 激进型（更多信号）
UPDATE system_config SET config_value = '12' WHERE config_key = 'DETECTOR_MIN_SCORE';
```

#### RSI参数

```sql
-- 趋势型市场（减少假信号）
UPDATE system_config SET config_value = '15' WHERE config_key = 'RSI_15M_OVERSOLD';
UPDATE system_config SET config_value = '85' WHERE config_key = 'RSI_15M_OVERBOUGHT';

-- 震荡型市场（更多交易机会）
UPDATE system_config SET config_value = '25' WHERE config_key = 'RSI_15M_OVERSOLD';
UPDATE system_config SET config_value = '75' WHERE config_key = 'RSI_15M_OVERBOUGHT';
```

### 4. 数据库维护

#### 定期清理历史数据

```sql
-- 清理3个月前的15分钟K线
DELETE FROM klines_15m WHERE time < NOW() - INTERVAL '3 months';

-- 清理过期信号
DELETE FROM market_signals WHERE expire_time < NOW() - INTERVAL '7 days';

-- 清理检测快照
DELETE FROM market_detection_snapshots WHERE detected_at < NOW() - INTERVAL '30 days';
```

#### 定期VACUUM

```bash
# 手动VACUUM
psql -U qwentradeai -d qwentradeai -c "VACUUM ANALYZE;"

# 设置自动VACUUM（推荐）
# 编辑 postgresql.conf
autovacuum = on
autovacuum_vacuum_scale_factor = 0.1
autovacuum_analyze_scale_factor = 0.05
```

#### 定期备份

```bash
# 备份数据库
pg_dump -U qwentradeai -d qwentradeai -f backup_$(date +%Y%m%d).sql

# 备份配置表
psql -U qwentradeai -d qwentradeai -c "COPY system_config TO '/tmp/config_backup.csv' CSV HEADER;"

# 恢复数据库
psql -U qwentradeai -d qwentradeai -f backup_20260102.sql
```

### 5. 监控告警

#### 关键指标监控

```sql
-- 监控信号生成频率（每小时）
SELECT
    DATE_TRUNC('hour', signal_time) as hour,
    COUNT(*) as signal_count
FROM market_signals
WHERE signal_time > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', signal_time);

-- 监控交易成功率
SELECT
    position_side,
    COUNT(*) as total_trades,
    SUM(CASE WHEN action_type = 'CLOSE' THEN 1 ELSE 0 END) as closed_trades
FROM trading_relations
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY position_side;

-- 监控API请求失败率
-- （需要在代码中记录到日志或单独的统计表）
```

#### 告警设置

```python
# 推荐监控项
- 数据库连接失败
- WebSocket断线超过5分钟
- API请求失败率 > 10%
- K线数据延迟 > 30分钟
- 账户余额低于阈值
- 单日亏损超过5%
```

### 6. 代码扩展

#### 添加新币种

```sql
-- 添加BTC
UPDATE system_config SET config_value = 'ETH,BTC' WHERE config_key = 'TRADING_SYMBOLS';

-- 重启应用生效
```

#### 添加自定义指标

```python
# 在 app/components/indicator_calculator.py 添加
@staticmethod
def calculate_custom_indicator(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """计算自定义指标"""
    # 你的指标逻辑
    return custom_values

# 在 klines.py 中调用
df['custom_indicator'] = IndicatorCalculator.calculate_custom_indicator(df)
```

#### 添加自定义检测规则

```python
# 在 app/layers/market_detector.py 修改
def _custom_filter(self, kline_15m: Dict, kline_4h: Dict) -> bool:
    """自定义过滤规则"""
    # 你的逻辑
    return True  # 或 False
```

---

## 常见问题FAQ

### Q1: 系统是否使用AI模型？

**A**: 当前版本（2.0）**暂不使用AI模型**。系统基于技术指标规则引擎进行市场检测和信号生成。AI集成接口已预留，计划在未来版本中实现。

### Q2: 支持哪些交易所？

**A**: 当前仅支持 **OKX交易所**。系统使用CCXT库，理论上可扩展到其他交易所，但需要修改代码适配不同交易所的API差异。

### Q3: 支持哪些币种？

**A**: 默认支持 **ETH-USDT永续合约**。可通过配置 `TRADING_SYMBOLS` 添加其他币种（如BTC），但需要确保数据源支持该币种。

### Q4: 能否同时做多和做空？

**A**: **不能**。系统采用OKX的**单向持仓模式**，同一币种同一时间只能持有一个方向的仓位（做多或做空）。

### Q5: 信号多久会过期？

**A**: 默认 **4小时**（可通过 `DETECTOR_SIGNAL_EXPIRE_HOURS` 配置）。过期信号状态会自动变为 `EXPIRED`。

### Q6: 如何手动触发交易？

**A**: 通过API接口调用：

```bash
curl -X POST http://localhost:8000/api/trading/open \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "ETH-USDT-SWAP",
    "side": "LONG",
    "amount": 0.1,
    "leverage": 3
  }'
```

### Q7: 系统会自动止损止盈吗？

**A**: **会**。开仓时设置 `stop_loss_trigger` 和 `take_profit_trigger`，系统会自动在OKX创建条件单（algo order），价格触达时自动执行。

### Q8: 如何切换到实盘？

**A**:

```sql
-- 1. 更新配置
UPDATE system_config SET config_value = 'false' WHERE config_key = 'EXCHANGE_SANDBOX';

-- 2. 更新实盘API Key
UPDATE system_config SET config_value = '实盘API_KEY' WHERE config_key = 'EXCHANGE_API_KEY';
UPDATE system_config SET config_value = '实盘SECRET' WHERE config_key = 'EXCHANGE_SECRET';
UPDATE system_config SET config_value = '实盘PASSPHRASE' WHERE config_key = 'EXCHANGE_PASSPHRASE';

-- 3. 重启应用
```

⚠️ **切换前请务必在模拟盘充分测试！**

### Q9: 数据从哪里来？

**A**:
- **K线、资金费率、订单簿、订单/持仓历史**: OKX API
- **未平仓合约、市场情绪、ETF资金流、恐惧贪婪指数、爆仓历史**: CoinGlass API

### Q10: 系统稳定性如何？

**A**:
- ✅ 支持自动重连（WebSocket、API）
- ✅ 支持断点续传（数据同步）
- ✅ 完善的异常处理和日志记录
- ✅ 数据库连接池管理
- ⚠️ 建议使用进程守护工具（如systemd、supervisor）

### Q11: 如何回测策略？

**A**: 当前版本**不支持回测**。建议：
- 使用模拟盘测试（至少7天）
- 导出历史K线数据到其他回测平台
- 或自行开发回测模块

### Q12: 系统有风控模块吗？

**A**: 当前版本**没有独立的风控模块**。风险控制主要依赖：
- 止损止盈设置
- 仓位大小控制（手动）
- 杠杆倍数控制（手动）
- 建议自行实现账户级风控逻辑

### Q13: 如何部署到服务器？

**A**:

```bash
# 1. 服务器环境准备（Ubuntu为例）
sudo apt update
sudo apt install python3.10 python3-pip postgresql git

# 2. 克隆代码
git clone https://github.com/wangyongyuan/Qwentradesai.git
cd Qwentradesai

# 3. 安装依赖
pip3 install -r requirements.txt

# 4. 配置数据库和API

# 5. 使用systemd守护进程
sudo nano /etc/systemd/system/qwentradeai.service

# 6. 启动服务
sudo systemctl start qwentradeai
sudo systemctl enable qwentradeai  # 开机自启
```

systemd服务文件示例：
```ini
[Unit]
Description=QwenTradeAI Service
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Qwentradesai
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Q14: 日志文件过大怎么办？

**A**: 系统已配置日志自动轮转（10MB单文件，保留5个备份）。如需调整：

```python
# app/utils/logger.py
logger.add(
    "logs/qwentradeai.log",
    rotation="20 MB",  # 修改文件大小
    retention="10 days",  # 或按天数保留
    compression="zip"  # 压缩旧日志
)
```

### Q15: 如何贡献代码？

**A**:
1. Fork项目到你的GitHub
2. 创建功能分支（`git checkout -b feature/AmazingFeature`）
3. 提交更改（`git commit -m 'Add some AmazingFeature'`）
4. 推送到分支（`git push origin feature/AmazingFeature`）
5. 创建Pull Request

---

## 附录

### A. 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                       FastAPI Application                    │
│  ┌───────────────┐  ┌───────────────┐  ┌─────────────────┐ │
│  │  API Routes   │  │  Components   │  │  Trading Mgr    │ │
│  │  - Health     │  │  - K线同步    │  │  - 开平仓      │ │
│  │  - Database   │  │  - 市场检测   │  │  - 止损止盈    │ │
│  │  - Trading    │  │  - WebSocket  │  │  - 状态追踪    │ │
│  └───────────────┘  └───────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          │                                       │
┌─────────▼──────────┐                 ┌─────────▼──────────┐
│   PostgreSQL DB    │                 │   External APIs    │
│  - 16个数据表      │                 │  - OKX Exchange    │
│  - Repository层    │                 │  - CoinGlass API   │
│  - 配置管理        │                 │  - WebSocket       │
└────────────────────┘                 └────────────────────┘
```

### B. 数据流图

```
OKX API ──┐
          ├─► API Manager ─► K线同步 ─► 技术指标计算 ─► 数据库
CoinGlass ┘                     │
                                │
                                ▼
                          市场检测器
                        （三层过滤模型）
                                │
                                ▼
                           市场信号
                                │
                                ▼
                          交易管理器
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
                OKX交易                  WebSocket监控
                    │                       │
                    └───────────┬───────────┘
                                ▼
                          数据库持久化
```

### C. 技术指标速查

| 指标 | 用途 | 周期 | 阈值 |
|-----|------|------|------|
| **EMA** | 趋势判断 | 9/21/55 | - |
| **RSI** | 超买超卖 | 7(15m)/14(4h) | <20超卖, >80超买 |
| **MACD** | 动量转折 | 8-17-9(15m)/12-26-9(4h) | 柱状图穿越0轴 |
| **布林带** | 波动率 | 20周期±2倍标准差 | 宽度>平均值×0.5 |
| **ATR** | 止损参考 | 14 | - |
| **OBV** | 成交量趋势 | - | 配合EMA(9) |
| **ADX** | 趋势强度 | 14 | >25强趋势 |

### D. OKX订单类型

| 类型 | 说明 | 使用场景 |
|-----|------|---------|
| market | 市价单 | 立即成交 |
| limit | 限价单 | 指定价格挂单 |
| post_only | 只做Maker | 保证不吃单 |
| fok | 全成交或全撤销 | 大额订单 |
| ioc | 立即成交或撤销 | 限时成交 |
| trigger | 条件单（Algo Order） | 止损止盈 |

### E. 相关资源

- **OKX API文档**: https://www.okx.com/docs-v5/zh/
- **CoinGlass API文档**: https://coinglass.com/api
- **CCXT文档**: https://docs.ccxt.com/
- **FastAPI文档**: https://fastapi.tiangolo.com/
- **SQLAlchemy文档**: https://docs.sqlalchemy.org/

### F. 联系方式

- **项目地址**: https://github.com/wangyongyuan/Qwentradesai
- **问题反馈**: GitHub Issues
- **文档更新**: 2026-01-02

---

**免责声明**：本系统仅供学习和研究使用。量化交易存在风险，使用本系统进行实盘交易可能导致资金损失。使用者应自行承担所有风险，作者不承担任何责任。强烈建议在充分测试和理解系统逻辑后再进行实盘操作。

---

© 2026 QwenTradeAI. All Rights Reserved.
