"""Summarize a synthetic email with the existing local Gemma profile in WSL."""

from hybrid_assistant.email import Email, render_email_summary, summarize_email
from hybrid_assistant.runtime import create_providers


def main() -> None:
    email = Email(
        sender="课程助教 <ta@example.com>",
        subject="项目演示材料提交",
        body=(
            "请在 2026-09-08 16:00（UTC-07:00）前提交项目演示材料，"
            "需要包含 1 份 PDF 和 2 张截图。请在提交前检查附件能否打开。"
        ),
    )
    providers = create_providers()
    result = summarize_email(email, providers)
    print(f"provider={result.provider.value}, used_fallback={result.used_fallback}")
    print(render_email_summary(email, result.text))


if __name__ == "__main__":
    main()
