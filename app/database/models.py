"""
数据库模型定义
"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class SystemStatus(Base):
    """系统状态表"""
    __tablename__ = 'system_status'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class Trade(Base):
    """交易记录表"""
    __tablename__ = 'trades'
    
    id = Column(Integer, primary_key=True)
    direction = Column(String(10), nullable=False)  # LONG/SHORT
    entry_price = Column(Numeric(20, 8), nullable=False)
    exit_price = Column(Numeric(20, 8))
    quantity = Column(Numeric(20, 8), nullable=False)
    stop_loss = Column(Numeric(20, 8), nullable=False)
    take_profit = Column(Numeric(20, 8))
    
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True))
    exit_reason = Column(String(100))
    
    pnl = Column(Numeric(20, 8))  # 盈亏金额
    pnl_percentage = Column(Numeric(10, 4))  # 盈亏百分比
    
    signal = Column(String(50))  # 市场信号
    opportunity_score = Column(Numeric(5, 2))  # 机会评分
    ai_decision = Column(JSONB)  # AI决策原文
    
    entry_order_id = Column(String(100))
    exit_order_id = Column(String(100))
    stop_loss_order_id = Column(String(100))
    
    slippage = Column(Numeric(10, 4))  # 滑点
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    ai_decisions = relationship("AIDecision", back_populates="trade")
    opportunity_scores = relationship("OpportunityScore", back_populates="trade")


class AIDecision(Base):
    """AI决策记录表"""
    __tablename__ = 'ai_decisions'
    
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trades.id'))
    opportunity_id = Column(Integer)  # 暂时不设外键
    
    final_vote = Column(String(10), nullable=False)  # YES/NO/ABSTAIN
    agent_votes = Column(JSONB, nullable=False)  # 所有Agent的投票
    
    decision_reasoning = Column(Text)
    trade_plan = Column(JSONB)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # 关系
    trade = relationship("Trade", back_populates="ai_decisions")


class OpportunityScore(Base):
    """机会评分历史表"""
    __tablename__ = 'opportunity_scores'
    
    id = Column(Integer, primary_key=True)
    signal = Column(String(50), nullable=False)
    
    total_score = Column(Numeric(5, 2), nullable=False)
    technical_score = Column(Numeric(5, 2), nullable=False)
    fundamental_score = Column(Numeric(5, 2), nullable=False)
    risk_score = Column(Numeric(5, 2), nullable=False)
    consensus_score = Column(Numeric(5, 2), nullable=False)
    
    score_details = Column(JSONB)  # 详细评分项
    ai_decision = Column(JSONB)  # AI决策原文
    
    executed = Column(Boolean, default=False)  # 是否执行
    trade_id = Column(Integer, ForeignKey('trades.id'))
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    
    # 关系
    trade = relationship("Trade", back_populates="opportunity_scores")


class AgentCreditScore(Base):
    """Agent信用分表"""
    __tablename__ = 'agent_credit_scores'
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String(50), unique=True, nullable=False)
    credit_score = Column(Numeric(5, 2), nullable=False, default=100.0)
    total_votes = Column(Integer, default=0)
    correct_votes = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentVoteHistory(Base):
    """Agent投票历史表"""
    __tablename__ = 'agent_vote_history'
    
    id = Column(Integer, primary_key=True)
    agent_name = Column(String(50), nullable=False)
    decision_id = Column(Integer, ForeignKey('ai_decisions.id'))
    trade_id = Column(Integer, ForeignKey('trades.id'))
    
    vote = Column(String(10), nullable=False)  # YES/NO/ABSTAIN
    confidence = Column(Numeric(5, 2))
    reasoning = Column(Text)
    suggestions = Column(JSONB)
    
    trade_result_pnl = Column(Numeric(20, 8))  # 交易结果（用于计算信用分）
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

