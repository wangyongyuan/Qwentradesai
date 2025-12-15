"""
持仓数据库操作模块
"""
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from decimal import Decimal
from app.database.connection import db
from app.utils.logger import logger


class PositionRepository:
    """持仓数据仓库"""

    @staticmethod
    def create_position(
        session: Session,
        symbol: str,
        trade_id: int,
        side: str,
        entry_price: Decimal,
        current_price: Decimal,
        quantity: Decimal,
        position_size: Decimal,
        stop_loss: Decimal,
        take_profit: Decimal
    ) -> Optional[int]:
        """
        创建新持仓

        Args:
            session: 数据库会话
            symbol: 币种名称
            trade_id: 关联的交易ID
            side: 持仓方向（LONG/SHORT）
            entry_price: 入场价格
            current_price: 当前价格
            quantity: 持仓数量
            position_size: 仓位大小（USDT）
            stop_loss: 止损价格
            take_profit: 止盈价格

        Returns:
            持仓ID，失败返回None
        """
        try:
            # 计算未实现盈亏
            if side == 'LONG':
                unrealized_pnl = (current_price - entry_price) * quantity
            else:  # SHORT
                unrealized_pnl = (entry_price - current_price) * quantity

            unrealized_pnl_percentage = (unrealized_pnl / position_size) * 100

            sql = text("""
                INSERT INTO positions (
                    symbol, trade_id, side, entry_price, current_price,
                    quantity, position_size, stop_loss, take_profit,
                    initial_stop_loss, initial_take_profit,
                    unrealized_pnl, unrealized_pnl_percentage,
                    opened_at, last_update
                )
                VALUES (
                    :symbol, :trade_id, :side, :entry_price, :current_price,
                    :quantity, :position_size, :stop_loss, :take_profit,
                    :initial_stop_loss, :initial_take_profit,
                    :unrealized_pnl, :unrealized_pnl_percentage,
                    :opened_at, :last_update
                )
                RETURNING id
            """)

            result = session.execute(sql, {
                'symbol': symbol,
                'trade_id': trade_id,
                'side': side,
                'entry_price': float(entry_price),
                'current_price': float(current_price),
                'quantity': float(quantity),
                'position_size': float(position_size),
                'stop_loss': float(stop_loss),
                'take_profit': float(take_profit),
                'initial_stop_loss': float(stop_loss),
                'initial_take_profit': float(take_profit),
                'unrealized_pnl': float(unrealized_pnl),
                'unrealized_pnl_percentage': float(unrealized_pnl_percentage),
                'opened_at': datetime.now(timezone.utc),
                'last_update': datetime.now(timezone.utc)
            })

            session.commit()
            position_id = result.fetchone()[0]
            logger.info(f"持仓已创建: ID={position_id}, 币种={symbol}, 方向={side}, 数量={quantity}")
            return position_id

        except Exception as e:
            session.rollback()
            logger.error(f"创建持仓失败: {e}", exc_info=True)
            return None

    @staticmethod
    def update_position_price(
        session: Session,
        symbol: str,
        current_price: Decimal
    ) -> bool:
        """
        更新持仓的当前价格和未实现盈亏

        Args:
            session: 数据库会话
            symbol: 币种名称
            current_price: 当前价格

        Returns:
            是否成功
        """
        try:
            # 获取持仓信息
            position = PositionRepository.get_position_by_symbol(session, symbol)
            if not position:
                return False

            entry_price = Decimal(str(position['entry_price']))
            quantity = Decimal(str(position['quantity']))
            position_size = Decimal(str(position['position_size']))
            side = position['side']

            # 计算未实现盈亏
            if side == 'LONG':
                unrealized_pnl = (current_price - entry_price) * quantity
            else:  # SHORT
                unrealized_pnl = (entry_price - current_price) * quantity

            unrealized_pnl_percentage = (unrealized_pnl / position_size) * 100

            # 更新最大回撤和最大浮盈
            max_drawdown = position.get('max_drawdown')
            max_profit = position.get('max_profit')

            if unrealized_pnl_percentage < 0:
                if max_drawdown is None or unrealized_pnl_percentage < float(max_drawdown):
                    max_drawdown = unrealized_pnl_percentage
            else:
                if max_profit is None or unrealized_pnl_percentage > float(max_profit):
                    max_profit = unrealized_pnl_percentage

            sql = text("""
                UPDATE positions
                SET current_price = :current_price,
                    unrealized_pnl = :unrealized_pnl,
                    unrealized_pnl_percentage = :unrealized_pnl_percentage,
                    max_drawdown = :max_drawdown,
                    max_profit = :max_profit,
                    last_update = :last_update
                WHERE symbol = :symbol
            """)

            session.execute(sql, {
                'symbol': symbol,
                'current_price': float(current_price),
                'unrealized_pnl': float(unrealized_pnl),
                'unrealized_pnl_percentage': float(unrealized_pnl_percentage),
                'max_drawdown': float(max_drawdown) if max_drawdown is not None else None,
                'max_profit': float(max_profit) if max_profit is not None else None,
                'last_update': datetime.now(timezone.utc)
            })

            session.commit()
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"更新持仓价格失败: {e}", exc_info=True)
            return False

    @staticmethod
    def update_stop_loss_take_profit(
        session: Session,
        symbol: str,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None
    ) -> bool:
        """
        更新持仓的止盈止损

        Args:
            session: 数据库会话
            symbol: 币种名称
            stop_loss: 新的止损价格（可选）
            take_profit: 新的止盈价格（可选）

        Returns:
            是否成功
        """
        try:
            updates = []
            params = {'symbol': symbol}

            if stop_loss is not None:
                updates.append("stop_loss = :stop_loss")
                params['stop_loss'] = float(stop_loss)

            if take_profit is not None:
                updates.append("take_profit = :take_profit")
                params['take_profit'] = float(take_profit)

            if not updates:
                return True

            updates.append("last_adjust_time = :last_adjust_time")
            updates.append("adjust_count = adjust_count + 1")
            params['last_adjust_time'] = datetime.now(timezone.utc)

            sql = text(f"""
                UPDATE positions
                SET {', '.join(updates)}
                WHERE symbol = :symbol
            """)

            session.execute(sql, params)
            session.commit()
            logger.info(f"止盈止损已更新: 币种={symbol}, 止损={stop_loss}, 止盈={take_profit}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"更新止盈止损失败: {e}", exc_info=True)
            return False

    @staticmethod
    def update_position_quantity(
        session: Session,
        symbol: str,
        new_quantity: Decimal,
        new_position_size: Decimal
    ) -> bool:
        """
        更新持仓数量（加仓/减仓）

        Args:
            session: 数据库会话
            symbol: 币种名称
            new_quantity: 新的数量
            new_position_size: 新的仓位大小

        Returns:
            是否成功
        """
        try:
            sql = text("""
                UPDATE positions
                SET quantity = :quantity,
                    position_size = :position_size,
                    last_adjust_time = :last_adjust_time,
                    adjust_count = adjust_count + 1
                WHERE symbol = :symbol
            """)

            session.execute(sql, {
                'symbol': symbol,
                'quantity': float(new_quantity),
                'position_size': float(new_position_size),
                'last_adjust_time': datetime.now(timezone.utc)
            })

            session.commit()
            logger.info(f"持仓数量已更新: 币种={symbol}, 新数量={new_quantity}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"更新持仓数量失败: {e}", exc_info=True)
            return False

    @staticmethod
    def delete_position(session: Session, symbol: str) -> bool:
        """
        删除持仓（平仓后）

        Args:
            session: 数据库会话
            symbol: 币种名称

        Returns:
            是否成功
        """
        try:
            sql = text("DELETE FROM positions WHERE symbol = :symbol")
            session.execute(sql, {'symbol': symbol})
            session.commit()
            logger.info(f"持仓已删除: 币种={symbol}")
            return True
        except Exception as e:
            session.rollback()
            logger.error(f"删除持仓失败: {e}", exc_info=True)
            return False

    @staticmethod
    def get_position_by_symbol(session: Session, symbol: str) -> Optional[Dict[str, Any]]:
        """获取指定币种的持仓"""
        try:
            sql = text("SELECT * FROM positions WHERE symbol = :symbol")
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            return dict(result._mapping) if result else None
        except Exception as e:
            logger.error(f"获取持仓失败: {e}", exc_info=True)
            return None

    @staticmethod
    def get_all_positions(session: Session) -> List[Dict[str, Any]]:
        """获取所有持仓"""
        try:
            sql = text("SELECT * FROM positions ORDER BY opened_at DESC")
            results = session.execute(sql).fetchall()
            return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.error(f"获取所有持仓失败: {e}", exc_info=True)
            return []

    @staticmethod
    def has_position(session: Session, symbol: str) -> bool:
        """检查是否有持仓"""
        try:
            sql = text("SELECT COUNT(*) FROM positions WHERE symbol = :symbol")
            result = session.execute(sql, {'symbol': symbol}).fetchone()
            return result[0] > 0 if result else False
        except Exception as e:
            logger.error(f"检查持仓失败: {e}", exc_info=True)
            return False
