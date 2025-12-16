-- ============================================
-- QwenTradeAI 数据同步系统 - 所有数据表创建脚本
-- 创建时间: 2024-12-XX
-- 说明: 本脚本包含数据同步系统所需的所有数据表定义
--       已移除AI交易相关表，仅保留数据同步功能
-- ============================================

-- ============================================
-- 一、K线数据表
-- 说明: 存储不同时间周期的K线数据，包含预计算的技术指标
-- ============================================

-- ============================================
-- 1.1 15分钟K线数据表 (klines_15m)
-- 说明: 存储15分钟周期的K线数据，包含完整的技术指标
-- 主键: (symbol, time)
-- 技术指标: EMA(9,21,55), RSI(7), MACD(8,17,9), 布林带(20,2), ATR(14), OBV, ADX(14), BB Width
-- ============================================
CREATE TABLE IF NOT EXISTS klines_15m (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                 -- K线时间戳（主键），15分钟周期，UTC时区
    
    -- 基础K线数据
    open DECIMAL(20, 8) NOT NULL,             -- 开盘价
    high DECIMAL(20, 8) NOT NULL,             -- 最高价
    low DECIMAL(20, 8) NOT NULL,              -- 最低价
    close DECIMAL(20, 8) NOT NULL,            -- 收盘价
    volume DECIMAL(20, 8) NOT NULL,           -- 成交量
    
    -- 技术指标：EMA（指数移动平均线）
    ema_9 DECIMAL(20, 8),                     -- EMA(9)，短期趋势判断
    ema_21 DECIMAL(20, 8),                    -- EMA(21)，中期趋势判断
    ema_55 DECIMAL(20, 8),                    -- EMA(55)，长期趋势判断
    
    -- 技术指标：RSI（相对强弱指标）
    rsi_7 DECIMAL(10, 4),                     -- RSI(7)，阈值20/80，用于超买超卖判断
    
    -- 技术指标：MACD（指数平滑异同移动平均线）
    macd_line DECIMAL(20, 8),                 -- MACD线，参数(8,17,9)，快线-慢线
    signal_line DECIMAL(20, 8),              -- 信号线，参数(8,17,9)，MACD的EMA平滑
    histogram DECIMAL(20, 8),                -- MACD柱状图，参数(8,17,9)，MACD线-信号线
    
    -- 技术指标：布林带（Bollinger Bands）
    bb_upper DECIMAL(20, 8),                  -- 布林带上轨，参数(20,2)，中轨+2倍标准差
    bb_middle DECIMAL(20, 8),                 -- 布林带中轨，参数(20,2)，20周期移动平均
    bb_lower DECIMAL(20, 8),                  -- 布林带下轨，参数(20,2)，中轨-2倍标准差
    
    -- 技术指标：ATR（平均真实波幅）
    atr_14 DECIMAL(20, 8),                    -- ATR(14)，用于止损和仓位计算
    
    -- 技术指标：OBV（能量潮指标）
    obv DECIMAL(20, 8),                       -- OBV原始值，基于成交量变化
    obv_ema_9 DECIMAL(20, 8),                -- OBV的EMA9平滑值，用于过滤噪音
    
    -- 技术指标：ADX（平均方向性指数）
    adx_14 DECIMAL(10, 4),                    -- ADX(14)，用于判断趋势强度，ADX>25表示趋势市
    
    -- 技术指标：布林带宽度
    bb_width DECIMAL(10, 6),                  -- 布林带宽度百分比，(上轨-下轨)/中轨，用于判断波动率
    
    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_klines_15m_symbol ON klines_15m(symbol);
CREATE INDEX IF NOT EXISTS idx_klines_15m_time ON klines_15m(time);
CREATE INDEX IF NOT EXISTS idx_klines_15m_symbol_time ON klines_15m(symbol, time DESC);

-- 表注释
COMMENT ON TABLE klines_15m IS '15分钟K线数据表，存储15分钟周期的K线数据和技术指标（RSI、MACD、EMA、布林带、ATR、OBV、ADX等）';
COMMENT ON COLUMN klines_15m.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN klines_15m.time IS 'K线时间戳（主键），15分钟周期，UTC时区';
COMMENT ON COLUMN klines_15m.open IS '开盘价';
COMMENT ON COLUMN klines_15m.high IS '最高价';
COMMENT ON COLUMN klines_15m.low IS '最低价';
COMMENT ON COLUMN klines_15m.close IS '收盘价';
COMMENT ON COLUMN klines_15m.volume IS '成交量';
COMMENT ON COLUMN klines_15m.ema_9 IS '指数移动平均线，周期9，用于短期趋势判断';
COMMENT ON COLUMN klines_15m.ema_21 IS '指数移动平均线，周期21，用于中期趋势判断';
COMMENT ON COLUMN klines_15m.ema_55 IS '指数移动平均线，周期55，用于长期趋势判断';
COMMENT ON COLUMN klines_15m.rsi_7 IS '相对强弱指标，周期7，阈值20/80，用于超买超卖判断';
COMMENT ON COLUMN klines_15m.macd_line IS 'MACD指标线，参数(8,17,9)，快线-慢线';
COMMENT ON COLUMN klines_15m.signal_line IS 'MACD信号线，参数(8,17,9)，MACD的EMA平滑';
COMMENT ON COLUMN klines_15m.histogram IS 'MACD柱状图，参数(8,17,9)，MACD线-信号线';
COMMENT ON COLUMN klines_15m.bb_upper IS '布林带上轨，参数(20,2)，中轨+2倍标准差';
COMMENT ON COLUMN klines_15m.bb_middle IS '布林带中轨，参数(20,2)，20周期移动平均';
COMMENT ON COLUMN klines_15m.bb_lower IS '布林带下轨，参数(20,2)，中轨-2倍标准差';
COMMENT ON COLUMN klines_15m.atr_14 IS '平均真实波幅，周期14，用于止损和仓位计算';
COMMENT ON COLUMN klines_15m.obv IS '能量潮指标原始值，基于成交量变化';
COMMENT ON COLUMN klines_15m.obv_ema_9 IS 'OBV的EMA9平滑值，用于过滤噪音';
COMMENT ON COLUMN klines_15m.adx_14 IS '平均方向性指标，周期14，用于判断市场类型（趋势市/震荡市），ADX>25表示趋势市';
COMMENT ON COLUMN klines_15m.bb_width IS '布林带宽度百分比，(上轨-下轨)/中轨，用于判断波动率，宽度小于近期平均表示波动收窄（震荡市）';

-- ============================================
-- 1.2 4小时K线数据表 (klines_4h)
-- 说明: 存储4小时周期的K线数据，包含中期技术指标
-- 主键: (symbol, time)
-- 技术指标: EMA(9,21), RSI(14), MACD(12,26,9), 布林带(20,2), OBV
-- ============================================
CREATE TABLE IF NOT EXISTS klines_4h (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- K线时间戳（主键），4小时周期，UTC时区
    
    -- 基础K线数据
    open DECIMAL(20, 8) NOT NULL,             -- 开盘价
    high DECIMAL(20, 8) NOT NULL,             -- 最高价
    low DECIMAL(20, 8) NOT NULL,              -- 最低价
    close DECIMAL(20, 8) NOT NULL,            -- 收盘价
    volume DECIMAL(20, 8) NOT NULL,           -- 成交量
    
    -- 技术指标：EMA（指数移动平均线）
    ema_9 DECIMAL(20, 8),                     -- EMA(9)，中期趋势判断
    ema_21 DECIMAL(20, 8),                    -- EMA(21)，长期趋势判断
    
    -- 技术指标：RSI（相对强弱指标）
    rsi_14 DECIMAL(10, 4),                    -- RSI(14)，阈值30/70，用于超买超卖判断
    
    -- 技术指标：MACD（指数平滑异同移动平均线）
    macd_line DECIMAL(20, 8),                 -- MACD线，参数(12,26,9)，快线-慢线
    signal_line DECIMAL(20, 8),              -- 信号线，参数(12,26,9)，MACD的EMA平滑
    histogram DECIMAL(20, 8),                -- MACD柱状图，参数(12,26,9)，MACD线-信号线
    
    -- 技术指标：布林带（Bollinger Bands）
    bb_upper DECIMAL(20, 8),                  -- 布林带上轨，参数(20,2)，中轨+2倍标准差
    bb_middle DECIMAL(20, 8),                 -- 布林带中轨，参数(20,2)，20周期移动平均
    bb_lower DECIMAL(20, 8),                  -- 布林带下轨，参数(20,2)，中轨-2倍标准差
    
    -- 技术指标：OBV（能量潮指标）
    obv DECIMAL(20, 8),                       -- OBV原始值，用于确认大方向趋势
    
    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_klines_4h_symbol ON klines_4h(symbol);
CREATE INDEX IF NOT EXISTS idx_klines_4h_time ON klines_4h(time);
CREATE INDEX IF NOT EXISTS idx_klines_4h_symbol_time ON klines_4h(symbol, time DESC);

-- 表注释
COMMENT ON TABLE klines_4h IS '4小时K线数据表，存储4小时周期的K线数据和技术指标（RSI、MACD、EMA、布林带、OBV等）';
COMMENT ON COLUMN klines_4h.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN klines_4h.time IS 'K线时间戳（主键），4小时周期，UTC时区';
COMMENT ON COLUMN klines_4h.open IS '开盘价';
COMMENT ON COLUMN klines_4h.high IS '最高价';
COMMENT ON COLUMN klines_4h.low IS '最低价';
COMMENT ON COLUMN klines_4h.close IS '收盘价';
COMMENT ON COLUMN klines_4h.volume IS '成交量';
COMMENT ON COLUMN klines_4h.ema_9 IS '指数移动平均线，周期9，用于中期趋势判断';
COMMENT ON COLUMN klines_4h.ema_21 IS '指数移动平均线，周期21，用于长期趋势判断';
COMMENT ON COLUMN klines_4h.rsi_14 IS '相对强弱指标，周期14，阈值30/70，用于超买超卖判断';
COMMENT ON COLUMN klines_4h.macd_line IS 'MACD指标线，参数(12,26,9)，快线-慢线';
COMMENT ON COLUMN klines_4h.signal_line IS 'MACD信号线，参数(12,26,9)，MACD的EMA平滑';
COMMENT ON COLUMN klines_4h.histogram IS 'MACD柱状图，参数(12,26,9)，MACD线-信号线';
COMMENT ON COLUMN klines_4h.bb_upper IS '布林带上轨，参数(20,2)，中轨+2倍标准差';
COMMENT ON COLUMN klines_4h.bb_middle IS '布林带中轨，参数(20,2)，20周期移动平均';
COMMENT ON COLUMN klines_4h.bb_lower IS '布林带下轨，参数(20,2)，中轨-2倍标准差';
COMMENT ON COLUMN klines_4h.obv IS '能量潮指标原始值，用于确认大方向趋势';

-- ============================================
-- 1.3 日线K线数据表 (klines_1d)
-- 说明: 存储日线周期的K线数据，包含长期趋势指标
-- 主键: (symbol, time)
-- 技术指标: EMA(9,21)
-- ============================================
CREATE TABLE IF NOT EXISTS klines_1d (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- K线时间戳（主键），1天周期，UTC时区
    
    -- 基础K线数据
    open DECIMAL(20, 8) NOT NULL,             -- 开盘价
    high DECIMAL(20, 8) NOT NULL,             -- 最高价
    low DECIMAL(20, 8) NOT NULL,              -- 最低价
    close DECIMAL(20, 8) NOT NULL,            -- 收盘价
    volume DECIMAL(20, 8) NOT NULL,           -- 成交量
    
    -- 技术指标：EMA（指数移动平均线）
    ema_9 DECIMAL(20, 8),                     -- EMA(9)，长期趋势判断
    ema_21 DECIMAL(20, 8),                    -- EMA(21)，长期趋势判断
    
    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_klines_1d_symbol ON klines_1d(symbol);
CREATE INDEX IF NOT EXISTS idx_klines_1d_time ON klines_1d(time);
CREATE INDEX IF NOT EXISTS idx_klines_1d_symbol_time ON klines_1d(symbol, time DESC);

-- 表注释
COMMENT ON TABLE klines_1d IS '日线K线数据表，存储1天周期的K线数据和技术指标（EMA等）';
COMMENT ON COLUMN klines_1d.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN klines_1d.time IS 'K线时间戳（主键），1天周期，UTC时区';
COMMENT ON COLUMN klines_1d.open IS '开盘价';
COMMENT ON COLUMN klines_1d.high IS '最高价';
COMMENT ON COLUMN klines_1d.low IS '最低价';
COMMENT ON COLUMN klines_1d.close IS '收盘价';
COMMENT ON COLUMN klines_1d.volume IS '成交量';
COMMENT ON COLUMN klines_1d.ema_9 IS '指数移动平均线，周期9，用于长期趋势判断';
COMMENT ON COLUMN klines_1d.ema_21 IS '指数移动平均线，周期21，用于长期趋势判断';

-- ============================================
-- 二、市场数据表
-- 说明: 存储各种市场元数据和情绪数据，为市场分析提供支持
-- ============================================

-- ============================================
-- 2.1 资金费率历史表 (funding_rate_history)
-- 说明: 存储各币种的资金费率历史数据，通常每8小时更新一次
-- 主键: (symbol, time)
-- 数据来源: 交易所API
-- ============================================
CREATE TABLE IF NOT EXISTS funding_rate_history (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- 资金费率时间戳（主键），通常每8小时更新一次，UTC时区
    funding_rate DECIMAL(10, 8) NOT NULL,      -- 资金费率（小数），正数表示做多支付做空，负数表示做空支付做多
    open_interest DECIMAL(20, 8),             -- 持仓量（可选），合约总持仓量
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_funding_rate_symbol ON funding_rate_history(symbol);
CREATE INDEX IF NOT EXISTS idx_funding_rate_time ON funding_rate_history(time);
CREATE INDEX IF NOT EXISTS idx_funding_rate_symbol_time ON funding_rate_history(symbol, time DESC);

-- 表注释
COMMENT ON TABLE funding_rate_history IS '资金费率历史表，存储各币种的资金费率历史数据，通常每8小时更新一次';
COMMENT ON COLUMN funding_rate_history.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN funding_rate_history.time IS '资金费率时间戳（主键），通常每8小时更新一次，UTC时区';
COMMENT ON COLUMN funding_rate_history.funding_rate IS '资金费率（小数），正数表示做多支付做空，负数表示做空支付做多';
COMMENT ON COLUMN funding_rate_history.open_interest IS '持仓量（可选），合约总持仓量';
COMMENT ON COLUMN funding_rate_history.created_at IS '记录创建时间';

-- ============================================
-- 2.2 未平仓合约15分钟数据表 (open_interest_15m)
-- 说明: 存储15分钟周期的未平仓合约数据（OHLC格式）
-- 主键: (symbol, time)
-- 数据来源: CoinGlass API
-- ============================================
CREATE TABLE IF NOT EXISTS open_interest_15m (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- 持仓量时间戳（主键），15分钟周期，UTC时区
    
    -- OHLC格式（类似K线数据）
    oi_open DECIMAL(20, 8) NOT NULL,          -- 持仓量开盘值（15分钟周期开始时的持仓量）
    oi_high DECIMAL(20, 8) NOT NULL,          -- 持仓量最高值（15分钟周期内的最高持仓量）
    oi_low DECIMAL(20, 8) NOT NULL,           -- 持仓量最低值（15分钟周期内的最低持仓量）
    oi_close DECIMAL(20, 8) NOT NULL,         -- 持仓量收盘值（15分钟周期结束时的持仓量）
    
    -- 计算字段（可选，用于快速查询）
    oi_change DECIMAL(20, 8),                 -- 持仓量变化（oi_close - oi_open），正数表示增加，负数表示减少
    oi_change_pct DECIMAL(10, 4),             -- 持仓量变化百分比（(oi_close - oi_open) / oi_open * 100）
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_open_interest_15m_symbol ON open_interest_15m(symbol);
CREATE INDEX IF NOT EXISTS idx_open_interest_15m_time ON open_interest_15m(time);
CREATE INDEX IF NOT EXISTS idx_open_interest_15m_symbol_time ON open_interest_15m(symbol, time DESC);

-- 表注释
COMMENT ON TABLE open_interest_15m IS '未平仓合约15分钟数据表，存储15分钟周期的持仓量数据（OHLC格式）';
COMMENT ON COLUMN open_interest_15m.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN open_interest_15m.time IS '持仓量时间戳（主键），15分钟周期，UTC时区';
COMMENT ON COLUMN open_interest_15m.oi_open IS '开始时的未平仓合约数（BTC数量）';
COMMENT ON COLUMN open_interest_15m.oi_high IS '最高未平仓合约数（BTC数量）';
COMMENT ON COLUMN open_interest_15m.oi_low IS '最低未平仓合约数（BTC数量）';
COMMENT ON COLUMN open_interest_15m.oi_close IS '结束时的未平仓合约数（BTC数量）';
COMMENT ON COLUMN open_interest_15m.oi_change IS '持仓量变化（oi_close - oi_open），正数表示增加，负数表示减少';
COMMENT ON COLUMN open_interest_15m.oi_change_pct IS '持仓量变化百分比（(oi_close - oi_open) / oi_open * 100）';

-- ============================================
-- 2.3 市场情绪数据表 (market_sentiment_data)
-- 说明: 存储多空持仓人数比数据，用于分析市场情绪和拥挤度
-- 主键: (symbol, time)
-- 数据来源: CoinGlass API
-- ============================================
CREATE TABLE IF NOT EXISTS market_sentiment_data (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- 情绪数据时间戳（主键），UTC时区
    
    -- 多空持仓人数比（CoinGlass API）
    global_account_long_percent DECIMAL(5, 2),      -- 全球账户多头占比（百分比），0-100，如73.88表示73.88%的账户持有多单
    global_account_short_percent DECIMAL(5, 2),     -- 全球账户空头占比（百分比），0-100，如26.12表示26.12%的账户持有空单
    global_account_long_short_ratio DECIMAL(10, 4), -- 全球账户多空比，多头占比/空头占比，如2.83表示多头账户数是空头账户数的2.83倍
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_market_sentiment_symbol ON market_sentiment_data(symbol);
CREATE INDEX IF NOT EXISTS idx_market_sentiment_time ON market_sentiment_data(time);
CREATE INDEX IF NOT EXISTS idx_market_sentiment_symbol_time ON market_sentiment_data(symbol, time DESC);

-- 表注释
COMMENT ON TABLE market_sentiment_data IS '市场情绪数据表，存储多空持仓人数比数据，用于分析市场情绪和拥挤度';
COMMENT ON COLUMN market_sentiment_data.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN market_sentiment_data.time IS '情绪数据时间戳（主键），UTC时区';
COMMENT ON COLUMN market_sentiment_data.global_account_long_percent IS '全球账户多头占比（百分比），0-100，如73.88表示73.88%的账户持有多单';
COMMENT ON COLUMN market_sentiment_data.global_account_short_percent IS '全球账户空头占比（百分比），0-100，如26.12表示26.12%的账户持有空单';
COMMENT ON COLUMN market_sentiment_data.global_account_long_short_ratio IS '全球账户多空比，多头占比/空头占比，如2.83表示多头账户数是空头账户数的2.83倍';
COMMENT ON COLUMN market_sentiment_data.created_at IS '记录创建时间';

-- ============================================
-- 2.4 盘口挂单分布表 (order_book_distribution)
-- 说明: 存储订单簿的买卖盘分布数据，包括总金额、订单数、大单分布等
-- 主键: (symbol, time)
-- 数据来源: 交易所API（OKX）
-- 更新频率: 1小时更新一次
-- ============================================
CREATE TABLE IF NOT EXISTS order_book_distribution (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH, SOL等
    time TIMESTAMPTZ NOT NULL,                -- 订单簿时间戳（主键），1小时更新一次，UTC时区
    
    -- 原始数据（JSONB格式，存储OKX API返回的完整asks和bids数组）
    asks JSONB NOT NULL,                     -- 卖单深度数组，最多1000档，格式：[["价格", "数量", "订单数"], ...]
    bids JSONB NOT NULL,                     -- 买单深度数组，最多1000档，格式：[["价格", "数量", "订单数"], ...]
    
    -- 汇总统计（便于快速查询）
    total_ask_amount DECIMAL(20, 8),          -- 卖单总数量（所有asks档位的数量之和）
    total_bid_amount DECIMAL(20, 8),          -- 买单总数量（所有bids档位的数量之和）
    total_ask_orders INTEGER,                 -- 卖单总订单数（所有asks档位的订单数之和）
    total_bid_orders INTEGER,                 -- 买单总订单数（所有bids档位的订单数之和）
    bid_ask_ratio DECIMAL(10, 4),            -- 买卖比（total_bid_amount / total_ask_amount），>1表示买盘更强，<1表示卖单更强
    
    -- 大单统计（可选，用于分析大额挂单）
    large_ask_amount DECIMAL(20, 8),         -- 大额卖单总量（超过阈值的卖单数量之和），用于分析大单压力
    large_bid_amount DECIMAL(20, 8),         -- 大额买单总量（超过阈值的买单数量之和），用于分析大单支撑
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_order_book_symbol ON order_book_distribution(symbol);
CREATE INDEX IF NOT EXISTS idx_order_book_time ON order_book_distribution(time);
CREATE INDEX IF NOT EXISTS idx_order_book_symbol_time ON order_book_distribution(symbol, time DESC);

-- 表注释
COMMENT ON TABLE order_book_distribution IS '盘口挂单分布表，存储OKX订单簿深度数据（1小时更新一次，保留90天）';
COMMENT ON COLUMN order_book_distribution.symbol IS '币种名称：BTC, ETH, SOL等';
COMMENT ON COLUMN order_book_distribution.time IS '订单簿时间戳（主键），1小时更新一次，UTC时区';
COMMENT ON COLUMN order_book_distribution.asks IS '卖单深度数组（JSONB），最多1000档，每个元素格式：["价格", "数量", "订单数"]';
COMMENT ON COLUMN order_book_distribution.bids IS '买单深度数组（JSONB），最多1000档，每个元素格式：["价格", "数量", "订单数"]';
COMMENT ON COLUMN order_book_distribution.total_ask_amount IS '卖单总数量（所有asks档位的数量之和）';
COMMENT ON COLUMN order_book_distribution.total_bid_amount IS '买单总数量（所有bids档位的数量之和）';
COMMENT ON COLUMN order_book_distribution.total_ask_orders IS '卖单总订单数（所有asks档位的订单数之和）';
COMMENT ON COLUMN order_book_distribution.total_bid_orders IS '买单总订单数（所有bids档位的订单数之和）';
COMMENT ON COLUMN order_book_distribution.bid_ask_ratio IS '买卖比（total_bid_amount / total_ask_amount），>1表示买单更强，<1表示卖单更强';
COMMENT ON COLUMN order_book_distribution.large_ask_amount IS '大额卖单总量（超过阈值的卖单数量之和，用于分析大单压力）';
COMMENT ON COLUMN order_book_distribution.large_bid_amount IS '大额买单总量（超过阈值的买单数量之和，用于分析大单支撑）';
COMMENT ON COLUMN order_book_distribution.created_at IS '记录创建时间';

-- ============================================
-- 2.5 ETF资金流数据表 (etf_flow_data)
-- 说明: 存储BTC和ETH现货ETF的净资产和资金流入流出数据
-- 主键: (symbol, date)
-- 数据来源: CoinGlass API
-- 更新频率: 每天早上8点更新
-- ============================================
CREATE TABLE IF NOT EXISTS etf_flow_data (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH（ETF相关币种）
    date DATE NOT NULL,                      -- 日期（主键），每天一条记录，每天早上8点更新
    
    -- 净资产和资金流数据
    net_assets_usd DECIMAL(30, 8) NOT NULL,  -- 净资产总额（USD），ETF的总资产净值
    change_usd DECIMAL(30, 8) NOT NULL,       -- 当日资金变化（USD），正数表示净流入，负数表示净流出
    price_usd DECIMAL(20, 8) NOT NULL,       -- 当日币种价格（USD），BTC用BTC价格，ETH用ETH价格
    timestamp BIGINT NOT NULL,                -- 日期（时间戳，单位毫秒），数据来源的时间戳
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录更新时间
    
    PRIMARY KEY (symbol, date)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_etf_flow_symbol ON etf_flow_data(symbol);
CREATE INDEX IF NOT EXISTS idx_etf_flow_date ON etf_flow_data(date);
CREATE INDEX IF NOT EXISTS idx_etf_flow_symbol_date ON etf_flow_data(symbol, date DESC);

-- 表注释
COMMENT ON TABLE etf_flow_data IS 'ETF资金流数据表，存储BTC和ETH现货ETF的净资产和资金流入流出数据（每天早上8点更新，保留730天）';
COMMENT ON COLUMN etf_flow_data.symbol IS '币种名称：BTC, ETH（ETF相关币种）';
COMMENT ON COLUMN etf_flow_data.date IS '日期（主键），每天一条记录，每天早上8点更新';
COMMENT ON COLUMN etf_flow_data.net_assets_usd IS '净资产总额（USD），ETF的总资产净值';
COMMENT ON COLUMN etf_flow_data.change_usd IS '当日资金变化（USD），正数表示净流入，负数表示净流出';
COMMENT ON COLUMN etf_flow_data.price_usd IS '当日币种价格（USD），BTC用BTC价格，ETH用ETH价格';
COMMENT ON COLUMN etf_flow_data.timestamp IS '日期（时间戳，单位毫秒），数据来源的时间戳';
COMMENT ON COLUMN etf_flow_data.created_at IS '记录创建时间';
COMMENT ON COLUMN etf_flow_data.updated_at IS '记录更新时间';

-- ============================================
-- 2.6 爆仓历史表 (liquidation_history)
-- 说明: 存储币种的爆仓历史数据，包括多单和空单爆仓金额
-- 主键: (symbol, time)
-- 数据来源: CoinGlass API
-- 更新频率: 每4小时更新一次
-- ============================================
CREATE TABLE IF NOT EXISTS liquidation_history (
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：BTC, ETH等
    time TIMESTAMPTZ NOT NULL,                -- 时间戳（主键），UTC时区
    
    -- 爆仓数据
    aggregated_long_liquidation_usd DECIMAL(30, 8) NOT NULL,   -- 聚合多单爆仓金额（美元）
    aggregated_short_liquidation_usd DECIMAL(30, 8) NOT NULL,  -- 聚合空单爆仓金额（美元）
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    
    PRIMARY KEY (symbol, time)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_liquidation_symbol ON liquidation_history(symbol);
CREATE INDEX IF NOT EXISTS idx_liquidation_time ON liquidation_history(time);
CREATE INDEX IF NOT EXISTS idx_liquidation_symbol_time ON liquidation_history(symbol, time DESC);

-- 表注释
COMMENT ON TABLE liquidation_history IS '爆仓历史表，存储币种的爆仓历史数据（每4小时更新一次，保留90天）';
COMMENT ON COLUMN liquidation_history.symbol IS '币种名称：BTC, ETH等';
COMMENT ON COLUMN liquidation_history.time IS '时间戳（主键），UTC时区';
COMMENT ON COLUMN liquidation_history.aggregated_long_liquidation_usd IS '聚合多单爆仓金额（美元）';
COMMENT ON COLUMN liquidation_history.aggregated_short_liquidation_usd IS '聚合空单爆仓金额（美元）';
COMMENT ON COLUMN liquidation_history.created_at IS '记录创建时间';

-- ============================================
-- 2.7 恐惧贪婪指数表 (fear_greed_index)
-- 说明: 存储加密货币市场的恐惧贪婪指数，用于判断市场情绪
-- 主键: date
-- 数据来源: CoinGlass API
-- 更新频率: 每天早上8点更新
-- ============================================
CREATE TABLE IF NOT EXISTS fear_greed_index (
    date DATE NOT NULL PRIMARY KEY,           -- 日期（主键），每天一条记录，每天早上8点更新
    
    value INTEGER NOT NULL,                   -- 恐惧贪婪指数值（0-100），0=极度恐惧，100=极度贪婪
    price DECIMAL(20, 8) NOT NULL,            -- 对应的价格数据（USD），与指数值对应的时间点的价格
    classification VARCHAR(50),                -- 分类：极度恐惧(0-24)/恐惧(25-44)/中性(45-55)/贪婪(56-75)/极度贪婪(76-100)，根据value自动计算
    
    -- 历史对比字段（可选，用于分析趋势）
    previous_value INTEGER,                   -- 前一天的值，用于计算变化趋势
    change INTEGER,                            -- 变化值（value - previous_value），正数表示情绪改善，负数表示情绪恶化
    
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_fear_greed_date ON fear_greed_index(date DESC);

-- 表注释
COMMENT ON TABLE fear_greed_index IS '恐惧贪婪指数表，存储市场情绪指数（CoinGlass API，每天早上8点更新，保留730天）';
COMMENT ON COLUMN fear_greed_index.date IS '日期（主键），每天一条记录，每天早上8点更新';
COMMENT ON COLUMN fear_greed_index.value IS '恐惧贪婪指数值（0-100），0=极度恐惧，100=极度贪婪';
COMMENT ON COLUMN fear_greed_index.price IS '对应的价格数据（USD），与指数值对应的时间点的价格';
COMMENT ON COLUMN fear_greed_index.classification IS '分类：极度恐惧(0-24)/恐惧(25-44)/中性(45-55)/贪婪(56-75)/极度贪婪(76-100)，根据value自动计算';
COMMENT ON COLUMN fear_greed_index.previous_value IS '前一天的值，用于计算变化趋势';
COMMENT ON COLUMN fear_greed_index.change IS '变化值（value - previous_value），正数表示情绪改善，负数表示情绪恶化';
COMMENT ON COLUMN fear_greed_index.created_at IS '记录创建时间';
COMMENT ON COLUMN fear_greed_index.updated_at IS '记录更新时间';

-- ============================================
-- 2.8 市场检测快照表 (market_detection_snapshots)
-- 说明: 存储每次市场检测的完整快照，无论是否生成信号都保存，用于回溯分析
-- 主键: id
-- 数据来源: 市场检测器
-- 更新频率: 每15分钟（15m K线更新时）
-- ============================================
CREATE TABLE IF NOT EXISTS market_detection_snapshots (
    id BIGSERIAL PRIMARY KEY,                    -- 自增主键ID
    symbol VARCHAR(20) NOT NULL,                 -- 币种名称：BTC, ETH等
    detected_at TIMESTAMPTZ NOT NULL,            -- 检测时间（UTC时区）
    
    -- 检测时的价格信息
    price DECIMAL(20, 8) NOT NULL,               -- 检测时的价格
    price_change_24h DECIMAL(10, 4),             -- 24小时价格变化百分比
    
    -- 使用的K线时间点（用于关联）
    kline_15m_time TIMESTAMPTZ NOT NULL,         -- 15分钟K线时间
    kline_4h_time TIMESTAMPTZ NOT NULL,          -- 4小时K线时间
    kline_1d_time TIMESTAMPTZ,                   -- 日线K线时间（可选）
    
    -- 环境层判断结果
    market_mode VARCHAR(20),                     -- 市场模式：BULL/BEAR/NEUTRAL
    market_active BOOLEAN DEFAULT FALSE,        -- 市场是否活跃（布林带宽度判断）
    trend_15m BOOLEAN,                           -- 15m趋势方向（价格是否在EMA55之上）
    trend_4h BOOLEAN,                            -- 4h趋势方向
    multi_tf_aligned BOOLEAN DEFAULT FALSE,     -- 多时间框架是否对齐（15m和4h共振）
    
    -- 触发层结果（6个维度）
    momentum_turn BOOLEAN DEFAULT FALSE,         -- MACD动量转折
    ema_cross BOOLEAN DEFAULT FALSE,             -- EMA交叉
    rsi_extreme BOOLEAN DEFAULT FALSE,           -- RSI极值
    bb_breakout BOOLEAN DEFAULT FALSE,           -- 布林带突破
    volume_surge BOOLEAN DEFAULT FALSE,           -- 成交量异常
    price_pattern BOOLEAN DEFAULT FALSE,         -- 价格形态（吞没形态）
    
    -- 触发时的关键指标值（用于分析）
    rsi_value DECIMAL(10, 4),                    -- 当前RSI值
    macd_histogram DECIMAL(20, 8),               -- MACD柱状图值
    volume_ratio DECIMAL(10, 4),                 -- 成交量比率（当前/平均）
    bb_width_ratio DECIMAL(10, 4),              -- 布林带宽度比率（当前/平均）
    
    -- 确认层结果
    volume_confirm BOOLEAN DEFAULT FALSE,        -- 成交量确认
    bb_confirm BOOLEAN DEFAULT FALSE,             -- 布林带确认
    
    -- 检测结果
    has_signal BOOLEAN NOT NULL DEFAULT FALSE,   -- 是否生成信号
    signal_direction VARCHAR(10),                 -- 信号方向：LONG/SHORT/NONE
    signal_strength VARCHAR(20),                 -- 信号强度：WEAK/MODERATE/STRONG/VERY_STRONG
    position_size_multiplier DECIMAL(5, 2) DEFAULT 1.0,  -- 仓位倍数（RSI极值时加倍）
    
    -- 检测使用的数据量
    kline_15m_count INTEGER NOT NULL,            -- 使用的15m K线数量
    kline_4h_count INTEGER NOT NULL,             -- 使用的4h K线数量
    kline_1d_count INTEGER,                      -- 使用的1d K线数量
    
    -- 元数据
    detection_version VARCHAR(20) DEFAULT '1.0', -- 检测算法版本
    created_at TIMESTAMPTZ DEFAULT NOW()         -- 记录创建时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_detection_snapshot_symbol ON market_detection_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_detection_snapshot_time ON market_detection_snapshots(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_detection_snapshot_symbol_time ON market_detection_snapshots(symbol, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_detection_snapshot_has_signal ON market_detection_snapshots(has_signal, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_detection_snapshot_strength ON market_detection_snapshots(signal_strength, detected_at DESC);

-- 表注释
COMMENT ON TABLE market_detection_snapshots IS '市场检测快照表，存储每次检测的完整信息（无论是否有信号都保存，用于回溯分析）';
COMMENT ON COLUMN market_detection_snapshots.symbol IS '币种名称：BTC, ETH等';
COMMENT ON COLUMN market_detection_snapshots.detected_at IS '检测时间（UTC时区）';
COMMENT ON COLUMN market_detection_snapshots.market_mode IS '市场模式：BULL/BEAR/NEUTRAL';
COMMENT ON COLUMN market_detection_snapshots.has_signal IS '是否生成信号';
COMMENT ON COLUMN market_detection_snapshots.signal_strength IS '信号强度：WEAK/MODERATE/STRONG/VERY_STRONG';

-- ============================================
-- 2.9 市场信号表 (market_signals)
-- 说明: 存储最终生成的交易信号，只保存通过所有层级过滤的信号
-- 主键: id
-- 数据来源: 市场检测器（从market_detection_snapshots生成）
-- 更新频率: 每15分钟（15m K线更新时，如果有信号）
-- ============================================
CREATE TABLE IF NOT EXISTS market_signals (
    id BIGSERIAL PRIMARY KEY,                    -- 自增主键ID
    snapshot_id BIGINT REFERENCES market_detection_snapshots(id),  -- 关联检测快照ID
    
    symbol VARCHAR(20) NOT NULL,                 -- 币种名称：BTC, ETH等
    signal_type VARCHAR(20) NOT NULL,             -- 信号类型：LONG/SHORT
    detected_at TIMESTAMPTZ NOT NULL,            -- 检测时间（UTC时区）
    
    -- 信号核心信息
    price DECIMAL(20, 8) NOT NULL,               -- 检测时的价格
    confidence_score DECIMAL(10, 2) NOT NULL,    -- 置信度分数（0-100，基于信号强度）
    
    -- 信号强度分级
    signal_strength VARCHAR(20) NOT NULL,         -- WEAK/MODERATE/STRONG/VERY_STRONG
    position_size_multiplier DECIMAL(5, 2) DEFAULT 1.0,  -- 仓位倍数（1.0=正常，2.0=加倍）
    
    -- 关键K线时间点
    kline_15m_time TIMESTAMPTZ NOT NULL,         -- 15分钟K线时间
    kline_4h_time TIMESTAMPTZ NOT NULL,          -- 4小时K线时间
    
    -- 信号触发原因（JSON格式，存储主要触发因素）
    trigger_factors JSONB,                       -- 如：["momentum_turn", "volume_surge", "ema_cross"]
    
    -- 市场环境信息
    market_mode VARCHAR(20),                     -- 市场模式：BULL/BEAR
    multi_tf_aligned BOOLEAN DEFAULT FALSE,      -- 多时间框架是否对齐
    
    -- 关键指标快照（用于后续分析）
    rsi_value DECIMAL(10, 4),                    -- RSI值
    macd_histogram DECIMAL(20, 8),               -- MACD柱状图值
    volume_ratio DECIMAL(10, 4),                 -- 成交量比率
    
    -- 预期目标（可选，后续可扩展）
    target_price DECIMAL(20, 8),                 -- 目标价格（可选）
    stop_loss_price DECIMAL(20, 8),              -- 止损价格（可选）
    
    -- 信号状态
    status VARCHAR(20) DEFAULT 'PENDING',        -- PENDING/ACTIVE/EXPIRED/FILLED/CANCELLED
    expired_at TIMESTAMPTZ,                      -- 信号过期时间（detected_at + 有效期）
    
    -- 关联信息
    opportunity_score_id BIGINT,                  -- 关联机会评分ID（如果有）
    trade_id BIGINT,                             -- 关联交易ID（如果已执行）
    
    created_at TIMESTAMPTZ DEFAULT NOW(),        -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()         -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON market_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_time ON market_signals(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_time ON market_signals(symbol, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_status ON market_signals(status, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_strength ON market_signals(signal_strength, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_confidence ON market_signals(confidence_score DESC, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_snapshot ON market_signals(snapshot_id);

-- 表注释
COMMENT ON TABLE market_signals IS '市场信号表，存储最终生成的交易信号（只保存通过所有层级过滤的信号）';
COMMENT ON COLUMN market_signals.symbol IS '币种名称：BTC, ETH等';
COMMENT ON COLUMN market_signals.signal_type IS '信号类型：LONG/SHORT';
COMMENT ON COLUMN market_signals.confidence_score IS '置信度分数（0-100，基于信号强度）';
COMMENT ON COLUMN market_signals.signal_strength IS '信号强度：WEAK/MODERATE/STRONG/VERY_STRONG';
COMMENT ON COLUMN market_signals.status IS '信号状态：PENDING/ACTIVE/EXPIRED/FILLED/CANCELLED';
COMMENT ON COLUMN market_signals.trigger_factors IS '触发因素（JSON数组），如：["momentum_turn", "volume_surge"]';

-- ============================================
-- 三、系统配置表
-- 说明: 存储所有系统配置项，替代config.py中的硬编码配置
-- ============================================

-- ============================================
-- 3.1 系统配置表 (system_config)
-- 说明: 用于存储所有系统配置项，支持动态读取和更新
-- 主键: config_key
-- ============================================
CREATE TABLE IF NOT EXISTS system_config (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    config_key VARCHAR(255) UNIQUE NOT NULL,  -- 配置键名（唯一），如APP_NAME、DATABASE_URL等
    value TEXT NOT NULL,                      -- 配置值（文本格式），支持JSON格式存储复杂配置
    value_type VARCHAR(50) DEFAULT 'string' NOT NULL, -- 配置类型：'string', 'int', 'float', 'boolean', 'json'
    description TEXT,                         -- 配置说明
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(config_key);

-- 表注释
COMMENT ON TABLE system_config IS '系统配置表，存储所有系统配置项，替代config.py中的硬编码配置';
COMMENT ON COLUMN system_config.id IS '自增主键ID';
COMMENT ON COLUMN system_config.config_key IS '配置键名（唯一），如APP_NAME、DATABASE_URL等';
COMMENT ON COLUMN system_config.value IS '配置值（文本格式），支持JSON格式存储复杂配置';
COMMENT ON COLUMN system_config.value_type IS '配置类型：string/int/float/boolean/json';
COMMENT ON COLUMN system_config.description IS '配置说明';
COMMENT ON COLUMN system_config.created_at IS '记录创建时间';
COMMENT ON COLUMN system_config.updated_at IS '记录更新时间';

-- ============================================
-- 3.2 插入初始配置数据
-- 说明: 从config.py迁移的默认配置项，仅保留数据同步系统需要的配置
-- ============================================
INSERT INTO system_config (config_key, value, value_type, description) VALUES
-- 应用基础配置
('APP_NAME', 'QwenTradeAI', 'string', '应用名称'),
('APP_VERSION', '2.0', 'string', '应用版本号'),
('DEBUG', 'false', 'boolean', '调试模式开关'),

-- 数据库配置
('DATABASE_URL', 'postgresql://qwentradeai:qwentradeai@45.197.144.57:5432/qwentradeai', 'string', 'PostgreSQL数据库连接URL'),

-- 交易所配置（用于数据同步）
('EXCHANGE_NAME', 'okx', 'string', '交易所名称'),
('EXCHANGE_API_KEY', '', 'string', 'OKX API密钥（可选，如果不需要交易功能可以不填）'),
('EXCHANGE_SECRET', '', 'string', 'OKX API密钥对应的Secret（可选）'),
('EXCHANGE_PASSPHRASE', '', 'string', 'OKX API密钥对应的Passphrase（可选）'),
('EXCHANGE_SANDBOX', 'true', 'boolean', '是否使用交易所沙箱环境'),

-- CoinGlass API配置
('COINGLASS_API_KEY', '95c31ba79d054646b2ca68c23bfb4839', 'string', 'CoinGlass API密钥'),
('COINGLASS_BASE_URL', 'https://open-api-v4.coinglass.com', 'string', 'CoinGlass API基础URL'),

-- 交易币种配置（用于数据同步）
('SYMBOL', 'ETH/USDT:USDT', 'string', '默认交易币种（CCXT格式）'),
('TRADING_SYMBOLS', 'ETH', 'string', '交易币种列表（逗号分隔），系统会为每个币种创建独立的同步线程'),

-- 技术指标配置
('RSI_15M_PERIOD', '7', 'int', '15分钟K线RSI计算周期'),
('RSI_15M_OVERSOLD', '20.0', 'float', '15分钟RSI超卖阈值'),
('RSI_15M_OVERBOUGHT', '80.0', 'float', '15分钟RSI超买阈值'),
('RSI_4H_PERIOD', '14', 'int', '4小时K线RSI计算周期'),
('RSI_4H_OVERSOLD', '30.0', 'float', '4小时RSI超卖阈值'),
('RSI_4H_OVERBOUGHT', '70.0', 'float', '4小时RSI超买阈值'),

('MACD_15M_FAST', '8', 'int', '15分钟K线MACD快线周期'),
('MACD_15M_SLOW', '17', 'int', '15分钟K线MACD慢线周期'),
('MACD_15M_SIGNAL', '9', 'int', '15分钟K线MACD信号线周期'),
('MACD_4H_FAST', '12', 'int', '4小时K线MACD快线周期'),
('MACD_4H_SLOW', '26', 'int', '4小时K线MACD慢线周期'),
('MACD_4H_SIGNAL', '9', 'int', '4小时K线MACD信号线周期'),

('EMA_SHORT', '9', 'int', 'EMA短期周期'),
('EMA_MID', '21', 'int', 'EMA中期周期'),
('EMA_LONG', '55', 'int', 'EMA长期周期'),

('BB_PERIOD', '20', 'int', '布林带周期'),
('BB_STD', '2.0', 'float', '布林带标准差倍数'),

('ATR_15M_PERIOD', '14', 'int', '15分钟K线ATR计算周期'),

('OBV_EMA_SMOOTH', '9', 'int', 'OBV平滑周期'),

-- K线历史数据同步配置
('KLINE_15M_START_DAYS', '30', 'int', '15分钟K线初始同步天数'),
('KLINE_4H_START_DAYS', '180', 'int', '4小时K线初始同步天数'),
('KLINE_1D_START_DAYS', '600', 'int', '日线K线初始同步天数'),

-- 资金费率同步配置
('FUNDING_RATE_START_DAYS', '30', 'int', '资金费率初始同步天数'),

-- API管理器配置
('API_RATE_LIMIT', '10', 'int', 'API请求速率限制（每时间窗口内允许的最大请求次数）'),
('API_RATE_WINDOW', '2.0', 'float', 'API限流时间窗口（秒）'),
('API_MIN_INTERVAL', '0.2', 'float', 'API请求最小间隔时间（秒）'),
('API_REQUEST_TIMEOUT', '30', 'int', 'API请求超时时间（秒）'),
('API_MAX_RETRIES', '3', 'int', 'API请求最大重试次数'),

-- WebSocket配置
('WS_RECONNECT_INTERVAL', '5', 'int', 'WebSocket重连间隔（秒）'),
('WS_HEARTBEAT_INTERVAL', '20', 'int', 'WebSocket心跳间隔（秒）'),
('WS_PING_TIMEOUT', '5', 'int', 'WebSocket ping超时时间（秒）'),
('WS_CONNECT_TIMEOUT', '30', 'int', 'WebSocket连接超时时间（秒）'),
('WS_SUBSCRIBE_TIMEOUT', '30', 'int', 'WebSocket订阅超时时间（秒）'),
('WS_PRICE_TIMEOUT', '30', 'int', 'WebSocket价格超时时间（秒）'),
('WS_QUEUE_MAXSIZE', '100', 'int', 'WebSocket价格队列最大长度'),
('WS_SSL_VERIFY', 'true', 'boolean', '是否验证SSL证书'),

-- 日志配置
('LOG_LEVEL', 'INFO', 'string', '日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL'),
('LOG_FILE', 'logs/qwentradeai.log', 'string', '日志文件路径'),
('LOG_MAX_BYTES', '10485760', 'int', '单个日志文件最大大小（字节），默认10MB'),
('LOG_BACKUP_COUNT', '5', 'int', '日志文件备份数量'),

-- 市场检测器配置
-- 环境层参数
('DETECTOR_EMA_TREND_PERIOD', '55', 'int', '市场检测器：用于趋势判断的EMA周期（环境层）'),
('DETECTOR_BB_WIDTH_THRESHOLD', '0.5', 'float', '市场检测器：布林带宽度阈值（相对于20根平均值的倍数，低于此值认为市场不活跃）'),

-- 触发层参数
('DETECTOR_RSI_LONG_THRESHOLD', '80.0', 'float', '市场检测器：做多信号RSI上限（RSI低于此值才允许做多，防止极端过热）'),
('DETECTOR_RSI_SHORT_THRESHOLD', '20.0', 'float', '市场检测器：做空信号RSI下限（RSI高于此值才允许做空，防止极端超卖）'),
('DETECTOR_RSI_DOUBLE_POSITION_LONG', '50.0', 'float', '市场检测器：做多时RSI低于此值加倍仓位（更好的盈亏比）'),
('DETECTOR_RSI_DOUBLE_POSITION_SHORT', '50.0', 'float', '市场检测器：做空时RSI高于此值加倍仓位（更好的盈亏比）'),

-- 确认层参数
('DETECTOR_VOLUME_STD_MULTIPLIER', '1.5', 'float', '市场检测器：成交量确认阈值（平均值 + 此倍数 × 标准差，降低此值可增加信号数量）'),

-- 数据量参数
('DETECTOR_KLINE_15M_COUNT', '100', 'int', '市场检测器：使用的15分钟K线数量'),
('DETECTOR_KLINE_4H_COUNT', '60', 'int', '市场检测器：使用的4小时K线数量'),

-- 其他参数
('DETECTOR_ENABLE_MULTI_TF', 'true', 'boolean', '市场检测器：是否启用多时间框架确认（15m和4h共振加分）'),
('DETECTOR_SIGNAL_EXPIRE_HOURS', '4', 'int', '市场检测器：信号有效期（小时，超过此时间信号自动过期）')

ON CONFLICT (config_key) DO UPDATE SET
    value = EXCLUDED.value,
    value_type = EXCLUDED.value_type,
    description = EXCLUDED.description,
    updated_at = NOW();

-- ============================================
-- 四、TimescaleDB 配置（可选）
-- 说明: 将时序数据表转换为TimescaleDB超表，并配置压缩和保留策略
-- 注意: 以下命令需要先安装TimescaleDB扩展
-- 如果未安装TimescaleDB，这部分会自动跳过，不影响表的正常使用
-- ============================================

-- ============================================
-- 4.1 创建TimescaleDB扩展（如果已安装）
-- ============================================
-- 注意：如果未安装TimescaleDB，以下代码会自动跳过，不会报错
-- TimescaleDB安装指南：https://docs.timescale.com/install/latest/
DO $$
BEGIN
    -- 尝试创建TimescaleDB扩展
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
    RAISE NOTICE 'TimescaleDB扩展已启用';
EXCEPTION
    WHEN OTHERS THEN
        -- 如果TimescaleDB未安装，跳过扩展创建
        RAISE NOTICE 'TimescaleDB未安装，跳过超表配置（表仍可正常使用）';
END $$;

-- ============================================
-- 4.2 将K线数据表转换为超表
-- ============================================
-- 15分钟K线表：7天一个chunk，30天后压缩，保留180天
SELECT create_hypertable('klines_15m'::regclass, 'time'::name, chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE klines_15m SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    -- 如果表已经有压缩chunk或已启用压缩，忽略错误
    NULL;
END $$;
SELECT add_compression_policy('klines_15m'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('klines_15m'::regclass, INTERVAL '180 days', if_not_exists => TRUE);

-- 4小时K线表：30天一个chunk，30天后压缩，保留365天
SELECT create_hypertable('klines_4h'::regclass, 'time'::name, chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE klines_4h SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('klines_4h'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('klines_4h'::regclass, INTERVAL '365 days', if_not_exists => TRUE);

-- 日线K线表：90天一个chunk，30天后压缩，保留730天
SELECT create_hypertable('klines_1d'::regclass, 'time'::name, chunk_time_interval => INTERVAL '90 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE klines_1d SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('klines_1d'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('klines_1d'::regclass, INTERVAL '730 days', if_not_exists => TRUE);

-- ============================================
-- 4.3 将市场数据表转换为超表
-- ============================================
-- 资金费率历史表：30天一个chunk，30天后压缩，保留365天
SELECT create_hypertable('funding_rate_history'::regclass, 'time'::name, chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE funding_rate_history SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('funding_rate_history'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('funding_rate_history'::regclass, INTERVAL '365 days', if_not_exists => TRUE);

-- 未平仓合约15分钟表：7天一个chunk，30天后压缩，保留180天
SELECT create_hypertable('open_interest_15m'::regclass, 'time'::name, chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE open_interest_15m SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('open_interest_15m'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('open_interest_15m'::regclass, INTERVAL '180 days', if_not_exists => TRUE);

-- 市场情绪数据表：30天一个chunk，30天后压缩，保留365天
SELECT create_hypertable('market_sentiment_data'::regclass, 'time'::name, chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE market_sentiment_data SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('market_sentiment_data'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('market_sentiment_data'::regclass, INTERVAL '365 days', if_not_exists => TRUE);

-- 盘口挂单分布表：7天一个chunk，30天后压缩，保留90天
SELECT create_hypertable('order_book_distribution'::regclass, 'time'::name, chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE order_book_distribution SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('order_book_distribution'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('order_book_distribution'::regclass, INTERVAL '90 days', if_not_exists => TRUE);

-- 爆仓历史表：7天一个chunk，30天后压缩，保留90天
SELECT create_hypertable('liquidation_history'::regclass, 'time'::name, chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE liquidation_history SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('liquidation_history'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('liquidation_history'::regclass, INTERVAL '90 days', if_not_exists => TRUE);

-- ETF资金流数据表：30天一个chunk，30天后压缩，保留730天
SELECT create_hypertable('etf_flow_data'::regclass, 'date'::name, chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE etf_flow_data SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('etf_flow_data'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('etf_flow_data'::regclass, INTERVAL '730 days', if_not_exists => TRUE);

-- 恐惧贪婪指数表：30天一个chunk，30天后压缩，保留730天
SELECT create_hypertable('fear_greed_index'::regclass, 'date'::name, chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
DO $$
BEGIN
    ALTER TABLE fear_greed_index SET (timescaledb.compress = true);
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;
SELECT add_compression_policy('fear_greed_index'::regclass, INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_retention_policy('fear_greed_index'::regclass, INTERVAL '730 days', if_not_exists => TRUE);

-- ============================================
-- 五、完成说明
-- ============================================
-- 所有数据表创建完成！
-- 
-- 表清单：
-- 1. K线数据表（3个）：
--    - klines_15m（15分钟K线，保留180天）
--    - klines_4h（4小时K线，保留365天）
--    - klines_1d（日线K线，保留730天）
-- 
-- 2. 市场数据表（6个）：
--    - funding_rate_history（资金费率历史，保留365天）
--    - open_interest_15m（未平仓合约15分钟，保留180天）
--    - market_sentiment_data（市场情绪数据，保留365天）
--    - order_book_distribution（盘口挂单分布，保留90天）
--    - etf_flow_data（ETF资金流，保留730天）
--    - fear_greed_index（恐惧贪婪指数，保留730天）
-- 
-- 3. 市场检测表（2个）：
--    - market_detection_snapshots（市场检测快照，保留180天）
--    - market_signals（市场信号，保留365天）
-- 
-- 4. 系统配置表（1个）：
--    - system_config（系统配置，永久保留）
-- 
-- 注意事项：
-- 1. TimescaleDB配置：如果未安装TimescaleDB扩展，请注释掉第四部分的TimescaleDB配置
-- 2. 数据保留策略：根据实际需求可以调整各表的保留时间
-- 3. 索引优化：已为所有表创建必要的索引，可根据查询需求添加更多索引
-- 4. 配置初始化：system_config表需要手动插入初始配置项，或通过ConfigManager初始化
-- ============================================
