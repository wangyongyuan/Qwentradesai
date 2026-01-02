#!/usr/bin/env python3
"""
外部平仓自动化测试工具
按照 test_cases.md 的测试场景执行
每个步骤间隔10秒
外部平仓直接调用OKX API，不写业务逻辑
"""
from pickle import TRUE
import requests
import time
import json
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from enum import Enum
from app.components.api_manager import APIManager, RequestPriority
from app.config import settings
from app.utils.logger import logger


# 配置
BASE_URL = "https://apidata.gufii6.xyz"
STEP_INTERVAL = 10  # 每步间隔3秒
SCENARIO_INTERVAL = 10  # 场景之间间隔10秒
AUTO_MODE = TRUE  # 自动模式：True=全自动（场景间自动等待），False=手动模式（需要按回车）
MAX_RETRY_COUNT = 3  # 自动重试次数，失败后自动重试3次，3次都失败后停止
# ETH当前价格：3798
# LONG方向：止损低于当前价格，止盈高于当前价格
STOP_LOSS_TRIGGER_ETH_LONG = 3500.0  # LONG止损（低于3798）
TAKE_PROFIT_TRIGGER_ETH_LONG = 5000.0  # LONG止盈（高于3798）
# SHORT方向：止损高于当前价格，止盈低于当前价格
STOP_LOSS_TRIGGER_ETH_SHORT = 5000.0  # SHORT止损（高于3798）
TAKE_PROFIT_TRIGGER_ETH_SHORT = 3500.0  # SHORT止盈（低于3798）
LEVERAGE = 10


class StepType(Enum):
    """步骤类型"""
    API_OPEN = "API开仓"
    API_ADD = "API加仓"
    API_REDUCE = "API减仓"
    API_CLOSE = "API全部平仓"
    EXTERNAL_CLOSE_PARTIAL = "外部部分平仓"
    EXTERNAL_CLOSE_FULL = "外部全部平仓"


@dataclass
class TestStep:
    """测试步骤"""
    step_type: StepType
    amount: Optional[float] = None  # 数量（币数量），None表示全部
    description: str = ""  # 步骤描述


@dataclass
class TestScenario:
    """测试场景"""
    name: str
    scenario_num: int
    symbol: str  # ETH 或 BTC
    side: str  # LONG 或 SHORT
    signal_id: int
    steps: List[TestStep]
    stop_loss_trigger: float
    take_profit_trigger: float


class TradingTestClient:
    """交易测试客户端（用于API操作）"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
    
    def open_position(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_loss_trigger: float,
        take_profit_trigger: float,
        leverage: float,
        signal_id: int
    ) -> Dict[str, Any]:
        """开仓"""
        url = f"{self.base_url}/trading/open-position"
        data = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "stop_loss_trigger": stop_loss_trigger,
            "take_profit_trigger": take_profit_trigger,
            "leverage": leverage,
            "signal_id": signal_id
        }
        response = self.session.post(url, json=data)
        result = response.json()
        if result.get("status") != "success":
            raise Exception(f"开仓失败: {result}")
        return result
    
    def add_position(self, cl_ord_id: str, amount: float) -> Dict[str, Any]:
        """加仓"""
        url = f"{self.base_url}/trading/add-position"
        data = {"cl_ord_id": cl_ord_id, "amount": amount}
        response = self.session.post(url, json=data)
        result = response.json()
        if result.get("status") != "success":
            raise Exception(f"加仓失败: {result}")
        return result
    
    def reduce_position(self, cl_ord_id: str, amount: float) -> Dict[str, Any]:
        """减仓"""
        url = f"{self.base_url}/trading/reduce-position"
        data = {"cl_ord_id": cl_ord_id, "amount": amount}
        response = self.session.post(url, json=data)
        result = response.json()
        if result.get("status") != "success":
            raise Exception(f"减仓失败: {result}")
        return result
    
    def close_position(self, cl_ord_id: str, amount: Optional[float] = None) -> Dict[str, Any]:
        """平仓"""
        url = f"{self.base_url}/trading/close-position"
        data = {"cl_ord_id": cl_ord_id, "amount": amount}
        response = self.session.post(url, json=data)
        result = response.json()
        if result.get("status") != "success":
            raise Exception(f"平仓失败: {result}")
        return result


class ExternalCloseClient:
    """外部平仓客户端（直接调用OKX API，不写业务逻辑）"""
    
    def __init__(self):
        self.api_manager = APIManager()
        self.api_manager.start()
    
    def get_positions(self, inst_id: str) -> List[Dict[str, Any]]:
        """查询当前持仓"""
        def _get_positions():
            try:
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法查询持仓")
                
                result = self.api_manager.exchange.private_get_account_positions({
                    'instId': inst_id
                })
                
                if result and result.get('code') == '0':
                    data = result.get('data', [])
                    return data if isinstance(data, list) else []
                else:
                    error_msg = result.get('msg', '未知错误') if result else '返回结果为空'
                    raise Exception(f"查询持仓失败: {error_msg}")
            except Exception as e:
                logger.error(f"查询持仓失败: {e}", exc_info=True)
                raise
        
        result = self.api_manager.submit_request(
            RequestPriority.QUERY,
            _get_positions
        )
        # 确保返回的是列表，如果为None则返回空列表
        return result if result is not None and isinstance(result, list) else []
    
    def close_position_external(
        self,
        inst_id: str,
        pos_side: str,
        amount: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        外部平仓（直接调用OKX API，不写业务逻辑）
        
        Args:
            inst_id: 交易对ID，如 'ETH-USDT-SWAP'
            pos_side: 持仓方向，'long' 或 'short'
            amount: 平仓数量（币的数量），None表示全部平仓
        """
        def _close_position():
            try:
                if not settings.EXCHANGE_API_KEY:
                    raise ValueError("EXCHANGE_API_KEY未配置，无法平仓")
                
                # 查询当前持仓
                positions = self.get_positions(inst_id)
                if positions is None:
                    raise Exception(f"查询持仓返回None: instId={inst_id}")
                
                if not isinstance(positions, list):
                    raise Exception(f"查询持仓返回类型错误: {type(positions)}, 期望list")
                
                current_position = None
                for pos in positions:
                    if pos.get('posSide') == pos_side and float(pos.get('pos', 0)) > 0:
                        current_position = pos
                        break
                
                if not current_position:
                    raise Exception(f"未找到持仓: instId={inst_id}, posSide={pos_side}")
                
                # 获取合约信息
                ccxt_symbol = inst_id.replace('-SWAP', '/USDT:USDT').replace('-', '/')
                try:
                    market = self.api_manager.exchange.market(ccxt_symbol)
                    contract_size = market.get('contractSize', 0.1)
                except:
                    if 'ETH' in inst_id.upper():
                        contract_size = 0.1
                    else:
                        contract_size = 1.0
                    logger.warning(f"无法获取合约信息，使用默认合约乘数: {contract_size}")
                
                # 当前持仓数量（合约张数）
                current_pos_contracts = float(current_position.get('pos', 0))
                # 当前持仓数量（币的数量）
                if contract_size != 1.0 and contract_size > 0:
                    current_pos_coins = current_pos_contracts * contract_size
                else:
                    current_pos_coins = current_pos_contracts
                
                # 确定平仓数量（币的数量）
                if amount is None:
                    close_amount_coins = current_pos_coins
                else:
                    close_amount_coins = min(amount, current_pos_coins)
                
                if close_amount_coins <= 0:
                    raise Exception(f"平仓数量无效: {close_amount_coins}")
                
                # 将币的数量转换为合约张数
                if contract_size != 1.0 and contract_size > 0:
                    order_amount = round(close_amount_coins / contract_size, 1)
                else:
                    order_amount = close_amount_coins
                
                # 确定平仓方向（反向平仓）
                if pos_side == 'long':
                    okx_side = 'sell'
                elif pos_side == 'short':
                    okx_side = 'buy'
                else:
                    raise ValueError(f"未知的持仓方向: {pos_side}")
                
                # 获取杠杆
                leverage = current_position.get('lever', '10')
                
                # 构建OKX API参数
                okx_params = {
                    'instId': inst_id,
                    'tdMode': 'cross',
                    'side': okx_side,
                    'ordType': 'market',
                    'sz': str(order_amount),
                    'posSide': pos_side,
                    'lever': str(leverage),
                    'reduceOnly': 'true'
                }
                
                logger.info(f"[外部平仓] OKX API参数: {okx_params}")
                
                # 调用OKX API下单
                result = self.api_manager.exchange.private_post_trade_order(okx_params)
                
                if result and result.get('code') == '0' and result.get('data'):
                    order_data = result['data'][0]
                    logger.info(
                        f"[外部平仓] 平仓成功: ordId={order_data.get('ordId')}, "
                        f"平仓数量（币）={close_amount_coins:.6f}, 合约张数={order_amount:.1f}"
                    )
                    return {
                        'success': True,
                        'ordId': order_data.get('ordId'),
                        'closeAmount': close_amount_coins,
                        'contractAmount': order_amount
                    }
                else:
                    error_msg = result.get('msg', '未知错误') if result else '返回结果为空'
                    error_code = result.get('code', 'N/A') if result else 'N/A'
                    raise Exception(f"外部平仓失败: [{error_code}] {error_msg}")
                    
            except Exception as e:
                logger.error(f"外部平仓失败: {e}", exc_info=True)
                raise
        
        return self.api_manager.submit_request(
            RequestPriority.TRADE,
            _close_position
        )
    
    def stop(self):
        """停止API管理器"""
        self.api_manager.stop()


def execute_step_with_retry(
    step_func: Callable,
    step_name: str,
    step_num: int,
    total_steps: int
) -> Any:
    """执行步骤，支持自动重试和手动重试"""
    retry_count = 0
    
    while True:
        try:
            if retry_count > 0:
                print(f"\n[步骤{step_num}/{total_steps}] {step_name} (重试 {retry_count}/{MAX_RETRY_COUNT})")
            else:
                print(f"\n[步骤{step_num}/{total_steps}] {step_name}")
            
            result = step_func()
            print(f"✓ {step_name} 成功")
            return result
            
        except Exception as e:
            retry_count += 1
            print(f"\n✗ {step_name} 失败 (第{retry_count}次): {e}")
            
            # 如果还没达到最大重试次数，自动重试
            if retry_count < MAX_RETRY_COUNT:
                print(f"自动重试中... ({retry_count}/{MAX_RETRY_COUNT})")
                time.sleep(2)  # 重试前等待2秒
                continue
            
            # 达到最大重试次数，提示用户
            print(f"\n⚠ {step_name} 已重试 {MAX_RETRY_COUNT} 次，仍然失败")
            
            if AUTO_MODE:
                # 自动模式：3次失败后直接跳过
                print(f"自动跳过 {step_name}，继续执行...")
                return None
            else:
                # 手动模式：让用户选择
                while True:
                    choice = input("输入 y 继续重试，输入 n 跳过: ").strip().lower()
                    if choice == 'y':
                        print("继续重试中...")
                        retry_count = 0  # 重置计数，继续重试
                        time.sleep(2)
                        break
                    elif choice == 'n':
                        print(f"跳过 {step_name}")
                        return None
                    else:
                        print("输入错误，请输入 y 或 n")


def run_test_scenario(
    client: TradingTestClient,
    scenario: TestScenario
):
    """执行单个测试场景"""
    print(f"\n{'='*60}")
    print(f"测试场景{scenario.scenario_num}: {scenario.name}")
    print(f"交易对: {scenario.symbol}, 方向: {scenario.side}, signal_id: {scenario.signal_id}")
    print(f"{'='*60}")
    
    cl_ord_id = None
    inst_id = f"{scenario.symbol}-USDT-SWAP"
    pos_side = "long" if scenario.side == "LONG" else "short"
    
    try:
        for i, step in enumerate(scenario.steps, 1):
            # 执行步骤
            if step.step_type == StepType.API_OPEN:
                result = execute_step_with_retry(
                    lambda: client.open_position(
                        symbol=scenario.symbol,
                        side=scenario.side,
                        amount=step.amount,
                        stop_loss_trigger=scenario.stop_loss_trigger,
                        take_profit_trigger=scenario.take_profit_trigger,
                        leverage=LEVERAGE,
                        signal_id=scenario.signal_id
                    ),
                    f"{step.step_type.value} {step.amount} {scenario.symbol}",
                    i,
                    len(scenario.steps)
                )
                if result:
                    cl_ord_id = result.get("cl_ord_id")
                    print(f"  cl_ord_id: {cl_ord_id}")
            
            elif step.step_type == StepType.API_ADD:
                if not cl_ord_id:
                    print("⚠ 警告: cl_ord_id为空，跳过此步骤")
                    continue
                execute_step_with_retry(
                    lambda: client.add_position(cl_ord_id, step.amount),
                    f"{step.step_type.value} {step.amount} {scenario.symbol}",
                    i,
                    len(scenario.steps)
                )
            
            elif step.step_type == StepType.API_REDUCE:
                if not cl_ord_id:
                    print("⚠ 警告: cl_ord_id为空，跳过此步骤")
                    continue
                execute_step_with_retry(
                    lambda: client.reduce_position(cl_ord_id, step.amount),
                    f"{step.step_type.value} {step.amount} {scenario.symbol}",
                    i,
                    len(scenario.steps)
                )
            
            elif step.step_type == StepType.API_CLOSE:
                if not cl_ord_id:
                    print("⚠ 警告: cl_ord_id为空，跳过此步骤")
                    continue
                execute_step_with_retry(
                    lambda: client.close_position(cl_ord_id, amount=None),
                    f"{step.step_type.value}",
                    i,
                    len(scenario.steps)
                )
            
            elif step.step_type == StepType.EXTERNAL_CLOSE_PARTIAL:
                # 外部部分平仓：手动操作
                print(f"\n[步骤{i}/{len(scenario.steps)}] {step.step_type.value} {step.amount} {scenario.symbol}")
                print(f"{'='*60}")
                print(f"请在OKX交易所手动平仓 {step.amount} {scenario.symbol}")
                print(f"交易对: {inst_id}, 方向: {pos_side}")
                print(f"{'='*60}")
                while True:
                    choice = input("平仓完成后，请输入 y 并按回车键继续: ").strip().lower()
                    if choice == 'y':
                        print(f"✓ {step.step_type.value} {step.amount} {scenario.symbol} 完成")
                        break
                    else:
                        print("输入错误，请输入 y 继续...")
            
            elif step.step_type == StepType.EXTERNAL_CLOSE_FULL:
                # 外部全部平仓：手动操作
                print(f"\n[步骤{i}/{len(scenario.steps)}] {step.step_type.value}")
                print(f"{'='*60}")
                print(f"请在OKX交易所手动全部平仓 {scenario.symbol}")
                print(f"交易对: {inst_id}, 方向: {pos_side}")
                print(f"{'='*60}")
                while True:
                    choice = input("平仓完成后，请输入 y 并按回车键继续: ").strip().lower()
                    if choice == 'y':
                        print(f"✓ {step.step_type.value} 完成")
                        break
                    else:
                        print("输入错误，请输入 y 继续...")
            
            # 等待间隔（最后一步不需要等待）
            if i < len(scenario.steps):
                print(f"\n等待 {STEP_INTERVAL} 秒...")
                time.sleep(STEP_INTERVAL)
        
        print(f"\n✓ 测试场景{scenario.scenario_num}完成")
        
    except Exception as e:
        print(f"\n✗ 测试场景{scenario.scenario_num}失败: {e}")
        import traceback
        traceback.print_exc()
        raise


def create_test_scenarios() -> List[TestScenario]:
    """创建测试场景列表"""
    scenarios = []
    
    # 场景1：基础开平仓流程（ETH）
    scenarios.append(TestScenario(
        name="基础开平仓流程（ETH）",
        scenario_num=1,
        symbol="ETH",
        side="LONG",
        signal_id=60,
        steps=[
            TestStep(StepType.API_OPEN, 10.0, "API开仓 10 ETH"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景2：加仓减仓流程（ETH）
    scenarios.append(TestScenario(
        name="加仓减仓流程（ETH）",
        scenario_num=2,
        symbol="ETH",
        side="LONG",
        signal_id=61,
        steps=[
            TestStep(StepType.API_OPEN, 10.0, "API开仓 10 ETH"),
            TestStep(StepType.API_ADD, 20.0, "API加仓 20 ETH"),
            TestStep(StepType.API_REDUCE, 5.0, "API减仓 5 ETH"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景3：外部部分平仓（ETH）
    scenarios.append(TestScenario(
        name="外部部分平仓（ETH）",
        scenario_num=3,
        symbol="ETH",
        side="LONG",
        signal_id=62,
        steps=[
            TestStep(StepType.API_OPEN, 20.0, "API开仓 20 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 5.0, "外部部分平仓 5 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景4：混合操作流程（ETH）
    scenarios.append(TestScenario(
        name="混合操作流程（ETH）",
        scenario_num=4,
        symbol="ETH",
        side="LONG",
        signal_id=63,
        steps=[
            TestStep(StepType.API_OPEN, 10.0, "API开仓 10 ETH"),
            TestStep(StepType.API_ADD, 20.0, "API加仓 20 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 15.0, "外部部分平仓 15 ETH"),
            TestStep(StepType.API_REDUCE, 5.0, "API减仓 5 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景5：多次加仓流程（ETH）
    scenarios.append(TestScenario(
        name="多次加仓流程（ETH）",
        scenario_num=5,
        symbol="ETH",
        side="LONG",
        signal_id=64,
        steps=[
            TestStep(StepType.API_OPEN, 10.0, "API开仓 10 ETH"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH（第一次）"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH（第二次）"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH（第三次）"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景6：多次减仓流程（ETH）
    scenarios.append(TestScenario(
        name="多次减仓流程（ETH）",
        scenario_num=6,
        symbol="ETH",
        side="LONG",
        signal_id=65,
        steps=[
            TestStep(StepType.API_OPEN, 50.0, "API开仓 50 ETH"),
            TestStep(StepType.API_REDUCE, 10.0, "API减仓 10 ETH（第一次）"),
            TestStep(StepType.API_REDUCE, 10.0, "API减仓 10 ETH（第二次）"),
            TestStep(StepType.API_REDUCE, 10.0, "API减仓 10 ETH（第三次）"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景7：外部多次平仓（ETH）
    scenarios.append(TestScenario(
        name="外部多次平仓（ETH）",
        scenario_num=7,
        symbol="ETH",
        side="LONG",
        signal_id=66,
        steps=[
            TestStep(StepType.API_OPEN, 30.0, "API开仓 30 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH（第一次）"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH（第二次）"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景8：SHORT方向测试（ETH）
    scenarios.append(TestScenario(
        name="SHORT方向测试（ETH）",
        scenario_num=8,
        symbol="ETH",
        side="SHORT",
        signal_id=67,
        steps=[
            TestStep(StepType.API_OPEN, 10.0, "API开仓（做空）10 ETH"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH"),
            TestStep(StepType.API_REDUCE, 5.0, "API减仓 5 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_SHORT,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_SHORT
    ))
    
    # 场景9：复杂混合场景（ETH）
    scenarios.append(TestScenario(
        name="复杂混合场景（ETH）",
        scenario_num=9,
        symbol="ETH",
        side="LONG",
        signal_id=68,
        steps=[
            TestStep(StepType.API_OPEN, 20.0, "API开仓 20 ETH"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH（第一次）"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH（第一次）"),
            TestStep(StepType.API_ADD, 15.0, "API加仓 15 ETH（第二次）"),
            TestStep(StepType.API_REDUCE, 5.0, "API减仓 5 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH（第二次）"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景10：小数量测试（ETH）
    scenarios.append(TestScenario(
        name="小数量测试（ETH）",
        scenario_num=10,
        symbol="ETH",
        side="LONG",
        signal_id=69,
        steps=[
            TestStep(StepType.API_OPEN, 0.1, "API开仓 0.1 ETH"),
            TestStep(StepType.API_ADD, 0.2, "API加仓 0.2 ETH"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景11：外部平仓后API操作（ETH）
    scenarios.append(TestScenario(
        name="外部平仓后API操作（ETH）",
        scenario_num=11,
        symbol="ETH",
        side="LONG",
        signal_id=70,
        steps=[
            TestStep(StepType.API_OPEN, 15.0, "API开仓 15 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 5.0, "外部部分平仓 5 ETH"),
            TestStep(StepType.API_ADD, 10.0, "API加仓 10 ETH"),
            TestStep(StepType.API_CLOSE, None, "API全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景12：SHORT方向外部平仓（ETH）
    scenarios.append(TestScenario(
        name="SHORT方向外部平仓（ETH）",
        scenario_num=12,
        symbol="ETH",
        side="SHORT",
        signal_id=71,
        steps=[
            TestStep(StepType.API_OPEN, 20.0, "API开仓（做空）20 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 8.0, "外部部分平仓 8 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 7.0, "外部部分平仓 7 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_SHORT,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_SHORT
    ))
    
    # 场景13：大数量测试（ETH）
    scenarios.append(TestScenario(
        name="大数量测试（ETH）",
        scenario_num=13,
        symbol="ETH",
        side="LONG",
        signal_id=72,
        steps=[
            TestStep(StepType.API_OPEN, 100.0, "API开仓 100 ETH"),
            TestStep(StepType.API_ADD, 50.0, "API加仓 50 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 75.0, "外部部分平仓 75 ETH"),
            TestStep(StepType.API_REDUCE, 25.0, "API减仓 25 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    # 场景14：复杂交替操作（外部-API-外部-API-外部）
    scenarios.append(TestScenario(
        name="复杂交替操作（外部-API-外部-API-外部）",
        scenario_num=14,
        symbol="ETH",
        side="LONG",
        signal_id=73,
        steps=[
            TestStep(StepType.API_OPEN, 25.0, "API开仓 25 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 8.0, "外部部分平仓 8 ETH（第一次）"),
            TestStep(StepType.API_ADD, 12.0, "API加仓 12 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 10.0, "外部部分平仓 10 ETH（第二次）"),
            TestStep(StepType.API_REDUCE, 5.0, "API减仓 5 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_PARTIAL, 7.0, "外部部分平仓 7 ETH（第三次）"),
            TestStep(StepType.API_ADD, 3.0, "API加仓 3 ETH"),
            TestStep(StepType.EXTERNAL_CLOSE_FULL, None, "外部全部平仓"),
        ],
        stop_loss_trigger=STOP_LOSS_TRIGGER_ETH_LONG,
        take_profit_trigger=TAKE_PROFIT_TRIGGER_ETH_LONG
    ))
    
    return scenarios


def main():
    """主函数"""
    print("="*60)
    print("外部平仓自动化测试工具")
    print("按照 test_cases.md 的测试场景执行")
    print("="*60)
    print(f"接口地址: {BASE_URL}")
    print(f"每步间隔: {STEP_INTERVAL}秒")
    print("="*60)
    
    scenarios = create_test_scenarios()
    
    print(f"\n共 {len(scenarios)} 个测试场景：")
    for scenario in scenarios:
        print(f"  场景{scenario.scenario_num}: {scenario.name} ({scenario.symbol}, {scenario.side}, signal_id={scenario.signal_id})")
    
    if AUTO_MODE:
        print(f"\n自动模式：场景之间自动等待 {SCENARIO_INTERVAL} 秒")
        print("3秒后开始测试...")
        time.sleep(3)
    else:
        input("\n手动模式：按回车键开始测试...")
    
    client = TradingTestClient(BASE_URL)
    
    for i, scenario in enumerate(scenarios, 1):
        try:
            print(f"\n\n{'#'*60}")
            print(f"开始执行测试场景 {i}/{len(scenarios)}: {scenario.name}")
            print(f"{'#'*60}")
            
            run_test_scenario(client, scenario)
            
            print(f"\n✓ 测试场景 {i} 完成")
            
            if i < len(scenarios):
                if AUTO_MODE:
                    print(f"\n等待 {SCENARIO_INTERVAL} 秒后继续下一个场景...")
                    time.sleep(SCENARIO_INTERVAL)
                else:
                    input("\n按回车键继续下一个测试场景...")
        except Exception as e:
            print(f"\n✗ 测试场景 {i} 执行失败: {e}")
            import traceback
            traceback.print_exc()
            if i < len(scenarios):
                choice = input("是否继续下一个场景？(y/n): ").strip().lower()
                if choice != 'y':
                    print("测试中断")
                    break
    
    print(f"\n\n{'='*60}")
    print("所有测试场景执行完成！")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
