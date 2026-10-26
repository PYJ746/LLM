from __future__ import annotations

from pathlib import Path

from core.confirmation import AutoApproveConfirmation
from core.tools.defaults import build_default_registry
from tests.conftest import ScriptedConfirmation


def run(registry, name, **arguments):
    return registry.execute("call_1", name, arguments)


def make_registry(workspace, confirmation=None):
    return build_default_registry(workspace=workspace, confirmation=confirmation)


async def test_getcwd_uses_workspace(workspace):
    registry = make_registry(workspace)
    result = await run(registry, "getcwd")
    assert result.ok
    assert str(workspace) in result.content


async def test_list_directory_sorts_dirs_first(workspace):
    (workspace / "b_dir").mkdir()
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "C.md").write_text("c", encoding="utf-8")

    result = await run(make_registry(workspace), "listDirectory", path=".")

    lines = result.content.splitlines()
    assert "共 3 项" in lines[1]
    assert lines[2].startswith("[目录] b_dir")
    assert lines[3].startswith("[文件] a.txt")
    assert lines[4].startswith("[文件] C.md")


async def test_read_utf8_and_gbk(workspace):
    (workspace / "utf8.txt").write_text("中文内容", encoding="utf-8")
    (workspace / "gbk.txt").write_bytes("国标编码".encode("gbk"))

    registry = make_registry(workspace)
    utf8 = await run(registry, "readTextFile", path="utf8.txt")
    gbk = await run(registry, "readTextFile", path="gbk.txt")

    assert "中文内容" in utf8.content
    assert "国标编码" in gbk.content


async def test_read_rejects_binary(workspace):
    (workspace / "data.txt").write_bytes(b"abc\x00def")
    result = await run(make_registry(workspace), "readTextFile", path="data.txt")
    assert not result.ok
    assert "二进制内容" in result.content


async def test_read_truncates_large_file(workspace):
    (workspace / "big.txt").write_bytes(b"a" * 200_100)
    result = await run(make_registry(workspace), "readTextFile", path="big.txt")
    assert result.ok
    assert "仅显示前 200000 字节" in result.content


async def test_read_rejects_non_text_suffix(workspace):
    (workspace / "image.png").write_bytes(b"\x89PNG\r\n")
    result = await run(make_registry(workspace), "readTextFile", path="image.png")
    assert not result.ok
    assert "仅支持纯文本文件" in result.content


async def test_create_directory_nested_and_existing(workspace):
    registry = make_registry(workspace)
    created = await run(registry, "createDirectory", path="a/b/c")
    assert created.content.startswith("已创建目录")
    assert (workspace / "a/b/c").is_dir()

    existing = await run(registry, "createDirectory", path="a/b/c")
    assert existing.content.startswith("目录已存在")


async def test_get_file_type(workspace):
    (workspace / "note.md").write_text("x", encoding="utf-8")
    registry = make_registry(workspace)

    file_result = await run(registry, "getFileType", path="note.md")
    dir_result = await run(registry, "getFileType", path=".")

    assert "扩展名: .md" in file_result.content
    assert "类型: 目录" in dir_result.content


async def test_rename_refuses_overwrite(workspace):
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "b.txt").write_text("b", encoding="utf-8")
    result = await run(
        make_registry(workspace), "renamePath", source="a.txt", destination="b.txt"
    )
    assert not result.ok
    assert "拒绝覆盖" in result.content


async def test_rename_moves_file(workspace):
    (workspace / "a.txt").write_text("a", encoding="utf-8")
    (workspace / "sub").mkdir()
    result = await run(
        make_registry(workspace), "renamePath", source="a.txt", destination="sub/a.txt"
    )
    assert result.ok
    assert (workspace / "sub/a.txt").is_file()


async def test_delete_file_requires_confirmation(workspace):
    target = workspace / "keep.txt"
    target.write_text("x", encoding="utf-8")
    confirmation = ScriptedConfirmation([False])

    result = await run(
        make_registry(workspace, confirmation), "deleteFile", path="keep.txt"
    )

    assert result.ok
    assert result.cancelled
    assert result.content == "用户取消了删除操作"
    assert target.exists()
    assert confirmation.requests[0].tool_name == "deleteFile"


async def test_delete_file_approved(workspace):
    target = workspace / "gone.txt"
    target.write_text("x", encoding="utf-8")
    result = await run(
        make_registry(workspace, AutoApproveConfirmation()),
        "deleteFile",
        path="gone.txt",
    )
    assert result.ok
    assert not result.cancelled
    assert not target.exists()


async def test_delete_directory_approved(workspace):
    target = workspace / "folder"
    target.mkdir()
    (target / "inner.txt").write_text("x", encoding="utf-8")

    result = await run(
        make_registry(workspace, AutoApproveConfirmation()),
        "deleteDirectory",
        path="folder",
    )
    assert result.ok
    assert not target.exists()


async def test_delete_refuses_disk_root(workspace):
    root = Path(workspace).anchor
    result = await run(
        make_registry(workspace, AutoApproveConfirmation()),
        "deleteDirectory",
        path=root,
    )
    assert not result.ok
    assert "拒绝删除" in result.content


async def test_delete_refuses_workspace(workspace):
    result = await run(
        make_registry(workspace, AutoApproveConfirmation()),
        "deleteDirectory",
        path=".",
    )
    assert not result.ok
    assert "拒绝删除" in result.content


async def test_absolute_path_outside_workspace_allowed(workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "remote.txt").write_text("remote", encoding="utf-8")

    result = await run(
        make_registry(workspace), "readTextFile", path=str(outside / "remote.txt")
    )
    assert result.ok
    assert "remote" in result.content
