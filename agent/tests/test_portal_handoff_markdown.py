from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_repo_file(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_portal_server_rendered_history_is_marked_for_markdown_hydration():
    template = read_repo_file("portal/app/templates/conversation.html")
    script = read_repo_file("portal/app/static/js/conversation.js")

    assert 'class="message-content" data-markdown-content' in template
    assert "renderExistingMarkdownMessages();" in script
    assert "data-markdown-rendered" in script


def test_portal_history_load_does_not_replay_raw_markdown_preview():
    script = read_repo_file("portal/app/static/js/conversation.js")

    assert "The transferred transcript above is rendered" in script
    assert "Loaded ${preHandoffConversation.messages.length} pre-handoff messages:\\n${preview}" not in script


def test_portal_markdown_has_chat_table_styles():
    styles = read_repo_file("portal/app/static/css/conversation.css")

    assert ".message-content table" in styles
    assert ".message-content th" in styles
    assert ".message-content td" in styles
