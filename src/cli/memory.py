"""Extract and update persistent preferences using local Gemma and Hermes."""

import argparse

from core.execution import ProviderError
from features.memory import render_memory_update, update_user_memory


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant memory", description=__doc__
    )
    parser.add_argument("request", help="你希望助手记住、修改或忘记的用户偏好")
    args = parser.parse_args(argv)
    try:
        result = update_user_memory(args.request)
    except ProviderError as error:
        parser.exit(
            1,
            f"{error}\n本次请求未写入用户档案。\n",
        )
    except (OSError, UnicodeError):
        parser.exit(1, "无法读写用户档案，请检查 USER.md 的权限与 UTF-8 编码。\n")
    except ValueError as error:
        parser.error(str(error))

    print(render_memory_update(result))


if __name__ == "__main__":
    main()
