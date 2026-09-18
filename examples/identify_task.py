"""识别当前任务并展示执行模型；此命令不执行业务任务。"""

import argparse

from hybrid_assistant.execution import ProviderError
from hybrid_assistant.intent import identify_task
from hybrid_assistant.routing import Privacy, RequestContext, Source, plan_route
from hybrid_assistant.runtime import create_providers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", help="允许发给 GPT 的当前任务描述")
    parser.add_argument(
        "--private", action="store_true", help="本次输入包含私人内容，仅本地识别"
    )
    parser.add_argument("--offline", action="store_true", help="离线运行，仅本地识别")
    args = parser.parse_args()
    context = RequestContext(
        privacy=Privacy.SENSITIVE if args.private else Privacy.PUBLIC,
        source=Source.USER_INPUT,
        offline=args.offline,
    )
    try:
        result = identify_task(
            args.message,
            create_providers(load_local_context=False),
            context=context,
        )
    except ProviderError as error:
        parser.exit(1, f"任务识别失败：{error}\n")
    except ValueError as error:
        parser.error(str(error))
    route = plan_route(result.context)
    print(f"识别模型：{result.classifier.value}（回退：{result.used_fallback}）")
    print(f"任务类型：{result.task.value}")
    print(f"任务复杂度：{result.context.complexity.value}")
    print(f"需要私人上下文：{result.needs_private_context}")
    print(f"执行模型：{route.primary.value}")
    print(f"执行失败时的回退：{', '.join(p.value for p in route.fallbacks) or '无'}")
    print(f"路由依据：{route.reason}")
    print("以上为识别和路由结果，尚未执行业务任务。")


if __name__ == "__main__":
    main()
