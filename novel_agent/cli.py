"""命令行入口。init 建项目，generate 生成单章（M2 单 Writer 流水线）。"""
from __future__ import annotations

import argparse
import asyncio

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


async def cmd_generate(args):
    """生成单章（M2：单 Writer 流水线）。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.llm.client import LLMClient
    from novel_agent.orchestrator.runner import ChapterRunner

    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        print("错误：没有项目，请先 novel-agent init")
        db.close()
        return
    repo = BibleRepository(db, project_id=project.id)
    runner = ChapterRunner(cfg, repo=repo)
    try:
        result = await runner.run(chapter=args.chapter, title=args.title)
        print(f"章节 {args.chapter}《{args.title}》：{result.get('status')}")
        if result.get("error"):
            print(f"错误：{result['error']}")
        else:
            print(f"字数：{result.get('word_count', 0)}")
            print(f"正文：{cfg.chapters_dir}")
    finally:
        runner.close()
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

    p_gen = sub.add_parser("generate", help="生成单章（M2 单 Writer 流水线）")
    p_gen.add_argument("--chapter", type=int, required=True)
    p_gen.add_argument("--title", required=True)
    p_gen.add_argument("--config", default=None)
    p_gen.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()
