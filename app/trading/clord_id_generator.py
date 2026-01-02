"""
clOrdId生成器
生成符合OKX要求的客户端订单ID：字母（大小写）+ 数字，1-32位
方案1：YYMMDDHHmm + 随机字符串（大小写字母+数字），总长度32位
"""
import random
import string
from datetime import datetime, timezone
from typing import Optional


class ClOrdIdGenerator:
    """clOrdId生成器"""
    
    # 字符集：大小写字母 + 数字
    CHARSET = string.ascii_letters + string.digits  # a-z, A-Z, 0-9
    
    @staticmethod
    def generate() -> str:
        """
        生成clOrdId
        
        格式：YYMMDDHHmm + 随机字符串（大小写字母+数字）
        总长度：32位（10位时间戳 + 22位随机字符串）
        
        Returns:
            clOrdId字符串
        """
        # 获取当前时间（UTC）
        now = datetime.now(timezone.utc)
        
        # 生成时间戳部分：YYMMDDHHmm（10位）
        time_part = now.strftime('%y%m%d%H%M')
        
        # 生成随机字符串部分：22位（大小写字母+数字）
        random_part = ''.join(random.choices(ClOrdIdGenerator.CHARSET, k=22))
        
        # 组合：总长度32位
        cl_ord_id = time_part + random_part
        
        return cl_ord_id
    
    @staticmethod
    def validate(cl_ord_id: str) -> bool:
        """
        验证clOrdId格式是否符合要求
        
        Args:
            cl_ord_id: 要验证的clOrdId
            
        Returns:
            是否符合要求（字母大小写+数字，1-32位）
        """
        if not cl_ord_id:
            return False
        
        if len(cl_ord_id) < 1 or len(cl_ord_id) > 32:
            return False
        
        # 检查是否只包含字母（大小写）和数字
        for char in cl_ord_id:
            if char not in ClOrdIdGenerator.CHARSET:
                return False
        
        return True

