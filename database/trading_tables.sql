-- ============================================
-- QwenTradeAI AI量化交易系统 - 交易相关数据表
-- 创建时间: 2024-12-15
-- 说明: 本脚本包含AI量化交易系统所需的所有交易相关表
--       包括：市场信号、AI评分、Agent投票、交易记录、持仓管理等
-- ============================================

-- ============================================
-- 一、市场信号表 (market_signals)
-- 说明: 存储MarketDetector检测到的交易信号
-- 主键: id (自增)
-- 用途: 记录每次信号检测结果，供AI决策使用
-- ============================================
CREATE TABLE IF NOT EXISTS market_signals (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    symbol VARCHAR(20) NOT NULL,              -- 币种名称：ETH, BTC等
    signal_type VARCHAR(50) NOT NULL,         -- 信号类型：BREAKOUT_LONG, BREAKOUT_SHORT, TREND_REVERSAL_LONG等
    confidence_score DECIMAL(5, 2) NOT NULL,  -- 置信度分数（0-100）
    market_type VARCHAR(20) NOT NULL,         -- 市场类型：TRENDING（趋势市）, RANGING（震荡市）
    detected_at TIMESTAMPTZ NOT NULL,         -- 信号检测时间

    -- 价格信息
    price DECIMAL(20, 8) NOT NULL,            -- 检测时的价格

    -- 关联的K线时间
    timeframe_15m_time TIMESTAMPTZ,           -- 15分钟K线时间
    timeframe_4h_time TIMESTAMPTZ,            -- 4小时K线时间

    -- 评分明细（JSON格式）
    score_breakdown JSONB,                    -- 评分明细：{"trend_score": 30, "momentum_score": 25, ...}
    weight_config JSONB,                      -- 权重配置：{"trend_weight": 0.3, "momentum_weight": 0.25, ...}
    indicators_snapshot JSONB,                -- 技术指标快照：{"rsi_15m": 58.5, "macd_15m": {...}, ...}

    -- 处理状态
    processed BOOLEAN DEFAULT FALSE,          -- 是否已被AI处理
    opportunity_score_id INTEGER,             -- 关联的机会评分ID（外键）
    trade_id INTEGER,                         -- 关联的交易ID（如果执行了交易）

    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_market_signals_symbol ON market_signals(symbol);
CREATE INDEX IF NOT EXISTS idx_market_signals_detected_at ON market_signals(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_signals_processed ON market_signals(processed);
CREATE INDEX IF NOT EXISTS idx_market_signals_score ON market_signals(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_market_signals_symbol_time ON market_signals(symbol, detected_at DESC);

-- 表注释
COMMENT ON TABLE market_signals IS '市场信号表，存储MarketDetector检测到的交易信号，包括信号类型、置信度、技术指标快照等';
COMMENT ON COLUMN market_signals.id IS '自增主键ID';
COMMENT ON COLUMN market_signals.symbol IS '币种名称：ETH, BTC等';
COMMENT ON COLUMN market_signals.signal_type IS '信号类型：BREAKOUT_LONG（突破做多）, BREAKOUT_SHORT（突破做空）, TREND_REVERSAL_LONG（趋势反转做多）等';
COMMENT ON COLUMN market_signals.confidence_score IS '置信度分数（0-100），由MarketDetector计算得出';
COMMENT ON COLUMN market_signals.market_type IS '市场类型：TRENDING（趋势市）, RANGING（震荡市）';
COMMENT ON COLUMN market_signals.detected_at IS '信号检测时间';
COMMENT ON COLUMN market_signals.price IS '检测时的价格';
COMMENT ON COLUMN market_signals.score_breakdown IS '评分明细（JSON），包含趋势评分、动量评分、波动率评分等';
COMMENT ON COLUMN market_signals.weight_config IS '权重配置（JSON），包含各项评分的权重';
COMMENT ON COLUMN market_signals.indicators_snapshot IS '技术指标快照（JSON），记录检测时的所有技术指标值';
COMMENT ON COLUMN market_signals.processed IS '是否已被AI委员会处理';
COMMENT ON COLUMN market_signals.opportunity_score_id IS '关联的机会评分ID（外键）';
COMMENT ON COLUMN market_signals.trade_id IS '关联的交易ID（如果执行了交易）';

-- ============================================
-- 二、AI机会评分表 (opportunity_scores)
-- 说明: 存储AI委员会对每个信号的评分和投票结果
-- 主键: id (自增)
-- 用途: 记录AI决策过程，用于回测和优化
-- ============================================
CREATE TABLE IF NOT EXISTS opportunity_scores (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    signal_id INTEGER NOT NULL,               -- 关联的信号ID（外键）
    symbol VARCHAR(20) NOT NULL,              -- 币种名称

    -- AI投票结果
    technical_vote VARCHAR(10),               -- 技术分析师投票：YES, NO, ABSTAIN
    technical_confidence DECIMAL(3, 2),       -- 技术分析师置信度（0-1）
    technical_reasoning TEXT,                 -- 技术分析师理由

    sentiment_vote VARCHAR(10),               -- 情绪分析师投票：YES, NO, ABSTAIN
    sentiment_confidence DECIMAL(3, 2),       -- 情绪分析师置信度（0-1）
    sentiment_reasoning TEXT,                 -- 情绪分析师理由

    risk_vote VARCHAR(10),                    -- 风控官投票：YES, NO（不允许ABSTAIN）
    risk_confidence DECIMAL(3, 2),            -- 风控官置信度（0-1）
    risk_reasoning TEXT,                      -- 风控官理由
    risk_reward_ratio DECIMAL(5, 2),          -- 盈亏比
    risk_level VARCHAR(10),                   -- 风险等级：低、中、高

    chief_vote VARCHAR(10),                   -- 首席交易官投票：YES, NO, ABSTAIN
    chief_confidence DECIMAL(3, 2),           -- 首席交易官置信度（0-1）
    chief_reasoning TEXT,                     -- 首席交易官理由

    -- 投票统计
    yes_votes INTEGER DEFAULT 0,              -- YES票数
    no_votes INTEGER DEFAULT 0,               -- NO票数
    abstain_votes INTEGER DEFAULT 0,          -- ABSTAIN票数
    weighted_yes_votes DECIMAL(5, 2),         -- 加权YES票数（风控官权重×2）
    weighted_no_votes DECIMAL(5, 2),          -- 加权NO票数

    -- 最终决策
    final_decision VARCHAR(10),               -- 最终决策：YES, NO, ABSTAIN

    -- 交易计划（如果通过）
    entry_price DECIMAL(20, 8),               -- 入场价格
    stop_loss DECIMAL(20, 8),                 -- 止损价格
    take_profit DECIMAL(20, 8),               -- 止盈价格
    position_size DECIMAL(20, 8),             -- 仓位大小（USDT）
    risk_per_trade DECIMAL(20, 8),            -- 单笔风险（USDT）
    max_loss DECIMAL(20, 8),                  -- 最大亏损（USDT）

    -- AI响应原始数据（JSON格式，用于调试和分析）
    technical_response JSONB,                 -- 技术分析师完整响应
    sentiment_response JSONB,                 -- 情绪分析师完整响应
    risk_response JSONB,                      -- 风控官完整响应
    chief_response JSONB,                     -- 首席交易官完整响应

    -- 执行状态
    executed BOOLEAN DEFAULT FALSE,           -- 是否已执行交易
    trade_id INTEGER,                         -- 关联的交易ID（如果执行了交易）

    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_signal_id ON opportunity_scores(signal_id);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_symbol ON opportunity_scores(symbol);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_final_decision ON opportunity_scores(final_decision);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_executed ON opportunity_scores(executed);
CREATE INDEX IF NOT EXISTS idx_opportunity_scores_created_at ON opportunity_scores(created_at DESC);

-- 表注释
COMMENT ON TABLE opportunity_scores IS 'AI机会评分表，存储AI委员会对每个信号的评分、投票结果和交易计划';
COMMENT ON COLUMN opportunity_scores.id IS '自增主键ID';
COMMENT ON COLUMN opportunity_scores.signal_id IS '关联的信号ID（外键到market_signals表）';
COMMENT ON COLUMN opportunity_scores.symbol IS '币种名称';
COMMENT ON COLUMN opportunity_scores.weighted_yes_votes IS '加权YES票数（风控官权重×2）';
COMMENT ON COLUMN opportunity_scores.final_decision IS '最终决策：YES（执行交易）, NO（不执行）, ABSTAIN（观望）';
COMMENT ON COLUMN opportunity_scores.executed IS '是否已执行交易';

-- ============================================
-- 三、交易记录表 (trades)
-- 说明: 存储所有交易记录（开仓和平仓）
-- 主键: id (自增)
-- 用途: 记录完整的交易生命周期，用于统计和回测
-- ============================================
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    symbol VARCHAR(20) NOT NULL,              -- 币种名称

    -- 关联信息
    signal_id INTEGER,                        -- 关联的信号ID
    opportunity_score_id INTEGER,             -- 关联的机会评分ID

    -- 交易方向
    side VARCHAR(10) NOT NULL,                -- 交易方向：LONG（做多）, SHORT（做空）

    -- 开仓信息
    entry_price DECIMAL(20, 8) NOT NULL,      -- 入场价格
    entry_time TIMESTAMPTZ NOT NULL,          -- 入场时间
    entry_order_id VARCHAR(100),              -- 交易所开仓订单ID

    -- 平仓信息
    exit_price DECIMAL(20, 8),                -- 出场价格
    exit_time TIMESTAMPTZ,                    -- 出场时间
    exit_order_id VARCHAR(100),               -- 交易所平仓订单ID
    exit_reason VARCHAR(50),                  -- 平仓原因：TAKE_PROFIT, STOP_LOSS, MANUAL, AI_DECISION

    -- 仓位信息
    quantity DECIMAL(20, 8) NOT NULL,         -- 数量（币的数量，如ETH数量）
    position_size DECIMAL(20, 8) NOT NULL,    -- 仓位大小（USDT价值）

    -- 止盈止损
    stop_loss DECIMAL(20, 8) NOT NULL,        -- 止损价格
    take_profit DECIMAL(20, 8) NOT NULL,      -- 止盈价格

    -- 盈亏计算
    pnl DECIMAL(20, 8),                       -- 盈亏（USDT）
    pnl_percentage DECIMAL(10, 4),            -- 盈亏百分比
    fee DECIMAL(20, 8),                       -- 手续费（USDT）
    net_pnl DECIMAL(20, 8),                   -- 净盈亏（扣除手续费）

    -- 交易状态
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN', -- 交易状态：OPEN（持仓中）, CLOSED（已平仓）, CANCELLED（已取消）

    -- 风险指标
    max_drawdown DECIMAL(10, 4),              -- 最大回撤百分比
    max_profit DECIMAL(10, 4),                -- 最大浮盈百分比
    holding_time INTEGER,                     -- 持仓时间（秒）

    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time DESC);
CREATE INDEX IF NOT EXISTS idx_trades_pnl ON trades(pnl DESC);
CREATE INDEX IF NOT EXISTS idx_trades_signal_id ON trades(signal_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades(symbol, status);

-- 表注释
COMMENT ON TABLE trades IS '交易记录表，存储所有交易的完整生命周期（开仓、平仓、盈亏等）';
COMMENT ON COLUMN trades.id IS '自增主键ID';
COMMENT ON COLUMN trades.symbol IS '币种名称';
COMMENT ON COLUMN trades.side IS '交易方向：LONG（做多）, SHORT（做空）';
COMMENT ON COLUMN trades.status IS '交易状态：OPEN（持仓中）, CLOSED（已平仓）, CANCELLED（已取消）';
COMMENT ON COLUMN trades.exit_reason IS '平仓原因：TAKE_PROFIT（止盈）, STOP_LOSS（止损）, MANUAL（手动平仓）, AI_DECISION（AI决策平仓）';
COMMENT ON COLUMN trades.pnl IS '盈亏（USDT）';
COMMENT ON COLUMN trades.net_pnl IS '净盈亏（扣除手续费）';

-- ============================================
-- 四、持仓表 (positions)
-- 说明: 存储当前持仓状态
-- 主键: id (自增)
-- 用途: 实时持仓管理，供PositionManagerAgent使用
-- ============================================
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    symbol VARCHAR(20) NOT NULL UNIQUE,       -- 币种名称（唯一，一个币种只能有一个持仓）

    -- 关联交易
    trade_id INTEGER NOT NULL,                -- 关联的交易ID（外键到trades表）

    -- 持仓信息
    side VARCHAR(10) NOT NULL,                -- 持仓方向：LONG（多头）, SHORT（空头）
    entry_price DECIMAL(20, 8) NOT NULL,      -- 入场价格
    current_price DECIMAL(20, 8) NOT NULL,    -- 当前价格（实时更新）
    quantity DECIMAL(20, 8) NOT NULL,         -- 持仓数量
    position_size DECIMAL(20, 8) NOT NULL,    -- 仓位大小（USDT价值）

    -- 止盈止损
    stop_loss DECIMAL(20, 8) NOT NULL,        -- 当前止损价格
    take_profit DECIMAL(20, 8) NOT NULL,      -- 当前止盈价格
    initial_stop_loss DECIMAL(20, 8) NOT NULL,-- 初始止损价格（用于对比）
    initial_take_profit DECIMAL(20, 8) NOT NULL, -- 初始止盈价格（用于对比）

    -- 盈亏信息
    unrealized_pnl DECIMAL(20, 8),            -- 未实现盈亏（USDT）
    unrealized_pnl_percentage DECIMAL(10, 4), -- 未实现盈亏百分比

    -- 风险指标
    max_drawdown DECIMAL(10, 4),              -- 最大回撤百分比（自开仓以来）
    max_profit DECIMAL(10, 4),                -- 最大浮盈百分比（自开仓以来）

    -- 持仓管理
    last_adjust_time TIMESTAMPTZ,             -- 上次调整时间（止盈止损或加减仓）
    adjust_count INTEGER DEFAULT 0,           -- 调整次数

    -- 时间信息
    opened_at TIMESTAMPTZ NOT NULL,           -- 开仓时间
    last_update TIMESTAMPTZ DEFAULT NOW(),    -- 最后更新时间

    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_trade_id ON positions(trade_id);
CREATE INDEX IF NOT EXISTS idx_positions_side ON positions(side);
CREATE INDEX IF NOT EXISTS idx_positions_unrealized_pnl ON positions(unrealized_pnl DESC);

-- 表注释
COMMENT ON TABLE positions IS '持仓表，存储当前所有持仓状态，供持仓管理AI实时监控和调整';
COMMENT ON COLUMN positions.id IS '自增主键ID';
COMMENT ON COLUMN positions.symbol IS '币种名称（唯一，一个币种只能有一个持仓）';
COMMENT ON COLUMN positions.trade_id IS '关联的交易ID（外键到trades表）';
COMMENT ON COLUMN positions.side IS '持仓方向：LONG（多头）, SHORT（空头）';
COMMENT ON COLUMN positions.current_price IS '当前价格（实时更新）';
COMMENT ON COLUMN positions.unrealized_pnl IS '未实现盈亏（USDT）';
COMMENT ON COLUMN positions.last_adjust_time IS '上次调整时间（止盈止损或加减仓）';

-- ============================================
-- 五、持仓调整历史表 (position_adjustments)
-- 说明: 记录持仓管理AI的所有调整操作
-- 主键: id (自增)
-- 用途: 分析持仓管理AI的决策效果
-- ============================================
CREATE TABLE IF NOT EXISTS position_adjustments (
    id SERIAL PRIMARY KEY,                    -- 自增主键ID
    position_id INTEGER NOT NULL,             -- 关联的持仓ID
    trade_id INTEGER NOT NULL,                -- 关联的交易ID
    symbol VARCHAR(20) NOT NULL,              -- 币种名称

    -- 调整类型
    action_type VARCHAR(20) NOT NULL,         -- 操作类型：ADD（加仓）, REDUCE（减仓）, ADJUST（调整止盈止损）, CLOSE（平仓）

    -- 调整前状态
    before_quantity DECIMAL(20, 8),           -- 调整前数量
    before_stop_loss DECIMAL(20, 8),          -- 调整前止损
    before_take_profit DECIMAL(20, 8),        -- 调整前止盈
    before_price DECIMAL(20, 8),              -- 调整时价格

    -- 调整后状态
    after_quantity DECIMAL(20, 8),            -- 调整后数量
    after_stop_loss DECIMAL(20, 8),           -- 调整后止损
    after_take_profit DECIMAL(20, 8),         -- 调整后止盈

    -- 调整数量（仅加仓/减仓）
    quantity_change DECIMAL(20, 8),           -- 数量变化

    -- AI决策
    ai_reasoning TEXT,                        -- AI决策理由
    ai_confidence DECIMAL(3, 2),              -- AI置信度
    ai_response JSONB,                        -- AI完整响应（JSON）

    -- 市场状态快照
    market_snapshot JSONB,                    -- 市场状态快照（技术指标、情绪等）

    -- 执行结果
    executed BOOLEAN DEFAULT FALSE,           -- 是否已执行
    execution_price DECIMAL(20, 8),           -- 实际执行价格
    order_id VARCHAR(100),                    -- 交易所订单ID

    -- 系统字段
    created_at TIMESTAMPTZ DEFAULT NOW(),     -- 记录创建时间
    updated_at TIMESTAMPTZ DEFAULT NOW()      -- 记录更新时间
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_position_adjustments_position_id ON position_adjustments(position_id);
CREATE INDEX IF NOT EXISTS idx_position_adjustments_trade_id ON position_adjustments(trade_id);
CREATE INDEX IF NOT EXISTS idx_position_adjustments_symbol ON position_adjustments(symbol);
CREATE INDEX IF NOT EXISTS idx_position_adjustments_action_type ON position_adjustments(action_type);
CREATE INDEX IF NOT EXISTS idx_position_adjustments_created_at ON position_adjustments(created_at DESC);

-- 表注释
COMMENT ON TABLE position_adjustments IS '持仓调整历史表，记录持仓管理AI的所有调整操作（加仓、减仓、调整止盈止损等）';
COMMENT ON COLUMN position_adjustments.id IS '自增主键ID';
COMMENT ON COLUMN position_adjustments.action_type IS '操作类型：ADD（加仓）, REDUCE（减仓）, ADJUST（调整止盈止损）, CLOSE（平仓）';
COMMENT ON COLUMN position_adjustments.ai_reasoning IS 'AI决策理由';
COMMENT ON COLUMN position_adjustments.ai_response IS 'AI完整响应（JSON格式）';
COMMENT ON COLUMN position_adjustments.market_snapshot IS '市场状态快照（包含技术指标、情绪面等数据）';

-- ============================================
-- 六、外键约束
-- 说明: 建立表之间的引用完整性约束
-- ============================================

-- market_signals -> opportunity_scores
ALTER TABLE market_signals
    ADD CONSTRAINT fk_market_signals_opportunity_score
    FOREIGN KEY (opportunity_score_id) REFERENCES opportunity_scores(id)
    ON DELETE SET NULL;

-- market_signals -> trades
ALTER TABLE market_signals
    ADD CONSTRAINT fk_market_signals_trade
    FOREIGN KEY (trade_id) REFERENCES trades(id)
    ON DELETE SET NULL;

-- opportunity_scores -> market_signals
ALTER TABLE opportunity_scores
    ADD CONSTRAINT fk_opportunity_scores_signal
    FOREIGN KEY (signal_id) REFERENCES market_signals(id)
    ON DELETE CASCADE;

-- opportunity_scores -> trades
ALTER TABLE opportunity_scores
    ADD CONSTRAINT fk_opportunity_scores_trade
    FOREIGN KEY (trade_id) REFERENCES trades(id)
    ON DELETE SET NULL;

-- trades -> market_signals
ALTER TABLE trades
    ADD CONSTRAINT fk_trades_signal
    FOREIGN KEY (signal_id) REFERENCES market_signals(id)
    ON DELETE SET NULL;

-- trades -> opportunity_scores
ALTER TABLE trades
    ADD CONSTRAINT fk_trades_opportunity_score
    FOREIGN KEY (opportunity_score_id) REFERENCES opportunity_scores(id)
    ON DELETE SET NULL;

-- positions -> trades
ALTER TABLE positions
    ADD CONSTRAINT fk_positions_trade
    FOREIGN KEY (trade_id) REFERENCES trades(id)
    ON DELETE CASCADE;

-- position_adjustments -> positions
ALTER TABLE position_adjustments
    ADD CONSTRAINT fk_position_adjustments_position
    FOREIGN KEY (position_id) REFERENCES positions(id)
    ON DELETE CASCADE;

-- position_adjustments -> trades
ALTER TABLE position_adjustments
    ADD CONSTRAINT fk_position_adjustments_trade
    FOREIGN KEY (trade_id) REFERENCES trades(id)
    ON DELETE CASCADE;

-- ============================================
-- 七、触发器：自动更新updated_at字段
-- ============================================

-- 创建通用的更新时间戳函数
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- 为所有表添加触发器
CREATE TRIGGER update_market_signals_updated_at BEFORE UPDATE ON market_signals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_opportunity_scores_updated_at BEFORE UPDATE ON opportunity_scores
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_trades_updated_at BEFORE UPDATE ON trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_position_adjustments_updated_at BEFORE UPDATE ON position_adjustments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 八、完成说明
-- ============================================
-- 所有交易相关数据表创建完成！
--
-- 表清单：
-- 1. market_signals（市场信号表）
-- 2. opportunity_scores（AI机会评分表）
-- 3. trades（交易记录表）
-- 4. positions（持仓表）
-- 5. position_adjustments（持仓调整历史表）
--
-- 使用说明：
-- 1. 在执行本脚本之前，请确保已执行 all_tables.sql 创建基础数据表
-- 2. 所有表都包含完整的索引、注释和外键约束
-- 3. 自动更新updated_at字段的触发器已创建
-- 4. 如果需要删除所有表，请按以下顺序执行：
--    DROP TABLE IF EXISTS position_adjustments CASCADE;
--    DROP TABLE IF EXISTS positions CASCADE;
--    DROP TABLE IF EXISTS trades CASCADE;
--    DROP TABLE IF EXISTS opportunity_scores CASCADE;
--    DROP TABLE IF EXISTS market_signals CASCADE;
-- ============================================
