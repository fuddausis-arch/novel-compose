"""项目 CRUD 功能测试。"""
from __future__ import annotations


def test_create_project(client):
    """创建项目：验证返回字段与状态码。"""
    resp = client.post(
        "/api/projects",
        json={"title": "测试小说", "genre": "玄幻", "summary": "简介", "style": "轻松"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] > 0
    assert data["title"] == "测试小说"
    assert data["genre"] == "玄幻"


def test_list_and_get_project(client, sample_project):
    """查询项目列表与详情。"""
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json()
    assert any(p["id"] == sample_project for p in projects)

    resp = client.get(f"/api/projects/{sample_project}")
    assert resp.status_code == 200
    assert resp.json()["id"] == sample_project


def test_update_and_delete_project(client, sample_project):
    """更新与删除项目。"""
    resp = client.put(f"/api/projects/{sample_project}", json={"title": "更新后标题"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "更新后标题"

    resp = client.delete(f"/api/projects/{sample_project}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    resp = client.get(f"/api/projects/{sample_project}")
    assert resp.status_code == 404


def test_create_project_missing_title(client):
    """缺少必填字段应返回 422。"""
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422
