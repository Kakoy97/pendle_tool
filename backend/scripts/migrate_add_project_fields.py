"""数据库迁移脚本：添加 project_group 和 expiry 字段"""

import asyncio
import sqlite3
from pathlib import Path


def migrate_database():
    """添加新字段到 pendle_projects 表"""
    # 数据库文件在 backend 目录下
    script_dir = Path(__file__).parent
    backend_dir = script_dir.parent
    db_path = backend_dir / "pendle_tool.db"
    
    print(f"查找数据库文件: {db_path}")
    print(f"文件是否存在: {db_path.exists()}")
    
    if not db_path.exists():
        print("数据库文件不存在，将在首次运行时自动创建")
        print(f"请确保在 backend 目录下运行此脚本")
        return
    
    print("=" * 60)
    print("数据库迁移：添加 project_group 和 expiry 字段")
    print("=" * 60)
    
    # 使用同步 SQLite 连接进行迁移（因为 ALTER TABLE 是同步操作）
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # 检查字段是否已存在
        cursor.execute("PRAGMA table_info(pendle_projects)")
        columns = [row[1] for row in cursor.fetchall()]
        
        print(f"当前表的字段: {columns}")
        
        # 添加 project_group 字段（如果不存在）
        if "project_group" not in columns:
            print("\n添加 project_group 字段...")
            cursor.execute("ALTER TABLE pendle_projects ADD COLUMN project_group VARCHAR(255)")
            print("✓ project_group 字段已添加")
        else:
            print("✓ project_group 字段已存在")
        
        # 添加 expiry 字段（如果不存在）
        if "expiry" not in columns:
            print("\n添加 expiry 字段...")
            cursor.execute("ALTER TABLE pendle_projects ADD COLUMN expiry DATETIME")
            print("✓ expiry 字段已添加")
        else:
            print("✓ expiry 字段已存在")
        
        # 创建索引（如果不存在）
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_pendle_projects_project_group ON pendle_projects(project_group)")
            print("✓ project_group 索引已创建")
        except Exception as e:
            print(f"创建 project_group 索引时出错（可能已存在）: {e}")
        
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS ix_pendle_projects_expiry ON pendle_projects(expiry)")
            print("✓ expiry 索引已创建")
        except Exception as e:
            print(f"创建 expiry 索引时出错（可能已存在）: {e}")
        
        conn.commit()
        print("\n" + "=" * 60)
        print("迁移完成！")
        print("=" * 60)
        
    except Exception as e:
        conn.rollback()
        print(f"\n迁移失败: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_database()

