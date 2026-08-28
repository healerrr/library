import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes import (
    create_email_template,
    delete_email_template,
    list_email_templates,
    update_email_template,
)
from app.database import Base
from app.models import Site
from app.schemas import EmailTemplateCreate, EmailTemplateUpdate
from app.services.email_html import sanitize_rich_text


def test_email_template_sanitizes_html_and_links() -> None:
    payload = EmailTemplateCreate(
        title="  合作邮件  ",
        content_html=(
            '<p onclick="steal()">您好 <strong>客户</strong></p>'
            '<a href="javascript:alert(1)">危险链接</a>'
            '<a href="https://example.com?a=1&amp;b=2">安全链接</a>'
            '<script>alert(1)</script>'
        ),
    )

    assert payload.title == "合作邮件"
    assert "onclick" not in payload.content_html
    assert "javascript:" not in payload.content_html
    assert "<script" not in payload.content_html
    assert 'href="https://example.com?a=1&amp;b=2"' in payload.content_html
    assert 'rel="noopener noreferrer"' in payload.content_html


def test_email_template_requires_visible_content() -> None:
    with pytest.raises(ValidationError, match="邮件模板正文不能为空"):
        EmailTemplateCreate(title="空模板", content_html="<br><div></div>")

    with pytest.raises(ValidationError, match="邮件模板标题不能为空"):
        EmailTemplateCreate(title="   ", content_html="<p>有正文</p>")


def test_sanitizer_keeps_supported_email_formatting() -> None:
    cleaned, plain_text = sanitize_rich_text(
        "<h2>标题</h2><ul><li><b>第一项</b></li><li><u>第二项</u></li></ul>"
    )

    assert cleaned == "<h2>标题</h2><ul><li><b>第一项</b></li><li><u>第二项</u></li></ul>"
    assert plain_text == "标题第一项第二项"


@pytest.mark.asyncio
async def test_email_template_crud_is_scoped_to_site() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        site = Site(
            name="模板测试站",
            domain="mail.example",
            sitemap_url="",
            product_routes=["product"],
        )
        session.add(site)
        await session.commit()
        await session.refresh(site)

        created = await create_email_template(
            site.id,
            EmailTemplateCreate(title="初始标题", content_html="<p>初始正文</p>"),
            session,
        )
        templates = await list_email_templates(site.id, None, session)
        assert [item.id for item in templates] == [created.id]

        updated = await update_email_template(
            site.id,
            created.id,
            EmailTemplateUpdate(title="更新标题", content_html="<p><strong>更新正文</strong></p>"),
            session,
        )
        assert updated.title == "更新标题"
        assert updated.content_html == "<p><strong>更新正文</strong></p>"

        await delete_email_template(site.id, created.id, session)
        assert await list_email_templates(site.id, None, session) == []

    await engine.dispose()
