"""命令行入口。M1 仅提供 init 命令；生成命令 M2 实现。"""
from __future__ import annotations

import argparse
import sys

from novel_agent.bible.database import SessionLocal, set_config
from novel_agent.bible.models import Base, Project
from novel_agent.bible.repository import BibleRepository
from novel_agent.config import load_config


def cmd_init(args):
    """初始化新小说项目。"""
    from novel_agent.bible import database as db_mod
    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    p = Project(title=args.title, genre=args.genre or "",
                summary=args.summary or "", style=args.style or "")
    db.add(p); db.commit(); db.refresh(p)
    print(f"已创建项目：{p.title} (id={p.id})")
    print(f"数据目录：{cfg.project_data_dir}")
    db.close()


def main():
    parser = argparse.ArgumentParser(prog="novel-agent", description="多 Agent 小说生成")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化新小说项目")
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--genre", default="")
    p_init.add_argument("--summary", default="")
    p_init.add_argument("--style", default="")
    p_init.add_argument("--config", default=None)
    p_init.set_defaults(func=cmd_init)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
