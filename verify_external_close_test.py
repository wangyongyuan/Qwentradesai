#!/usr/bin/env python3
"""
外部平仓测试数据验证脚本
按照 external_close_test.py 的测试场景执行数据验证
分三个步骤：
第一步：trading_relations 表验证
第二步：order_history 表验证
第三步：数据一致性验证
"""
import os
import sys
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
from decimal import Decimal
import importlib.util

# 加载环境变量
load_dotenv()

# 合约乘数配置
CONTRACT_SIZE = {
    'ETH': 0.1,
    'BTC': 1.0
}


def get_test_scenarios():
    """从 external_close_test.py 读取测试场景配置"""
    script_path = os.path.join(os.path.dirname(__file__), 'external_close_test.py')
    
    if not os.path.exists(script_path):
        raise FileNotFoundError(f"未找到测试脚本: {script_path}")
    
    # 动态导入模块
    spec = importlib.util.spec_from_file_location("external_close_test", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    # 调用 create_test_scenarios 函数
    scenarios = module.create_test_scenarios()
    
    # 转换为字典格式，便于验证
    scenarios_dict = {}
    for scenario in scenarios:
        scenarios_dict[scenario.signal_id] = {
            'name': scenario.name,
            'scenario_num': scenario.scenario_num,
            'symbol': scenario.symbol,
            'side': scenario.side,
            'signal_id': scenario.signal_id,
            'steps': [
                {
                    'step_type': step.step_type.value,
                    'amount': step.amount,
                    'description': step.description
                }
                for step in scenario.steps
            ]
        }
    
    return scenarios_dict


class ExternalCloseTestVerifier:
    """外部平仓测试数据验证器"""
    
    def __init__(self):
        """初始化数据库连接"""
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("未找到DATABASE_URL环境变量，请在.env文件中配置")
        
        print(f"正在连接数据库: {self.database_url.split('@')[1] if '@' in self.database_url else '***'}")
        
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            pool_recycle=3600
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.session: Optional[Session] = None
        
        # 测试场景配置
        self.test_scenarios = get_test_scenarios()
        
        # 验证结果
        self.step1_results = {}  # trading_relations 验证结果
        self.step2_results = {}   # order_history 验证结果
        self.step3_results = {}   # 数据一致性验证结果
    
    def connect(self):
        """建立数据库连接"""
        try:
            self.session = self.SessionLocal()
            self.session.execute(text("SELECT 1"))
            print("✓ 数据库连接成功\n")
            return True
        except Exception as e:
            print(f"✗ 数据库连接失败: {e}")
            return False
    
    def close(self):
        """关闭数据库连接"""
        if self.session:
            self.session.close()
        self.engine.dispose()
    
    def float_compare(self, a: float, b: float, tolerance: float = 0.01) -> bool:
        """比较两个浮点数（允许误差）"""
        if a is None or b is None:
            return False
        return abs(a - b) <= tolerance
    
    def get_contract_size(self, symbol: str) -> float:
        """获取合约乘数"""
        return CONTRACT_SIZE.get(symbol.upper(), 0.1)
    
    def get_trading_relations_by_signal_id(self, signal_id: int) -> List[Dict[str, Any]]:
        """根据signal_id获取trading_relations记录"""
        sql = text("""
            SELECT 
                id, signal_id, cl_ord_id, ord_id, position_history_id,
                operation_type, amount, price, created_at
            FROM trading_relations
            WHERE signal_id = :signal_id
            ORDER BY created_at ASC
        """)
        result = self.session.execute(sql, {'signal_id': signal_id}).fetchall()
        
        records = []
        for row in result:
            records.append({
                'id': row[0],
                'signal_id': row[1],
                'cl_ord_id': row[2],
                'ord_id': row[3],
                'position_history_id': row[4],
                'operation_type': row[5],
                'amount': float(row[6]) if row[6] else None,
                'price': float(row[7]) if row[7] else None,
                'created_at': row[8]
            })
        return records
    
    def get_order_history_by_cl_ord_id(self, cl_ord_id: str) -> List[Dict[str, Any]]:
        """根据cl_ord_id获取order_history记录"""
        sql = text("""
            SELECT 
                ord_id, cl_ord_id, symbol, inst_id, sz, side, pos_side,
                state, acc_fill_sz, fill_px, fill_time, c_time
            FROM order_history
            WHERE cl_ord_id = :cl_ord_id
            ORDER BY c_time ASC
        """)
        result = self.session.execute(sql, {'cl_ord_id': cl_ord_id}).fetchall()
        
        orders = []
        for row in result:
            orders.append({
                'ord_id': row[0],
                'cl_ord_id': row[1],
                'symbol': row[2],
                'inst_id': row[3],
                'sz': float(row[4]) if row[4] else 0.0,  # 合约数量
                'side': row[5],
                'pos_side': row[6],
                'state': row[7],
                'acc_fill_sz': float(row[8]) if row[8] else 0.0,
                'fill_px': float(row[9]) if row[9] else None,
                'fill_time': row[10],
                'c_time': row[11]
            })
        return orders
    
    def get_order_history_by_ord_id(self, ord_id: str) -> Optional[Dict[str, Any]]:
        """根据ord_id获取order_history记录"""
        sql = text("""
            SELECT 
                ord_id, cl_ord_id, symbol, inst_id, sz, side, pos_side,
                state, acc_fill_sz, fill_px, fill_time, c_time
            FROM order_history
            WHERE ord_id = :ord_id
            LIMIT 1
        """)
        result = self.session.execute(sql, {'ord_id': ord_id}).fetchone()
        
        if result:
            return {
                'ord_id': result[0],
                'cl_ord_id': result[1],
                'symbol': result[2],
                'inst_id': result[3],
                'sz': float(result[4]) if result[4] else 0.0,
                'side': result[5],
                'pos_side': result[6],
                'state': result[7],
                'acc_fill_sz': float(result[8]) if result[8] else 0.0,
                'fill_px': float(result[9]) if result[9] else None,
                'fill_time': result[10],
                'c_time': result[11]
            }
        return None
    
    def step1_verify_trading_relations(self):
        """第一步：trading_relations 表验证"""
        print("="*60)
        print("第一步：trading_relations 表验证")
        print("="*60)
        
        for signal_id in sorted(self.test_scenarios.keys()):
            scenario = self.test_scenarios[signal_id]
            result = self._verify_trading_relations_scenario(signal_id, scenario)
            self.step1_results[signal_id] = result
        
        # 汇总结果
        self._print_step1_summary()
    
    def _verify_trading_relations_scenario(self, signal_id: int, scenario: Dict) -> Dict[str, Any]:
        """验证单个场景的 trading_relations 数据"""
        scenario_name = scenario['name']
        scenario_num = scenario['scenario_num']
        symbol = scenario['symbol']
        side = scenario['side']
        steps = scenario['steps']
        
        print(f"\n{'='*60}")
        print(f"验证场景{scenario_num}: {scenario_name} (signal_id={signal_id})")
        print(f"交易对: {symbol}, 方向: {side}")
        print(f"{'='*60}")
        
        # 获取实际记录
        actual_records = self.get_trading_relations_by_signal_id(signal_id)
        
        result = {
            'signal_id': signal_id,
            'scenario_num': scenario_num,
            'scenario_name': scenario_name,
            'symbol': symbol,
            'side': side,
            'passed': True,
            'errors': [],
            'warnings': [],
            'actual_count': len(actual_records),
            'expected_count': len(steps)
        }
        
        # 1. 检查记录数量
        expected_count = len([s for s in steps if s['step_type'] in ['API开仓', 'API加仓', 'API减仓', 'API全部平仓', '外部部分平仓', '外部全部平仓']])
        if len(actual_records) != expected_count:
            result['passed'] = False
            error_msg = f"记录数量不匹配: 期望{expected_count}条，实际{len(actual_records)}条"
            result['errors'].append(error_msg)
            print(f"✗ {error_msg}")
        else:
            print(f"✓ 记录数量正确: {len(actual_records)}条")
        
        if len(actual_records) == 0:
            result['passed'] = False
            result['errors'].append("未找到任何记录")
            return result
        
        # 2. 检查 cl_ord_id 一致性
        cl_ord_ids = set(r['cl_ord_id'] for r in actual_records if r['cl_ord_id'])
        if len(cl_ord_ids) > 1:
            result['passed'] = False
            error_msg = f"cl_ord_id不一致: {cl_ord_ids}"
            result['errors'].append(error_msg)
            print(f"✗ {error_msg}")
        elif len(cl_ord_ids) == 1:
            print(f"✓ cl_ord_id一致: {list(cl_ord_ids)[0]}")
        else:
            result['warnings'].append("所有记录的cl_ord_id为空")
            print(f"⚠ 所有记录的cl_ord_id为空")
        
        # 3. 检查 signal_id 一致性
        signal_ids = set(r['signal_id'] for r in actual_records)
        if len(signal_ids) > 1 or (signal_ids and list(signal_ids)[0] != signal_id):
            result['passed'] = False
            error_msg = f"signal_id不一致: {signal_ids}"
            result['errors'].append(error_msg)
            print(f"✗ {error_msg}")
        else:
            print(f"✓ signal_id一致: {signal_id}")
        
        # 4. 检查操作类型和数量
        api_steps = [s for s in steps if s['step_type'] in ['API开仓', 'API加仓', 'API减仓', 'API全部平仓']]
        external_steps = [s for s in steps if s['step_type'] in ['外部部分平仓', '外部全部平仓']]
        
        # 映射操作类型
        operation_type_map = {
            'API开仓': 'open',
            'API加仓': 'add',
            'API减仓': 'reduce',
            'API全部平仓': 'close',
            '外部部分平仓': 'reduce',
            '外部全部平仓': 'close'
        }
        
        # 验证API操作的记录
        api_record_idx = 0
        for i, step in enumerate(steps):
            step_type = step['step_type']
            if step_type not in operation_type_map:
                continue
            
            expected_op_type = operation_type_map[step_type]
            expected_amount = step['amount']
            
            if api_record_idx >= len(actual_records):
                result['passed'] = False
                error_msg = f"缺少第{api_record_idx+1}条记录: 期望{expected_op_type}, amount={expected_amount}"
                result['errors'].append(error_msg)
                print(f"✗ {error_msg}")
                continue
            
            actual_record = actual_records[api_record_idx]
            
            # 检查 operation_type
            if actual_record['operation_type'] != expected_op_type:
                result['passed'] = False
                error_msg = f"第{api_record_idx+1}条记录operation_type错误: 期望{expected_op_type}, 实际{actual_record['operation_type']}"
                result['errors'].append(error_msg)
                print(f"✗ {error_msg}")
            else:
                print(f"✓ 第{api_record_idx+1}条记录operation_type正确: {expected_op_type}")
            
            # 检查 amount（对于外部平仓，amount可能不准确，只检查API操作）
            if step_type in ['API开仓', 'API加仓', 'API减仓', 'API全部平仓']:
                if actual_record['amount'] is None:
                    if expected_amount is not None and expected_amount > 0:
                        result['passed'] = False
                        error_msg = f"第{api_record_idx+1}条记录amount为空，期望{expected_amount}"
                        result['errors'].append(error_msg)
                        print(f"✗ {error_msg}")
                elif expected_amount is not None:
                    tolerance = abs(expected_amount * 0.01) if expected_amount > 0 else 0.01
                    if not self.float_compare(actual_record['amount'], expected_amount, tolerance):
                        result['passed'] = False
                        error_msg = f"第{api_record_idx+1}条记录amount错误: 期望{expected_amount}, 实际{actual_record['amount']}"
                        result['errors'].append(error_msg)
                        print(f"✗ {error_msg}")
                    else:
                        print(f"✓ 第{api_record_idx+1}条记录amount正确: {actual_record['amount']} (期望{expected_amount})")
            
            # 检查 ord_id（API操作必须有ord_id，外部平仓可能没有）
            if step_type in ['API开仓', 'API加仓', 'API减仓', 'API全部平仓']:
                if not actual_record['ord_id']:
                    result['warnings'].append(f"第{api_record_idx+1}条API操作记录没有ord_id")
                    print(f"⚠ 第{api_record_idx+1}条API操作记录没有ord_id")
                else:
                    print(f"✓ 第{api_record_idx+1}条记录有ord_id: {actual_record['ord_id']}")
            
            api_record_idx += 1
        
        # 5. 检查最后一条外部平仓是否为 close
        if len(actual_records) > 0:
            last_record = actual_records[-1]
            last_step = steps[-1] if steps else None
            
            if last_step and last_step['step_type'] in ['外部部分平仓', '外部全部平仓', 'API全部平仓']:
                if last_record['operation_type'] == 'close':
                    print(f"✓ 最后一条平仓记录operation_type正确: close")
                elif last_record['operation_type'] == 'reduce':
                    # 如果是外部全部平仓，应该是close
                    if last_step['step_type'] == '外部全部平仓':
                        result['passed'] = False
                        error_msg = "最后一条外部全部平仓记录operation_type应该是close，实际是reduce"
                        result['errors'].append(error_msg)
                        print(f"✗ {error_msg}")
                    else:
                        print(f"✓ 最后一条部分平仓记录operation_type: reduce")
        
        # 6. 检查时间戳递增
        if len(actual_records) > 1:
            prev_time = actual_records[0]['created_at']
            time_ok = True
            for i in range(1, len(actual_records)):
                curr_time = actual_records[i]['created_at']
                if curr_time < prev_time:
                    time_ok = False
                    break
                prev_time = curr_time
            
            if time_ok:
                print(f"✓ 时间戳递增正确")
            else:
                result['warnings'].append("时间戳未严格递增")
                print(f"⚠ 时间戳未严格递增")
        
        # 7. 计算数量统计
        open_amount = sum(r['amount'] or 0 for r in actual_records if r['operation_type'] == 'open')
        add_amount = sum(r['amount'] or 0 for r in actual_records if r['operation_type'] == 'add')
        reduce_amount = sum(r['amount'] or 0 for r in actual_records if r['operation_type'] == 'reduce')
        close_amount = sum(r['amount'] or 0 for r in actual_records if r['operation_type'] == 'close')
        
        total_open = open_amount + add_amount
        total_close = reduce_amount + close_amount
        
        print(f"\n数量统计:")
        print(f"  开仓: {open_amount}")
        print(f"  加仓: {add_amount}")
        print(f"  减仓: {reduce_amount}")
        print(f"  平仓: {close_amount}")
        print(f"  总开仓: {total_open}")
        print(f"  总平仓: {total_close}")
        
        if total_open > 0:
            tolerance = abs(total_open * 0.01)
            if not self.float_compare(total_close, total_open, tolerance):
                result['warnings'].append(f"数量不一致: 总开仓{total_open}, 总平仓{total_close}")
                print(f"⚠ 数量不一致: 总开仓{total_open}, 总平仓{total_close}")
            else:
                print(f"✓ 数量一致: 总开仓{total_open} = 总平仓{total_close}")
        
        if result['passed']:
            print(f"\n✓ 场景{scenario_num} trading_relations 验证通过")
        else:
            print(f"\n✗ 场景{scenario_num} trading_relations 验证失败")
        
        return result
    
    def _print_step1_summary(self):
        """打印第一步验证汇总"""
        print(f"\n{'='*60}")
        print("第一步验证汇总")
        print(f"{'='*60}")
        
        passed_count = sum(1 for r in self.step1_results.values() if r['passed'])
        total_count = len(self.step1_results)
        error_count = sum(len(r['errors']) for r in self.step1_results.values())
        warning_count = sum(len(r['warnings']) for r in self.step1_results.values())
        
        print(f"通过: {passed_count}/{total_count}")
        print(f"失败: {total_count - passed_count}/{total_count}")
        print(f"错误总数: {error_count}")
        print(f"警告总数: {warning_count}")
        
        print(f"\n详细结果:")
        for signal_id in sorted(self.step1_results.keys()):
            result = self.step1_results[signal_id]
            status = "✓" if result['passed'] else "✗"
            print(f"{status} 场景{result['scenario_num']}: {result['scenario_name']} (signal_id={signal_id})")
            if result['errors']:
                for error in result['errors']:
                    print(f"   错误: {error}")
            if result['warnings']:
                for warning in result['warnings']:
                    print(f"   警告: {warning}")
    
    def step2_verify_order_history(self):
        """第二步：order_history 表验证"""
        print(f"\n{'='*60}")
        print("第二步：order_history 表验证")
        print(f"{'='*60}")
        
        for signal_id in sorted(self.test_scenarios.keys()):
            scenario = self.test_scenarios[signal_id]
            result = self._verify_order_history_scenario(signal_id, scenario)
            self.step2_results[signal_id] = result
        
        # 汇总结果
        self._print_step2_summary()
    
    def _verify_order_history_scenario(self, signal_id: int, scenario: Dict) -> Dict[str, Any]:
        """验证单个场景的 order_history 数据"""
        scenario_name = scenario['name']
        scenario_num = scenario['scenario_num']
        symbol = scenario['symbol']
        side = scenario['side']
        
        print(f"\n{'='*60}")
        print(f"验证场景{scenario_num}: {scenario_name} (signal_id={signal_id})")
        print(f"交易对: {symbol}, 方向: {side}")
        print(f"{'='*60}")
        
        # 获取 trading_relations 记录
        tr_records = self.get_trading_relations_by_signal_id(signal_id)
        
        result = {
            'signal_id': signal_id,
            'scenario_num': scenario_num,
            'scenario_name': scenario_name,
            'symbol': symbol,
            'side': side,
            'passed': True,
            'errors': [],
            'warnings': [],
            'total_orders': 0,
            'filled_orders': 0,
            'missing_orders': []
        }
        
        if len(tr_records) == 0:
            result['passed'] = False
            result['errors'].append("trading_relations 中没有记录，无法验证 order_history")
            print(f"✗ trading_relations 中没有记录")
            return result
        
        # 获取 cl_ord_id
        cl_ord_ids = set(r['cl_ord_id'] for r in tr_records if r['cl_ord_id'])
        if len(cl_ord_ids) == 0:
            result['warnings'].append("所有记录的cl_ord_id为空，无法验证order_history")
            print(f"⚠ 所有记录的cl_ord_id为空")
            return result
        
        cl_ord_id = list(cl_ord_ids)[0]
        print(f"cl_ord_id: {cl_ord_id}")
        
        # 获取所有订单记录
        all_orders = self.get_order_history_by_cl_ord_id(cl_ord_id)
        result['total_orders'] = len(all_orders)
        
        print(f"找到 {len(all_orders)} 条订单记录")
        
        # 1. 检查API操作的订单是否存在
        api_tr_records = [r for r in tr_records if r['operation_type'] in ['open', 'add', 'reduce', 'close'] and r['ord_id']]
        
        missing_ord_ids = []
        for tr_record in api_tr_records:
            ord_id = tr_record['ord_id']
            order = self.get_order_history_by_ord_id(ord_id)
            
            if not order:
                missing_ord_ids.append(ord_id)
                result['passed'] = False
                error_msg = f"trading_relations中的ord_id={ord_id}在order_history中不存在"
                result['errors'].append(error_msg)
                result['missing_orders'].append(ord_id)
                print(f"✗ {error_msg}")
            else:
                print(f"✓ 找到订单: ord_id={ord_id}")
        
        if len(missing_ord_ids) == 0 and len(api_tr_records) > 0:
            print(f"✓ 所有API操作的订单都已记录")
        
        # 2. 检查订单状态
        for order in all_orders:
            ord_id = order['ord_id']
            state = order['state']
            
            if state != 'filled':
                result['warnings'].append(f"订单{ord_id}状态不是filled: {state}")
                print(f"⚠ 订单{ord_id}状态: {state} (期望filled)")
            else:
                result['filled_orders'] += 1
        
        if result['filled_orders'] == len(all_orders) and len(all_orders) > 0:
            print(f"✓ 所有订单状态都是filled: {result['filled_orders']}/{len(all_orders)}")
        
        # 3. 检查数量转换正确性（合约数量 -> 币数量）
        contract_size = self.get_contract_size(symbol)
        print(f"\n合约乘数: {contract_size} ({symbol})")
        
        for tr_record in tr_records:
            if not tr_record['ord_id']:
                continue
            
            order = self.get_order_history_by_ord_id(tr_record['ord_id'])
            if not order:
                continue
            
            # 订单的合约数量
            order_sz = order['sz']  # 合约数量
            # 转换为币数量
            order_amount_coins = order_sz * contract_size if contract_size > 0 else order_sz
            
            # trading_relations 中的币数量
            tr_amount = tr_record['amount']
            
            if tr_amount is not None:
                tolerance = abs(tr_amount * 0.01) if tr_amount > 0 else 0.01
                if not self.float_compare(order_amount_coins, tr_amount, tolerance):
                    result['warnings'].append(
                        f"数量转换不一致: ord_id={tr_record['ord_id']}, "
                        f"order_history.sz={order_sz}(合约)={order_amount_coins}(币), "
                        f"trading_relations.amount={tr_amount}"
                    )
                    print(f"⚠ 数量转换不一致: ord_id={tr_record['ord_id']}")
                    print(f"   order_history: {order_sz}(合约) = {order_amount_coins}(币)")
                    print(f"   trading_relations: {tr_amount}(币)")
                else:
                    print(f"✓ 数量转换正确: ord_id={tr_record['ord_id']}, {order_sz}(合约) = {order_amount_coins}(币) = {tr_amount}(币)")
        
        # 4. 检查订单的 cl_ord_id 关联
        for order in all_orders:
            if order['cl_ord_id'] != cl_ord_id:
                result['warnings'].append(
                    f"订单{order['ord_id']}的cl_ord_id={order['cl_ord_id']}与期望的{cl_ord_id}不一致"
                )
                print(f"⚠ 订单{order['ord_id']}的cl_ord_id不一致")
            else:
                print(f"✓ 订单{order['ord_id']}的cl_ord_id正确")
        
        # 5. 检查订单的 symbol 和 side
        expected_pos_side = 'long' if side == 'LONG' else 'short'
        for order in all_orders:
            if order['symbol'].upper() != symbol.upper():
                result['warnings'].append(
                    f"订单{order['ord_id']}的symbol={order['symbol']}与期望的{symbol}不一致"
                )
                print(f"⚠ 订单{order['ord_id']}的symbol不一致: {order['symbol']} vs {symbol}")
            
            if order.get('pos_side'):
                if order['pos_side'] != expected_pos_side:
                    result['warnings'].append(
                        f"订单{order['ord_id']}的pos_side={order['pos_side']}与期望的{expected_pos_side}不一致"
                    )
                    print(f"⚠ 订单{order['ord_id']}的pos_side不一致: {order['pos_side']} vs {expected_pos_side}")
        
        # 6. 检查外部平仓的订单（如果已同步）
        external_tr_records = [
            r for r in tr_records 
            if r['operation_type'] in ['reduce', 'close'] and r['ord_id']
        ]
        
        external_orders_found = 0
        for tr_record in external_tr_records:
            ord_id = tr_record['ord_id']
            order = self.get_order_history_by_ord_id(ord_id)
            if order:
                external_orders_found += 1
                print(f"✓ 外部平仓订单已同步: ord_id={ord_id}")
        
        if len(external_tr_records) > 0:
            print(f"外部平仓订单同步情况: {external_orders_found}/{len(external_tr_records)}")
            if external_orders_found < len(external_tr_records):
                result['warnings'].append(
                    f"部分外部平仓订单未同步: {external_orders_found}/{len(external_tr_records)}"
                )
        
        if result['passed']:
            print(f"\n✓ 场景{scenario_num} order_history 验证通过")
        else:
            print(f"\n✗ 场景{scenario_num} order_history 验证失败")
        
        return result
    
    def _print_step2_summary(self):
        """打印第二步验证汇总"""
        print(f"\n{'='*60}")
        print("第二步验证汇总")
        print(f"{'='*60}")
        
        passed_count = sum(1 for r in self.step2_results.values() if r['passed'])
        total_count = len(self.step2_results)
        error_count = sum(len(r['errors']) for r in self.step2_results.values())
        warning_count = sum(len(r['warnings']) for r in self.step2_results.values())
        
        total_orders = sum(r['total_orders'] for r in self.step2_results.values())
        filled_orders = sum(r['filled_orders'] for r in self.step2_results.values())
        
        print(f"通过: {passed_count}/{total_count}")
        print(f"失败: {total_count - passed_count}/{total_count}")
        print(f"错误总数: {error_count}")
        print(f"警告总数: {warning_count}")
        print(f"订单总数: {total_orders}")
        print(f"已成交订单: {filled_orders}")
        
        print(f"\n详细结果:")
        for signal_id in sorted(self.step2_results.keys()):
            result = self.step2_results[signal_id]
            status = "✓" if result['passed'] else "✗"
            print(f"{status} 场景{result['scenario_num']}: {result['scenario_name']} (signal_id={signal_id})")
            print(f"   订单数: {result['total_orders']}, 已成交: {result['filled_orders']}")
            if result['errors']:
                for error in result['errors']:
                    print(f"   错误: {error}")
            if result['warnings']:
                for warning in result['warnings']:
                    print(f"   警告: {warning}")
    
    def step3_verify_consistency(self):
        """第三步：数据一致性验证"""
        print(f"\n{'='*60}")
        print("第三步：数据一致性验证")
        print(f"{'='*60}")
        
        for signal_id in sorted(self.test_scenarios.keys()):
            scenario = self.test_scenarios[signal_id]
            result = self._verify_consistency_scenario(signal_id, scenario)
            self.step3_results[signal_id] = result
        
        # 汇总结果
        self._print_step3_summary()
    
    def _verify_consistency_scenario(self, signal_id: int, scenario: Dict) -> Dict[str, Any]:
        """验证单个场景的数据一致性"""
        scenario_name = scenario['name']
        scenario_num = scenario['scenario_num']
        symbol = scenario['symbol']
        side = scenario['side']
        steps = scenario['steps']
        
        print(f"\n{'='*60}")
        print(f"验证场景{scenario_num}: {scenario_name} (signal_id={signal_id})")
        print(f"交易对: {symbol}, 方向: {side}")
        print(f"{'='*60}")
        
        result = {
            'signal_id': signal_id,
            'scenario_num': scenario_num,
            'scenario_name': scenario_name,
            'symbol': symbol,
            'side': side,
            'passed': True,
            'errors': [],
            'warnings': []
        }
        
        # 获取 trading_relations 记录
        tr_records = self.get_trading_relations_by_signal_id(signal_id)
        
        if len(tr_records) == 0:
            result['passed'] = False
            result['errors'].append("trading_relations 中没有记录，无法验证数据一致性")
            print(f"✗ trading_relations 中没有记录")
            return result
        
        # 1. 数量平衡验证
        print(f"\n1. 数量平衡验证")
        open_amount = sum(r['amount'] or 0 for r in tr_records if r['operation_type'] == 'open')
        add_amount = sum(r['amount'] or 0 for r in tr_records if r['operation_type'] == 'add')
        reduce_amount = sum(r['amount'] or 0 for r in tr_records if r['operation_type'] == 'reduce')
        close_amount = sum(r['amount'] or 0 for r in tr_records if r['operation_type'] == 'close')
        
        total_open = open_amount + add_amount
        total_close = reduce_amount + close_amount
        final_position = total_open - total_close
        
        print(f"  开仓: {open_amount}")
        print(f"  加仓: {add_amount}")
        print(f"  减仓: {reduce_amount}")
        print(f"  平仓: {close_amount}")
        print(f"  总开仓: {total_open}")
        print(f"  总平仓: {total_close}")
        print(f"  最终持仓: {final_position}")
        
        # 最终持仓应该为0（允许1%误差）
        if total_open > 0:
            tolerance = abs(total_open * 0.01)
            if not self.float_compare(final_position, 0.0, tolerance):
                result['passed'] = False
                error_msg = f"数量不平衡: 最终持仓={final_position}, 期望=0 (总开仓={total_open}, 总平仓={total_close})"
                result['errors'].append(error_msg)
                print(f"✗ {error_msg}")
            else:
                print(f"✓ 数量平衡: 最终持仓={final_position} ≈ 0")
        else:
            result['warnings'].append("总开仓为0，无法验证数量平衡")
            print(f"⚠ 总开仓为0")
        
        # 2. 验证开仓总数量 = 所有open操作的amount之和
        print(f"\n2. 开仓总数量验证")
        open_operations = [r for r in tr_records if r['operation_type'] == 'open']
        open_sum = sum(r['amount'] or 0 for r in open_operations)
        
        if len(open_operations) > 0:
            if self.float_compare(open_sum, open_amount):
                print(f"✓ 开仓总数量正确: {open_sum}")
            else:
                result['warnings'].append(f"开仓总数量不一致: 计算值={open_sum}, 汇总值={open_amount}")
                print(f"⚠ 开仓总数量不一致")
        
        # 3. 验证加仓总数量 = 所有add操作的amount之和
        print(f"\n3. 加仓总数量验证")
        add_operations = [r for r in tr_records if r['operation_type'] == 'add']
        add_sum = sum(r['amount'] or 0 for r in add_operations)
        
        if len(add_operations) > 0:
            if self.float_compare(add_sum, add_amount):
                print(f"✓ 加仓总数量正确: {add_sum}")
            else:
                result['warnings'].append(f"加仓总数量不一致: 计算值={add_sum}, 汇总值={add_amount}")
                print(f"⚠ 加仓总数量不一致")
        
        # 4. 验证平仓总数量 = 所有reduce+close操作的amount之和
        print(f"\n4. 平仓总数量验证")
        close_operations = [r for r in tr_records if r['operation_type'] in ['reduce', 'close']]
        close_sum = sum(r['amount'] or 0 for r in close_operations)
        
        if len(close_operations) > 0:
            if self.float_compare(close_sum, total_close):
                print(f"✓ 平仓总数量正确: {close_sum}")
            else:
                result['warnings'].append(f"平仓总数量不一致: 计算值={close_sum}, 汇总值={total_close}")
                print(f"⚠ 平仓总数量不一致")
        
        # 5. 验证最后一条外部平仓必须为close
        print(f"\n5. 最后一条外部平仓验证")
        external_steps = [s for s in steps if s['step_type'] in ['外部部分平仓', '外部全部平仓']]
        
        if len(external_steps) > 0:
            last_external_step = external_steps[-1]
            last_tr_record = tr_records[-1]
            
            if last_external_step['step_type'] == '外部全部平仓':
                if last_tr_record['operation_type'] == 'close':
                    print(f"✓ 最后一条外部全部平仓正确识别为close")
                else:
                    result['passed'] = False
                    error_msg = f"最后一条外部全部平仓应该为close，实际为{last_tr_record['operation_type']}"
                    result['errors'].append(error_msg)
                    print(f"✗ {error_msg}")
            else:
                print(f"✓ 最后一条是外部部分平仓，operation_type={last_tr_record['operation_type']}")
        
        # 6. 验证外部平仓的ord_id（如果订单已同步）
        print(f"\n6. 外部平仓订单同步验证")
        external_tr_records = [
            r for r in tr_records 
            if r['operation_type'] in ['reduce', 'close'] and r['ord_id']
        ]
        
        if len(external_tr_records) > 0:
            external_orders_synced = 0
            for tr_record in external_tr_records:
                order = self.get_order_history_by_ord_id(tr_record['ord_id'])
                if order:
                    external_orders_synced += 1
            
            print(f"  外部平仓记录数: {len(external_tr_records)}")
            print(f"  已同步订单数: {external_orders_synced}")
            
            if external_orders_synced == len(external_tr_records):
                print(f"✓ 所有外部平仓订单都已同步")
            else:
                result['warnings'].append(
                    f"部分外部平仓订单未同步: {external_orders_synced}/{len(external_tr_records)}"
                )
                print(f"⚠ 部分外部平仓订单未同步")
        else:
            print(f"  无外部平仓记录或ord_id为空")
        
        # 7. 验证trading_relations与order_history的数量一致性
        print(f"\n7. trading_relations与order_history数量一致性验证")
        cl_ord_ids = set(r['cl_ord_id'] for r in tr_records if r['cl_ord_id'])
        
        if len(cl_ord_ids) > 0:
            cl_ord_id = list(cl_ord_ids)[0]
            orders = self.get_order_history_by_cl_ord_id(cl_ord_id)
            contract_size = self.get_contract_size(symbol)
            
            # 计算order_history中的总数量（币数量）
            order_total_coins = 0
            for order in orders:
                order_sz = order['sz']  # 合约数量
                order_amount_coins = order_sz * contract_size if contract_size > 0 else order_sz
                order_total_coins += order_amount_coins
            
            # 计算trading_relations中的总数量
            tr_total = sum(r['amount'] or 0 for r in tr_records if r['amount'] is not None)
            
            if len(orders) > 0:
                tolerance = abs(tr_total * 0.01) if tr_total > 0 else 0.01
                if self.float_compare(order_total_coins, tr_total, tolerance):
                    print(f"✓ 数量一致性正确: order_history={order_total_coins}(币), trading_relations={tr_total}(币)")
                else:
                    result['warnings'].append(
                        f"数量不一致: order_history={order_total_coins}(币), trading_relations={tr_total}(币)"
                    )
                    print(f"⚠ 数量不一致: order_history={order_total_coins}(币), trading_relations={tr_total}(币)")
            else:
                result['warnings'].append("order_history中没有订单记录")
                print(f"⚠ order_history中没有订单记录")
        
        # 8. 验证position_history关联（可选）
        print(f"\n8. position_history关联验证")
        tr_with_pos_history = [r for r in tr_records if r['position_history_id']]
        
        if len(tr_with_pos_history) > 0:
            print(f"  有position_history_id的记录数: {len(tr_with_pos_history)}")
            print(f"  ✓ 部分记录已关联position_history")
        else:
            print(f"  无position_history关联（这是正常的，平仓后才会关联）")
        
        if result['passed']:
            print(f"\n✓ 场景{scenario_num} 数据一致性验证通过")
        else:
            print(f"\n✗ 场景{scenario_num} 数据一致性验证失败")
        
        return result
    
    def _print_step3_summary(self):
        """打印第三步验证汇总"""
        print(f"\n{'='*60}")
        print("第三步验证汇总")
        print(f"{'='*60}")
        
        passed_count = sum(1 for r in self.step3_results.values() if r['passed'])
        total_count = len(self.step3_results)
        error_count = sum(len(r['errors']) for r in self.step3_results.values())
        warning_count = sum(len(r['warnings']) for r in self.step3_results.values())
        
        print(f"通过: {passed_count}/{total_count}")
        print(f"失败: {total_count - passed_count}/{total_count}")
        print(f"错误总数: {error_count}")
        print(f"警告总数: {warning_count}")
        
        print(f"\n详细结果:")
        for signal_id in sorted(self.step3_results.keys()):
            result = self.step3_results[signal_id]
            status = "✓" if result['passed'] else "✗"
            print(f"{status} 场景{result['scenario_num']}: {result['scenario_name']} (signal_id={signal_id})")
            if result['errors']:
                for error in result['errors']:
                    print(f"   错误: {error}")
            if result['warnings']:
                for warning in result['warnings']:
                    print(f"   警告: {warning}")

    def run(self):
        """运行验证"""
        if not self.connect():
            return False
        
        try:
            # 第一步：trading_relations 表验证
            self.step1_verify_trading_relations()
            
            # 第二步：order_history 表验证
            self.step2_verify_order_history()
            
            # 第三步：数据一致性验证
            self.step3_verify_consistency()
            
            # 最终汇总
            self._print_final_summary()
            
            # 判断是否全部通过
            step1_passed = sum(1 for r in self.step1_results.values() if r['passed'])
            step1_total = len(self.step1_results)
            step1_errors = sum(len(r['errors']) for r in self.step1_results.values())
            
            step2_passed = sum(1 for r in self.step2_results.values() if r['passed'])
            step2_total = len(self.step2_results)
            step2_errors = sum(len(r['errors']) for r in self.step2_results.values())
            
            step3_passed = sum(1 for r in self.step3_results.values() if r['passed'])
            step3_total = len(self.step3_results)
            step3_errors = sum(len(r['errors']) for r in self.step3_results.values())
            
            return (step1_passed == step1_total and step1_errors == 0 and 
                    step2_passed == step2_total and step2_errors == 0 and
                    step3_passed == step3_total and step3_errors == 0)
        
        finally:
            self.close()
    
    def _print_final_summary(self):
        """打印最终汇总"""
        print(f"\n{'='*60}")
        print("最终验证汇总")
        print(f"{'='*60}")
        
        step1_passed = sum(1 for r in self.step1_results.values() if r['passed'])
        step1_total = len(self.step1_results)
        step1_errors = sum(len(r['errors']) for r in self.step1_results.values())
        step1_warnings = sum(len(r['warnings']) for r in self.step1_results.values())
        
        step2_passed = sum(1 for r in self.step2_results.values() if r['passed'])
        step2_total = len(self.step2_results)
        step2_errors = sum(len(r['errors']) for r in self.step2_results.values())
        step2_warnings = sum(len(r['warnings']) for r in self.step2_results.values())
        
        step3_passed = sum(1 for r in self.step3_results.values() if r['passed'])
        step3_total = len(self.step3_results)
        step3_errors = sum(len(r['errors']) for r in self.step3_results.values())
        step3_warnings = sum(len(r['warnings']) for r in self.step3_results.values())
        
        print(f"第一步（trading_relations验证）: {step1_passed}/{step1_total} 通过, {step1_errors} 个错误, {step1_warnings} 个警告")
        print(f"第二步（order_history验证）: {step2_passed}/{step2_total} 通过, {step2_errors} 个错误, {step2_warnings} 个警告")
        print(f"第三步（数据一致性验证）: {step3_passed}/{step3_total} 通过, {step3_errors} 个错误, {step3_warnings} 个警告")
        
        all_passed = (step1_passed == step1_total and step1_errors == 0 and 
                      step2_passed == step2_total and step2_errors == 0 and
                      step3_passed == step3_total and step3_errors == 0)
        
        if all_passed:
            print("\n✓ 所有验证全部通过！")
        else:
            print("\n✗ 验证未完全通过")


if __name__ == "__main__":
    print("="*60)
    print("外部平仓测试数据验证脚本")
    print("="*60)
    print("验证范围: signal_id 60-73 (14个测试场景)")
    print("="*60)
    
    try:
        verifier = ExternalCloseTestVerifier()
        print(f"✓ 加载测试场景配置: {len(verifier.test_scenarios)} 个场景")
        for signal_id, scenario in sorted(verifier.test_scenarios.items()):
            print(f"  场景{scenario['scenario_num']}: {scenario['name']} (signal_id={signal_id})")
        
        success = verifier.run()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ 验证失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

