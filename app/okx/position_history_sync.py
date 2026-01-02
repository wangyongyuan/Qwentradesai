"""
OKX仓位历史同步管理器
"""
import threading
import time
import requests
import hmac
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode
from sqlalchemy import text
from app.components.api_manager import APIManager
from app.database.connection import db
from app.database.position_history import PositionHistoryRepository
from app.config import settings
from app.utils.logger import logger


class PositionHistorySyncManager(threading.Thread):
    """OKX仓位历史同步管理器（后台线程）"""
    
    def __init__(self, api_manager: APIManager):
        super().__init__(name="PositionHistorySyncThread", daemon=False)
        self.api_manager = api_manager
        self.stop_event = threading.Event()
        self.db = db
        
        # 同步状态
        self.last_sync_time: Optional[datetime] = None
        self.sync_symbols: List[str] = []  # 要同步的币种列表
        
        # 初始化同步币种列表
        self._init_sync_symbols()
    
    def _init_sync_symbols(self):
        """初始化同步币种列表"""
        try:
            symbols_str = settings._get('OKX_POSITION_HISTORY_SYMBOLS', 'BTC,ETH', 'string')
            self.sync_symbols = [s.strip().upper() for s in symbols_str.split(',') if s.strip()]
        except Exception as e:
            logger.warning(f"读取OKX_POSITION_HISTORY_SYMBOLS配置失败，使用默认值: {e}")
            self.sync_symbols = ['BTC', 'ETH']
    
    def _get_start_time_ms(self) -> int:
        """获取同步开始时间（毫秒时间戳）"""
        try:
            start_time_str = settings._get('OKX_POSITION_HISTORY_START_TIME', '', 'string')
            if start_time_str and start_time_str.strip():
                return int(start_time_str.strip())
            else:
                # 如果未配置，默认从当前时间往前推30天
                now = datetime.now(timezone.utc)
                start_time = now - timedelta(days=30)
                return int(start_time.timestamp() * 1000)
        except Exception as e:
            logger.warning(f"读取OKX_POSITION_HISTORY_START_TIME配置失败，使用默认值（30天前）: {e}")
            now = datetime.now(timezone.utc)
            start_time = now - timedelta(days=30)
            return int(start_time.timestamp() * 1000)
    
    def stop(self):
        """停止同步线程"""
        self.stop_event.set()
    
    def _symbol_to_inst_id(self, symbol: str) -> str:
        """将币种转换为OKX instId格式（永续合约）"""
        return f"{symbol}-USDT-SWAP"
    
    def _build_okx_signature(
        self,
        timestamp: str,
        method: str,
        request_path: str,
        body: str = ''
    ) -> str:
        """
        构建OKX API签名
        
        Args:
            timestamp: ISO 8601格式的时间戳（如：2020-12-08T09:08:57.715Z）
            method: HTTP方法（GET/POST）
            request_path: 请求路径，GET请求包含查询参数（如 /api/v5/account/positions-history?instType=SWAP&instId=ETH-USDT-SWAP）
            body: 请求体（GET请求为空字符串，POST请求为JSON字符串）
            
        Returns:
            签名字符串（Base64编码）
        """
        message = timestamp + method + request_path + body
        secret = settings.EXCHANGE_SECRET
        if not secret:
            raise ValueError("EXCHANGE_SECRET未配置")
        
        signature = base64.b64encode(
            hmac.new(
                secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        return signature
    
    def _fetch_positions_history(
        self,
        inst_id: str,
        after: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        调用OKX原始API获取仓位历史
        
        Args:
            inst_id: 产品ID（如BTC-USDT-SWAP）
            after: 分页参数，查询仓位更新(uTime)之前的内容（更旧的数据）
            before: 分页参数，查询仓位更新(uTime)之后的内容（更新的数据）
            limit: 返回结果的数量，最大100
            
        Returns:
            仓位历史列表
        """
        try:
            # 检查API密钥配置
            api_key = settings.EXCHANGE_API_KEY
            secret = settings.EXCHANGE_SECRET
            passphrase = settings.EXCHANGE_PASSPHRASE
            
            if not all([api_key, secret, passphrase]):
                logger.warning("OKX API密钥未配置，无法获取仓位历史")
                return []
            
            # 构建请求参数
            params = {
                'instType': 'SWAP',  # 只同步永续合约
                'instId': inst_id,
                'limit': str(min(limit, 100))  # 最大100
            }
            
            # 添加分页参数
            if after:
                params['after'] = after
            if before:
                params['before'] = before
            
            # 构建查询字符串
            query_string = urlencode(params)
            
            # 构建请求路径（GET请求的查询参数包含在requestPath中）
            request_path = '/api/v5/account/positions-history'
            if query_string:
                request_path += '?' + query_string
            
            # 确定API基础URL
            base_url = 'https://www.okx.com'
            
            # 构建完整URL
            url = base_url + request_path
            
            
            # 直接发送请求，避免通过API管理器队列导致时间戳过期
            try:
                # 在实际发送请求时生成时间戳（避免过期）
                now = datetime.now(timezone.utc)
                timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'  # ISO 8601格式，保留毫秒
                
                # 构建签名
                signature = self._build_okx_signature(
                    timestamp=timestamp,
                    method='GET',
                    request_path=request_path,  # 包含查询参数
                    body=''  # GET请求body为空字符串
                )
                
                # 构建请求头
                headers = {
                    'Content-Type': 'application/json',
                    'OK-ACCESS-KEY': api_key,
                    'OK-ACCESS-SIGN': signature,
                    'OK-ACCESS-TIMESTAMP': timestamp,
                    'OK-ACCESS-PASSPHRASE': passphrase
                }
                
                # 如果是模拟盘，添加模拟盘标记头
                if settings.EXCHANGE_SANDBOX:
                    headers['x-simulated-trading'] = '1'
                
                # 简单限流：避免请求过快
                time.sleep(0.2)
                
                http_response = requests.get(url, headers=headers, timeout=30)
                http_response.raise_for_status()
                
                # 解析JSON响应
                try:
                    response = http_response.json()
                except ValueError as json_error:
                    logger.error(f"解析OKX API响应JSON失败: {json_error}, 响应内容: {http_response.text[:500]}")
                    return []
            except requests.exceptions.RequestException as e:
                logger.error(f"调用OKX API失败: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_data = e.response.json()
                        logger.error(f"错误响应: {error_data}")
                        if e.response.status_code == 401:
                            logger.error(
                                f"401认证失败，请检查:\n"
                                f"  1. API Key是否正确\n"
                                f"  2. Secret Key是否正确\n"
                                f"  3. Passphrase是否正确\n"
                                f"  4. 是否使用了正确的环境（模拟盘/实盘）\n"
                                f"  5. 时间戳格式: {timestamp}\n"
                                f"  6. 请求路径: {request_path}\n"
                                f"  7. 签名: {signature}"
                            )
                        elif error_data.get('code') == '50102':
                            logger.error(
                                f"50102时间戳过期错误，请检查:\n"
                                f"  1. 系统时间是否与OKX服务器时间同步\n"
                                f"  2. 时间戳: {timestamp}\n"
                                f"  3. 当前UTC时间: {datetime.now(timezone.utc).isoformat()}\n"
                                f"  4. 建议：确保系统时间与标准时间同步（NTP）"
                            )
                    except:
                        logger.error(f"错误响应内容: {e.response.text[:500]}")
                return []
            except Exception as e:
                logger.error(f"调用OKX API异常: {e}", exc_info=True)
                return []
            
            if not response:
                return []
            
            if not response or response.get('code') != '0':
                error_msg = response.get('msg', '未知错误') if response else '返回结果为空'
                logger.warning(f"获取{inst_id}仓位历史失败: {error_msg}")
                return []
            
            data = response.get('data', [])
            if not data:
                logger.debug(f"{inst_id} 仓位历史数据为空")
                return []
            
            return data
            
        except Exception as e:
            logger.error(f"调用OKX API获取{inst_id}仓位历史失败: {e}", exc_info=True)
            return []
    
    def _save_positions(self, positions: List[Dict[str, Any]]) -> int:
        """
        保存仓位到数据库
        
        Args:
            positions: 仓位列表
            
        Returns:
            成功保存的仓位数量
        """
        if not positions:
            return 0
        
        saved_count = 0
        try:
            with self.db.get_session() as session:
                try:
                    for position_data in positions:
                        try:
                            # 保存完整原始数据
                            if PositionHistoryRepository.insert_position(session, position_data, raw_data=position_data):
                                saved_count += 1
                        except Exception as e:
                            logger.warning(f"保存仓位失败 posId={position_data.get('posId', 'N/A')}, uTime={position_data.get('uTime', 'N/A')}: {e}")
                            continue
                    
                    session.commit()
                    
                except Exception as e:
                    session.rollback()
                    logger.error(f"保存仓位历史到数据库失败: {e}", exc_info=True)
                    raise  # 重新抛出异常，让外层处理
        except Exception as e:
            logger.error(f"数据库会话创建失败: {e}", exc_info=True)
        
        return saved_count
    
    def _sync_symbol_initial(self, symbol: str) -> bool:
        """
        首次同步某个币种的仓位历史（从配置的开始时间拉取）
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            
        Returns:
            是否同步成功
        """
        try:
            inst_id = self._symbol_to_inst_id(symbol)
            # 获取开始时间
            start_time_ms = self._get_start_time_ms()
            
            # 获取数据库最新仓位更新时间
            with self.db.get_session() as session:
                latest_u_time_ms, latest_u_time = PositionHistoryRepository.get_latest_position_time(session, symbol=symbol)
            
            if latest_u_time_ms:
                return self._sync_symbol_incremental(symbol)
            
            # 首次同步：从开始时间拉取，使用after参数（拉取更旧的数据）
            total_saved = 0
            after = None  # after参数是时间戳（毫秒），查询uTime之前的内容
            max_iterations = 1000  # 防止无限循环
            iteration = 0
            last_after = None  # 记录上次的after参数，防止死循环
            
            # 获取当前时间作为结束时间（毫秒时间戳）
            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            # 首次同步：从当前时间往前拉取，使用after参数
            # after参数是时间戳，查询uTime < after的数据（更旧的数据）
            after = str(current_time_ms)  # 从当前时间开始往前拉取
            
            while iteration < max_iterations:
                iteration += 1
                
                # 防止死循环：如果after参数没有变化，说明没有新数据，停止同步
                if after == last_after:
                    break
                last_after = after
                
                # 获取仓位历史（使用after参数拉取更旧的数据）
                positions = self._fetch_positions_history(
                    inst_id,
                    after=after,
                    limit=100
                )
                
                if not positions:
                    break
                
                # 过滤掉uTime < start_time_ms的数据（只保存符合时间范围的数据）
                # 同时找到所有数据中的最小uTime（用于判断是否继续拉取）
                filtered_positions = []
                min_u_time_all = None  # 所有数据中的最小uTime（用于判断是否继续拉取）
                min_u_time_filtered = None  # 过滤后数据中的最小uTime（用于分页）
                max_u_time = None
                for pos in positions:
                    u_time_str = pos.get('uTime', '')
                    if u_time_str:
                        try:
                            u_time_ms = int(u_time_str)
                            # 记录所有数据中的最小uTime
                            if min_u_time_all is None or u_time_ms < min_u_time_all:
                                min_u_time_all = u_time_ms
                            # 只保留uTime >= start_time_ms的数据
                            if u_time_ms >= start_time_ms:
                                filtered_positions.append(pos)
                                if min_u_time_filtered is None or u_time_ms < min_u_time_filtered:
                                    min_u_time_filtered = u_time_ms
                                if max_u_time is None or u_time_ms > max_u_time:
                                    max_u_time = u_time_ms
                        except (ValueError, TypeError):
                            continue
                
                # 保存过滤后的仓位（只保存符合时间范围的数据）
                if filtered_positions:
                    saved_count = self._save_positions(filtered_positions)
                    total_saved += saved_count
                
                # 如果所有数据中的最小uTime已经 <= start_time_ms，说明已经拉取完符合条件的数据
                if min_u_time_all is None:
                    break
                
                if min_u_time_all <= start_time_ms:
                    break
                
                # 如果返回的仓位数少于limit，说明已经拉取完
                if len(positions) < 100:
                    break
                
                # 使用所有数据的最小uTime作为after参数（继续拉取更旧的数据）
                # 这样可以确保不会遗漏任何数据，即使有些数据的uTime < start_time_ms
                # 保存时会再次过滤，所以不会保存不符合条件的数据
                new_after = str(min_u_time_all)
                
                # 防止死循环：如果新的after参数与当前相同，说明所有仓位uTime相同，停止同步
                if new_after == after:
                    break
                
                after = new_after
                
                # 避免请求过快
                time.sleep(0.2)
            
            logger.info(f"{symbol} 仓位历史同步完成，共保存 {total_saved} 条")
            
            # 同步完成后，自动更新trading_relations中缺失的position_history_id
            if total_saved > 0:
                try:
                    with self.db.get_session() as session:
                        # 通过cl_ord_id和时间范围匹配position_history
                        # 策略：对于每个cl_ord_id，找到其平仓订单的时间范围，然后匹配相同symbol和pos_side的position_history
                        update_sql = text("""
                            UPDATE trading_relations tr
                            SET position_history_id = ph.id, updated_at = NOW()
                            FROM order_history oh, position_history ph
                            WHERE tr.ord_id = oh.ord_id
                              AND tr.position_history_id IS NULL
                              AND tr.operation_type IN ('reduce', 'close')
                              AND oh.symbol = ph.symbol
                              AND oh.pos_side = ph.pos_side
                              AND oh.symbol = :symbol
                              AND ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) < 60
                            ORDER BY ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) ASC
                            ON CONFLICT DO NOTHING
                        """)
                        # 使用子查询确保每个trading_relations记录只更新一次
                        update_sql_v2 = text("""
                            WITH matched_ph AS (
                                SELECT DISTINCT ON (tr.id)
                                    tr.id as tr_id,
                                    ph.id as ph_id
                                FROM trading_relations tr
                                JOIN order_history oh ON tr.ord_id = oh.ord_id
                                JOIN position_history ph ON oh.symbol = ph.symbol 
                                    AND oh.pos_side = ph.pos_side
                                WHERE tr.position_history_id IS NULL
                                  AND tr.operation_type IN ('reduce', 'close')
                                  AND oh.symbol = :symbol
                                  AND ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) < 60
                                ORDER BY tr.id, ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) ASC
                            )
                            UPDATE trading_relations tr
                            SET position_history_id = matched_ph.ph_id, updated_at = NOW()
                            FROM matched_ph
                            WHERE tr.id = matched_ph.tr_id
                        """)
                        result = session.execute(update_sql_v2, {'symbol': symbol})
                        session.commit()
                        if result.rowcount > 0:
                            logger.info(f"{symbol} 自动更新了 {result.rowcount} 个trading_relations的position_history_id")
                except Exception as e:
                    logger.warning(f"{symbol} 自动更新position_history_id失败: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"{symbol} 仓位历史首次同步失败: {e}", exc_info=True)
            return False
    
    def _sync_symbol_incremental(self, symbol: str) -> bool:
        """
        增量同步某个币种的仓位历史（拉取数据库最新仓位之后的新仓位）
        
        Args:
            symbol: 币种名称（BTC, ETH等）
            
        Returns:
            是否同步成功
        """
        try:
            inst_id = self._symbol_to_inst_id(symbol)
            
            # 获取数据库最新仓位更新时间
            with self.db.get_session() as session:
                latest_u_time_ms, latest_u_time = PositionHistoryRepository.get_latest_position_time(session, symbol=symbol)
            
            if not latest_u_time_ms:
                return self._sync_symbol_initial(symbol)
            
            # 增量同步：使用before参数拉取更新的数据
            # before参数是时间戳，查询uTime > before的数据（更新的数据）
            # 从最新u_time开始，使用before参数往前拉取
            total_saved = 0
            before = str(latest_u_time_ms)  # 从最新u_time开始往前拉取
            max_iterations = 100  # 增量同步通常数据量不大，限制迭代次数
            iteration = 0
            last_before = None  # 记录上次的before参数，防止死循环
            
            # 获取当前时间作为结束时间（毫秒时间戳）
            current_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            
            while iteration < max_iterations:
                iteration += 1
                
                # 防止死循环：如果before参数没有变化，说明没有新数据，停止同步
                if before == last_before:
                    break
                last_before = before
                
                # 使用before参数拉取更新的数据
                positions = self._fetch_positions_history(
                    inst_id,
                    before=before,
                    limit=100
                )
                
                if not positions:
                    break
                
                # 保存仓位
                saved_count = self._save_positions(positions)
                total_saved += saved_count
                
                # 如果返回的仓位数少于limit，说明已经拉取完
                if len(positions) < 100:
                    break
                
                # 使用最后一个仓位的最大uTime作为before参数（继续拉取更新的数据）
                # 注意：需要找到最大的uTime
                max_u_time = None
                for pos in positions:
                    u_time_str = pos.get('uTime', '')
                    if u_time_str:
                        try:
                            u_time_ms = int(u_time_str)
                            if max_u_time is None or u_time_ms > max_u_time:
                                max_u_time = u_time_ms
                        except (ValueError, TypeError):
                            continue
                
                if max_u_time is None:
                    break
                
                # 如果已经到达当前时间，停止同步
                if max_u_time >= current_time_ms:
                    break
                
                # 使用最大uTime作为before参数（继续拉取更新的数据）
                new_before = str(max_u_time)
                
                # 防止死循环：如果新的before参数与当前相同，说明所有仓位uTime相同，停止同步
                if new_before == before:
                    break
                
                before = new_before
                
                # 避免请求过快
                time.sleep(0.2)
            
            if total_saved > 0:
                logger.info(f"{symbol} 仓位历史同步完成，新增 {total_saved} 条")
                
                # 同步完成后，自动更新trading_relations中缺失的position_history_id
                try:
                    with self.db.get_session() as session:
                        # 通过symbol、pos_side和时间范围匹配position_history.id
                        # 策略：匹配相同symbol和pos_side的position_history，时间差在60秒内
                        update_sql_v2 = text("""
                            WITH matched_ph AS (
                                SELECT DISTINCT ON (tr.id)
                                    tr.id as tr_id,
                                    ph.id as ph_id
                                FROM trading_relations tr
                                JOIN order_history oh ON tr.ord_id = oh.ord_id
                                JOIN position_history ph ON oh.symbol = ph.symbol 
                                    AND oh.pos_side = ph.pos_side
                                WHERE tr.position_history_id IS NULL
                                  AND tr.operation_type IN ('reduce', 'close')
                                  AND oh.symbol = :symbol
                                  AND ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) < 60
                                ORDER BY tr.id, ABS(EXTRACT(EPOCH FROM (oh.fill_time - ph.u_time))) ASC
                            )
                            UPDATE trading_relations tr
                            SET position_history_id = matched_ph.ph_id, updated_at = NOW()
                            FROM matched_ph
                            WHERE tr.id = matched_ph.tr_id
                        """)
                        result = session.execute(update_sql_v2, {'symbol': symbol})
                        session.commit()
                        if result.rowcount > 0:
                            logger.info(f"{symbol} 自动更新了 {result.rowcount} 个trading_relations的position_history_id")
                except Exception as e:
                    logger.warning(f"{symbol} 自动更新position_history_id失败: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"{symbol} 仓位历史增量同步失败: {e}", exc_info=True)
            return False
    
    def _sync_all_symbols(self):
        """同步所有配置的币种"""
        for symbol in self.sync_symbols:
            try:
                # 增量同步
                self._sync_symbol_incremental(symbol)
            except Exception as e:
                logger.error(f"{symbol} 仓位历史同步异常: {e}", exc_info=True)
                continue
        
        self.last_sync_time = datetime.now(timezone.utc)
    
    def run(self):
        """线程主循环"""
        # 启动时先执行一次首次同步（如果需要）
        try:
            # 检查是否需要首次同步
            need_initial_sync = False
            for symbol in self.sync_symbols:
                with self.db.get_session() as session:
                    latest_u_time_ms, _ = PositionHistoryRepository.get_latest_position_time(session, symbol=symbol)
                    if not latest_u_time_ms:
                        need_initial_sync = True
                        break
            
            if need_initial_sync:
                for symbol in self.sync_symbols:
                    self._sync_symbol_initial(symbol)
        except Exception as e:
            logger.error(f"首次同步检查失败: {e}", exc_info=True)
        
        # 主循环：每30秒执行一次同步
        while not self.stop_event.is_set():
            try:
                self._sync_all_symbols()
                
                # 等待30秒后继续
                self.stop_event.wait(30)
                
            except Exception as e:
                logger.error(f"仓位历史同步循环异常: {e}", exc_info=True)
                # 出错时等待30秒再继续
                self.stop_event.wait(30)

