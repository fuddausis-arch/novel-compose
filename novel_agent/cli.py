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
        print("错误：没有项目，请先 novel-compose init")
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
        await runner.close()
        db.close()


async def cmd_plan(args):
    """卷级规划（M3b）：plan → 人审① → 写入圣经。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.planning.runner import VolumeRunner

    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        print("错误：没有项目，请先 novel-compose init")
        db.close()
        return
    repo = BibleRepository(db, project_id=project.id)
    runner = VolumeRunner(cfg, repo=repo)
    try:
        result = await runner.run(volume=args.volume, chapter_count=args.chapters,
                                  thread_id=args.thread_id)
        print(f"规划已生成，等待人审①。thread_id={args.thread_id}")
        print(f"卷规划：{result.get('volume_plan', {})}")
        print(f"用 novel-compose resume --thread-id {args.thread_id} --approve 恢复")
    finally:
        await runner.aclose()
        db.close()


async def cmd_resume(args):
    """人审①后恢复规划。"""
    from novel_agent.bible import database as db_mod
    from novel_agent.planning.runner import VolumeRunner

    cfg = load_config(args.config)
    set_config(cfg)
    Base.metadata.create_all(bind=db_mod.engine)
    db = SessionLocal()
    project = db.query(Project).order_by(Project.id.desc()).first()
    if not project:
        print("错误：没有项目")
        db.close()
        return
    repo = BibleRepository(db, project_id=project.id)
    runner = VolumeRunner(cfg, repo=repo)
    try:
        decision = {"approved": args.approve, "edits": args.edits or ""}
        result = await runner.resume(decision, thread_id=args.thread_id)
        print(f"恢复完成：{result.get('status')}")
    finally:
        await runner.aclose()
        db.close()


def cmd_serve(args):
    """启动 API 服务 + 前端控制台。"""
    import uvicorn
    uvicorn.run("novel_agent.api.app:create_app", factory=True,
                host="127.0.0.1", port=args.port, reload=False)


def main():
    parser = argparse.ArgumentParser(prog="novel-compose", description="多 Agent 小说生成")
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

    p_plan = sub.add_parser("plan", help="卷级规划（M3b）")
    p_plan.add_argument("--volume", required=True)
    p_plan.add_argument("--chapters", type=int, default=30)
    p_plan.add_argument("--thread-id", required=True)
    p_plan.add_argument("--config", default=None)
    p_plan.set_defaults(func=cmd_plan)

    p_resume = sub.add_parser("resume", help="人审①后恢复规划")
    p_resume.add_argument("--thread-id", required=True)
    p_resume.add_argument("--approve", action="store_true")
    p_resume.add_argument("--edits", default="")
    p_resume.add_argument("--config", default=None)
    p_resume.set_defaults(func=cmd_resume)

    p_serve = sub.add_parser("serve", help="启动 API 服务 + 前端控制台")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)


if __name__ == "__main__":
    main()
