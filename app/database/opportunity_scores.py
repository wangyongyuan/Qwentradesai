"""
AI机会评分数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal
from app.database.connection import db
from app.utils.logger import logger
import json


class OpportunityScoreRepository:
    """AI机会评分数据仓库"""

    @staticmethod
    def create_opportunity_score(
        session: Session,
        signal_id: int,
        symbol: str,
        # 技术分析师投票
        technical_vote: str,
        technical_confidence: float,
        technical_reasoning: str,
        technical_response: Dict[str, Any],
        # 情绪分析师投票
        sentiment_vote: str,
        sentiment_confidence: float,
        sentiment_reasoning: str,
        sentiment_response: Dict[str, Any],
        # 风控官投票
        risk_vote: str,
        risk_confidence: float,
        risk_reasoning: str,
        risk_response: Dict[str, Any],
        risk_reward_ratio: float,
        risk_level: str,
        # 首席交易官投票
        chief_vote: str,
        chief_confidence: float,
        chief_reasoning: str,
        chief_response: Dict[str, Any],
        # 投票统计
        yes_votes: int,
        no_votes: int,
        abstain_votes: int,
        weighted_yes_votes: float,
        weighted_no_votes: float,
        final_decision: str,
        # 交易计划（如果通过）
        entry_price: Optional[Decimal] = None,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        position_size: Optional[Decimal] = None,
        risk_per_trade: Optional[Decimal] = None,
        max_loss: Optional[Decimal] = None
    ) -> Optional[int]:
        """
        创建AI机会评分记录

        Returns:
            评分ID，失败返回None
        """
        try:
            sql = text("""
                INSERT INTO opportunity_scores (
                    signal_id, symbol,
                    technical_vote, technical_confidence, technical_reasoning, technical_response,
                    sentiment_vote, sentiment_confidence, sentiment_reasoning, sentiment_response,
                    risk_vote, risk_confidence, risk_reasoning, risk_response, risk_reward_ratio, risk_level,
                    chief_vote, chief_confidence, chief_reasoning, chief_response,
                    yes_votes, no_votes, abstain_votes, weighted_yes_votes, weighted_no_votes,
                    final_decision,
                    entry_price, stop_loss, take_profit, position_size, risk_per_trade, max_loss
                )
                VALUES (
                    :signal_id, :symbol,
                    :technical_vote, :technical_confidence, :technical_reasoning, :technical_response,
                    :sentiment_vote, :sentiment_confidence, :sentiment_reasoning, :sentiment_response,
                    :risk_vote, :risk_confidence, :risk_reasoning, :risk_response, :risk_reward_ratio, :risk_level,
                    :chief_vote, :chief_confidence, :chief_reasoning, :chief_response,
                    :yes_votes, :no_votes, :abstain_votes, :weighted_yes_votes, :weighted_no_votes,
                    :final_decision,
                    :entry_price, :stop_loss, :take_profit, :position_size, :risk_per_trade, :max_loss
                )
                RETURNING id
            """)

            result = session.execute(sql, {
                'signal_id': signal_id,
                'symbol': symbol,
                'technical_vote': technical_vote,
                'technical_confidence': technical_confidence,
                'technical_reasoning': technical_reasoning,
                'technical_response': json.dumps(technical_response),
                'sentiment_vote': sentiment_vote,
                'sentiment_confidence': sentiment_confidence,
                'sentiment_reasoning': sentiment_reasoning,
                'sentiment_response': json.dumps(sentiment_response),
                'risk_vote': risk_vote,
                'risk_confidence': risk_confidence,
                'risk_reasoning': risk_reasoning,
                'risk_response': json.dumps(risk_response),
                'risk_reward_ratio': risk_reward_ratio,
                'risk_level': risk_level,
                'chief_vote': chief_vote,
                'chief_confidence': chief_confidence,
                'chief_reasoning': chief_reasoning,
                'chief_response': json.dumps(chief_response),
                'yes_votes': yes_votes,
                'no_votes': no_votes,
                'abstain_votes': abstain_votes,
                'weighted_yes_votes': weighted_yes_votes,
                'weighted_no_votes': weighted_no_votes,
                'final_decision': final_decision,
                'entry_price': float(entry_price) if entry_price else None,
                'stop_loss': float(stop_loss) if stop_loss else None,
                'take_profit': float(take_profit) if take_profit else None,
                'position_size': float(position_size) if position_size else None,
                'risk_per_trade': float(risk_per_trade) if risk_per_trade else None,
                'max_loss': float(max_loss) if max_loss else None,
            })

            session.commit()
            score_id = result.fetchone()[0]
            logger.info(f"AI评分已保存: ID={score_id}, 信号ID={signal_id}, 最终决策={final_decision}")
            return score_id

        except Exception as e:
            session.rollback()
            logger.error(f"创建AI评分失败: {e}", exc_info=True)
            return None

    @staticmethod
    def update_executed_status(
        session: Session,
        score_id: int,
        executed: bool,
        trade_id: Optional[int] = None
    ) -> bool:
        """更新执行状态"""
        try:
            sql = text("""
                UPDATE opportunity_scores
                SET executed = :executed,
                    trade_id = :trade_id
                WHERE id = :score_id
            """)

            session.execute(sql, {
                'score_id': score_id,
                'executed': executed,
                'trade_id': trade_id
            })

            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"更新执行状态失败: {e}", exc_info=True)
            return False

    @staticmethod
    def get_score_by_id(session: Session, score_id: int) -> Optional[Dict[str, Any]]:
        """获取评分记录"""
        try:
            sql = text("SELECT * FROM opportunity_scores WHERE id = :score_id")
            result = session.execute(sql, {'score_id': score_id}).fetchone()
            return dict(result._mapping) if result else None
        except Exception as e:
            logger.error(f"获取评分记录失败: {e}", exc_info=True)
            return None

    @staticmethod
    def get_scores_by_signal(session: Session, signal_id: int) -> List[Dict[str, Any]]:
        """获取信号的所有评分记录"""
        try:
            sql = text("""
                SELECT * FROM opportunity_scores
                WHERE signal_id = :signal_id
                ORDER BY created_at DESC
            """)
            results = session.execute(sql, {'signal_id': signal_id}).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取信号评分失败: {e}", exc_info=True)
            return []

    @staticmethod
    def get_recent_scores(
        session: Session,
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取最近的评分记录"""
        try:
            conditions = []
            params = {'limit': limit}

            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            sql = text(f"""
                SELECT * FROM opportunity_scores
                {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit
            """)

            results = session.execute(sql, params).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取最近评分失败: {e}", exc_info=True)
            return []

    @staticmethod
    def get_decision_stats(session: Session, symbol: Optional[str] = None) -> Dict[str, Any]:
        """获取决策统计信息"""
        try:
            conditions = []
            params = {}

            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

            sql = text(f"""
                SELECT
                    COUNT(*) as total_decisions,
                    SUM(CASE WHEN final_decision = 'YES' THEN 1 ELSE 0 END) as yes_count,
                    SUM(CASE WHEN final_decision = 'NO' THEN 1 ELSE 0 END) as no_count,
                    SUM(CASE WHEN final_decision = 'ABSTAIN' THEN 1 ELSE 0 END) as abstain_count,
                    SUM(CASE WHEN executed = TRUE THEN 1 ELSE 0 END) as executed_count,
                    AVG(CASE WHEN final_decision = 'YES' THEN weighted_yes_votes END) as avg_yes_weight,
                    AVG(risk_reward_ratio) as avg_risk_reward_ratio
                FROM opportunity_scores
                {where_clause}
            """)

            result = session.execute(sql, params).fetchone()
            return dict(result._mapping) if result else {}
        except Exception as e:
            logger.error(f"获取决策统计失败: {e}", exc_info=True)
            return {}
