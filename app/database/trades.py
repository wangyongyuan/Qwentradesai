"""
交易记录数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from decimal import Decimal
from app.database.connection import db
from app.utils.logger import logger


class TradeRepository:
    """交易记录数据仓库"""

    @staticmethod
    def create_trade(
        session: Session,
        symbol: str,
        side: str,
        entry_price: Decimal,
        quantity: Decimal,
        position_size: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal,
        signal_id: Optional[int] = None,
        opportunity_score_id: Optional[int] = None,
        entry_order_id: Optional[str] = None
    ) -> Optional[int]:
        """
        创建新交易记录（开仓）

        Args:
            session: 数据库会话
            symbol: 币种名称
            side: 交易方向（LONG/SHORT）
            entry_price: 入场价格
            quantity: 数量
            position_size: 仓位大小（USDT）
            stop_loss: 止损价格
            take_profit: 止盈价格
            signal_id: 关联的信号ID
            opportunity_score_id: 关联的机会评分ID
            entry_order_id: 交易所订单ID

        Returns:
            交易ID，失败返回None
        """
        try:
            sql = text("""
                INSERT INTO trades (
                    symbol, side, entry_price, entry_time, entry_order_id,
                    quantity, position_size, stop_loss, take_profit,
                    signal_id, opportunity_score_id, status
                )
                VALUES (
                    :symbol, :side, :entry_price, :entry_time, :entry_order_id,
                    :quantity, :position_size, :stop_loss, :take_profit,
                    :signal_id, :opportunity_score_id, 'OPEN'
                )
                RETURNING id
            """)

            result = session.execute(sql, {
                'symbol': symbol,
                'side': side,
                'entry_price': float(entry_price),
                'entry_time': datetime.now(timezone.utc),
                'entry_order_id': entry_order_id,
                'quantity': float(quantity),
                'position_size': float(position_size),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'signal_id': signal_id,
                'opportunity_score_id': opportunity_score_id
            })

            session.commit()
            trade_id = result.fetchone()[0]
            logger.info(f"交易已创建: ID={trade_id}, 币种={symbol}, 方向={side}, 入场价={entry_price}")
            return trade_id

        except Exception as e:
            session.rollback()
            logger.error(f"创建交易失败: {e}", exc_info=True)
            return None

    @staticmethod
    def close_trade(
        session: Session,
        trade_id: int,
        exit_price: Decimal,
        exit_reason: str,
        exit_order_id: Optional[str] = None,
        fee: Optional[Decimal] = None
    ) -> bool:
        """
        平仓交易

        Args:
            session: 数据库会话
            trade_id: 交易ID
            exit_price: 出场价格
            exit_reason: 平仓原因（TAKE_PROFIT/STOP_LOSS/MANUAL/AI_DECISION）
            exit_order_id: 交易所订单ID
            fee: 手续费

        Returns:
            是否成功
        """
        try:
            # 获取交易信息
            trade = TradeRepository.get_trade_by_id(session, trade_id)
            if not trade:
                logger.error(f"交易不存在: ID={trade_id}")
                return False

            # 计算盈亏
            entry_price = Decimal(str(trade['entry_price']))
            quantity = Decimal(str(trade['quantity']))
            side = trade['side']

            if side == 'LONG':
                pnl = (exit_price - entry_price) * quantity
            else:  # SHORT
                pnl = (entry_price - exit_price) * quantity

            pnl_percentage = (pnl / Decimal(str(trade['position_size']))) * 100

            # 计算净盈亏
            fee_amount = fee if fee else Decimal('0')
            net_pnl = pnl - fee_amount

            # 计算持仓时间
            entry_time = trade['entry_time']
            exit_time = datetime.now(timezone.utc)
            holding_time = int((exit_time - entry_time).total_seconds())

            # 更新交易记录
            sql = text("""
                UPDATE trades
                SET exit_price = :exit_price,
                    exit_time = :exit_time,
                    exit_order_id = :exit_order_id,
                    exit_reason = :exit_reason,
                    pnl = :pnl,
                    pnl_percentage = :pnl_percentage,
                    fee = :fee,
                    net_pnl = :net_pnl,
                    holding_time = :holding_time,
                    status = 'CLOSED'
                WHERE id = :trade_id
            """)

            session.execute(sql, {
                'trade_id': trade_id,
                'exit_price': float(exit_price),
                'exit_time': exit_time,
                'exit_order_id': exit_order_id,
                'exit_reason': exit_reason,
                'pnl': float(pnl),
                'pnl_percentage': float(pnl_percentage),
                'fee': float(fee_amount),
                'net_pnl': float(net_pnl),
                'holding_time': holding_time
            })

            session.commit()
            logger.info(f"交易已平仓: ID={trade_id}, 出场价={exit_price}, 盈亏={pnl:.2f} USDT ({pnl_percentage:.2f}%)")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"平仓交易失败: {e}", exc_info=True)
            return False

    @staticmethod
    def get_trade_by_id(session: Session, trade_id: int) -> Optional[Dict[str, Any]]:
        """获取交易记录"""
        try:
            sql = text("""
                SELECT * FROM trades WHERE id = :trade_id
            """)
            result = session.execute(sql, {'trade_id': trade_id}).fetchone()
            return dict(result._mapping) if result else None
        except Exception as e:
            logger.error(f"获取交易失败: {e}", exc_info=True)
            return None

    @staticmethod
    def get_open_trades(session: Session, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有持仓中的交易"""
        try:
            conditions = ["status = 'OPEN'"]
            params = {}

            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol

            sql = text(f"""
                SELECT * FROM trades
                WHERE {' AND '.join(conditions)}
                ORDER BY entry_time DESC
            """)

            results = session.execute(sql, params).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取持仓交易失败: {e}", exc_info=True)
            return []

    @staticmethod
    def get_closed_trades(
        session: Session,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """获取已平仓交易"""
        try:
            conditions = ["status = 'CLOSED'"]
            params = {'limit': limit, 'offset': offset}

            if symbol:
                conditions.append("symbol = :symbol")
                params['symbol'] = symbol

            sql = text(f"""
                SELECT * FROM trades
                WHERE {' AND '.join(conditions)}
                ORDER BY exit_time DESC
                LIMIT :limit OFFSET :offset
            """)

            results = session.execute(sql, params).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取已平仓交易失败: {e}", exc_info=True)
            return []

    @staticmethod
    def get_recent_trades(session: Session, symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的交易记录（用于计算胜率和连续亏损）"""
        try:
            sql = text("""
                SELECT * FROM trades
                WHERE symbol = :symbol AND status = 'CLOSED'
                ORDER BY exit_time DESC
                LIMIT :limit
            """)

            results = session.execute(sql, {'symbol': symbol, 'limit': limit}).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取最近交易失败: {e}", exc_info=True)
            return []

    @staticmethod
    def get_consecutive_losses(session: Session, symbol: str) -> int:
        """计算连续亏损次数"""
        try:
            recent_trades = TradeRepository.get_recent_trades(session, symbol, limit=20)

            consecutive_losses = 0
            for trade in recent_trades:
                pnl = trade.get('pnl')
                if pnl is None:
                    continue

                if float(pnl) < 0:
                    consecutive_losses += 1
                else:
                    break

            return consecutive_losses
        except Exception as e:
            logger.error(f"计算连续亏损失败: {e}", exc_info=True)
            return 0

    @staticmethod
    def get_win_rate(session: Session, symbol: str, limit: int = 20) -> float:
        """计算胜率"""
        try:
            recent_trades = TradeRepository.get_recent_trades(session, symbol, limit=limit)

            if not recent_trades:
                return 0.0

            wins = sum(1 for trade in recent_trades if trade.get('pnl') and float(trade['pnl']) > 0)
            total = len(recent_trades)

            return (wins / total) * 100 if total > 0 else 0.0
        except Exception as e:
            logger.error(f"计算胜率失败: {e}", exc_info=True)
            return 0.0

    @staticmethod
    def update_max_drawdown_profit(
        session: Session,
        trade_id: int,
        max_drawdown: Optional[Decimal] = None,
        max_profit: Optional[Decimal] = None
    ) -> bool:
        """更新最大回撤和最大浮盈"""
        try:
            updates = []
            params = {'trade_id': trade_id}

            if max_drawdown is not None:
                updates.append("max_drawdown = :max_drawdown")
                params['max_drawdown'] = float(max_drawdown)

            if max_profit is not None:
                updates.append("max_profit = :max_profit")
                params['max_profit'] = float(max_profit)

            if not updates:
                return True

            sql = text(f"""
                UPDATE trades
                SET {', '.join(updates)}
                WHERE id = :trade_id
            """)

            session.execute(sql, params)
            session.commit()
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"更新最大回撤/浮盈失败: {e}", exc_info=True)
            return False
