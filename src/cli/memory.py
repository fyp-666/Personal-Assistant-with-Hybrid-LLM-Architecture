"""Extract and update persistent preferences using the selected model and a local Hermes file."""

import argparse

from app.runtime import create_providers
from core.execution import ProviderError, execute_plan
from core.routing import Privacy, RequestContext, plan_route
from features.memory import render_memory_update, update_user_memory


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="hybrid-assistant memory", description=__doc__
    )
    parser.add_argument("request", help="The preference to remember, change, or forget")
    parser.add_argument(
        "--private", action="store_true", help="Process preferences using Local only"
    )
    args = parser.parse_args(argv)
    try:
        result = update_user_memory(
            args.request,
            generate=lambda prompt: (
                execute_plan(
                    plan_route(
                        RequestContext(
                            privacy=Privacy.SENSITIVE
                            if args.private
                            else Privacy.PUBLIC
                        )
                    ),
                    prompt,
                    create_providers(load_local_context=False),
                ).text
            ),
        )
    except ProviderError as error:
        parser.exit(
            1,
            f"{error}\nThis request was not saved to the user profile.\n",
        )
    except (OSError, UnicodeError):
        parser.exit(
            1,
            "Cannot read or write the user profile. Check USER.md permissions and UTF-8 encoding.\n",
        )
    except ValueError as error:
        parser.error(str(error))

    print(render_memory_update(result))


if __name__ == "__main__":
    main()
