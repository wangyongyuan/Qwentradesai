"""
数据库连接管理
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


class Database:
    """数据库管理"""
    
    def __init__(self, database_url: str = None):
        if database_url is None:
            # 延迟导入settings，避免循环依赖
            from app.config import settings
            database_url = settings.DATABASE_URL
        self.engine = create_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # 连接前检查
            pool_recycle=3600,  # 1小时回收连接
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
    
    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()
    
    def close(self):
        """关闭连接"""
        self.engine.dispose()


# 全局数据库实例（延迟初始化，避免循环依赖）
_db_instance = None

def _get_db():
    """获取全局数据库实例（延迟初始化）"""
    global _db_instance
    if _db_instance is None:
        from app.config import settings
        _db_instance = Database(database_url=settings.DATABASE_URL)
    return _db_instance

# 为了向后兼容，提供一个db变量
# 使用延迟初始化，避免循环依赖
class _DatabaseProxy:
    """数据库实例代理，延迟初始化"""
    def __getattr__(self, name):
        return getattr(_get_db(), name)

db = _DatabaseProxy()


def get_db() -> Session:
    """获取数据库会话（用于依赖注入）"""
    session = _get_db().get_session()
    try:
        yield session
    finally:
        session.close()

