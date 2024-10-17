import argparse
import logging
import os
import sys
import time

import flask
import telebot
import toml  # type: ignore

from github import Github  # type: ignore
from telebot import TeleBot  # type: ignore
from telebot.types import BotCommand, Message  # type: ignore

from config import (
    GithubRepoName,
    MyNumber,
    GithubWorkflow,
    MyClockIn,
    TelegramBotCommandInfo,
    TelegramBotCommadMyNumberTodo,
    RunningPhoto,
)

from utils import (
    sha256_hash,
    is_owner,
    extract_command,
    extract_photo_command,
)

from responder import (
    respond_info,
    respond_clock_in,
    respond_clock_in_summary,
    respond_github_workflow,
    respond_daily,
    respond_my_number_todo,
    respond_running,
)


telebot.logger.setLevel(logging.DEBUG)


def set_bot_commands(bot: TeleBot) -> None:
    bot.delete_my_commands()
    bot.set_my_commands(
        commands=[
            BotCommand(cmd, val.get("desc") + val.get("status_unit_str", ""))
            for cmd, val in MyNumber.items()
        ]
        + [BotCommand(cmd, val.get("desc")) for cmd, val in GithubWorkflow.items()]
        + [BotCommand(cmd, val.get("desc")) for cmd, val in MyClockIn.items()]
        + [
            BotCommand(cmd, val.get("desc"))
            for cmd, val in TelegramBotCommadMyNumberTodo.items()
        ]
        + [
            BotCommand(cmd, val.get("desc"))
            for cmd, val in TelegramBotCommandInfo.items()
        ]
        + [BotCommand(cmd, val.get("desc")) for cmd, val in RunningPhoto.items()]
    )


def exit_based_on_tg_token():
    telebot.logger.error(
        "tg_token is empty. "
        "You should use --tg-token='<your-tg-token>' "
        "or add the environment variable TG_TOKEN='<your-tg-token>' for configuration"
    )
    sys.exit(1)


def exit_based_on_github_token():
    telebot.logger.error(
        "tg_token is empty. "
        "You should use --github-token='<your-github-token>' "
        "or add the environment variable GITHUB_TOKEN='<your-github-token>' for configuration"
    )
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tg-token", dest="tg_token", default="", help="tg token")
    parser.add_argument(
        "--github-token", dest="github_token", default="", help="github token"
    )
    parser.add_argument(
        "--use-webhook",
        default=False,
        dest="use_webhook",
        action="store_true",
        help="use webhook, default using polling",
    )
    options = parser.parse_args()

    tg_token = options.tg_token or os.environ.get("TG_TOKEN")
    if not tg_token:
        exit_based_on_tg_token()

    github_token = options.github_token or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        exit_based_on_github_token()

    use_webhook = options.use_webhook or os.environ.get("USE_WEBHOOK") == "1"

    # Init bot
    bot = TeleBot(tg_token)
    set_bot_commands(bot)
    bot_name = bot.get_me().username
    telebot.logger.info("Bot init done.")

    # Init github
    gh = Github(github_token)
    gh_username = gh.get_user().login
    gh_repo = gh.get_repo(GithubRepoName)
    telebot.logger.info("Github init done.")

    @bot.message_handler(commands=[k for k in TelegramBotCommandInfo.keys()])
    def info_handler(message: Message):
        respond_info(bot, message)

    @bot.message_handler(commands=[k for k in MyClockIn.keys()])
    def clock_in_handler(message: Message):
        cmd, cmd_text = extract_command(message, bot_name)
        if cmd is None:
            return

        task: dict = MyClockIn.get(cmd)
        if task is None:
            bot.reply_to(message, f"{task} config is not found.")
            return

        if not is_owner(message, task.get("allowed_user")):
            telebot.logger.debug(f"For owner use only.({cmd})")
            return

        respond_clock_in_summary(bot, message, gh_repo, task.get("number_names"))

        clock_in_for_me = ["eng_vocabulary", "push_up", "eng_shadowing"]
        respond_clock_in(bot, message, gh_repo, clock_in_for_me)

    @bot.message_handler(commands=[k for k in GithubWorkflow.keys()])
    def github_workflow_handler(message: Message):
        cmd, cmd_text = extract_command(message, bot_name)
        if cmd is None:
            return

        task: dict = GithubWorkflow.get(cmd)
        if task is None:
            bot.reply_to(message, f"{task} config is not found.")
            return

        if not is_owner(message, task.get("allowed_user")):
            telebot.logger.debug(f"For owner use only.({cmd})")
            return

        respond_github_workflow(bot, message, gh_repo, task)

    @bot.message_handler(commands=[k for k in TelegramBotCommadMyNumberTodo.keys()])
    def my_number_todo_handler(message: Message):
        cmd, cmd_text = extract_command(message, bot_name)
        if cmd is None:
            return

        task: dict = TelegramBotCommadMyNumberTodo.get(cmd)
        if task is None:
            bot.reply_to(message, f"{task} config is not found.")
            return

        if not is_owner(message, task.get("allowed_user")):
            telebot.logger.debug(f"For owner use only.({cmd})")
            return

        respond_my_number_todo(bot, message, gh_repo, gh_username)

    @bot.message_handler(commands=[k for k in MyNumber.keys()])
    def daily_handler(message: Message):
        cmd, cmd_text = extract_command(message, bot_name)
        if cmd is None:
            return

        if not cmd_text:
            bot.reply_to(message, "comment is empty.")
            return

        tasks = dict()
        tasks.update(MyNumber)

        task: dict = tasks.get(cmd, {})
        if not any(task):
            bot.reply_to(message, f"task config is not found.")
            return

        if not is_owner(message, task.get("allowed_user")):
            telebot.logger.debug(f"For owner use only.({cmd})")
            return

        respond_daily(bot, message, gh_repo, gh_username, task, cmd_text)

    @bot.message_handler(commands=[k for k in RunningPhoto.keys()])
    @bot.message_handler(content_types=["photo"])
    def running_handler(message: Message) -> None:
        cmd, cmd_text = extract_photo_command(message, bot_name)
        if cmd is None:
            return

        if not cmd_text:
            bot.reply_to(message, "caption is empty.")
            return

        task: dict = RunningPhoto.get(cmd)
        if task is None:
            bot.reply_to(message, f"{task} config is not found.")
            return

        if not is_owner(message, task.get("allowed_user")):
            telebot.logger.debug(f"For owner use only.({cmd})")
            return

        respond_running(bot, message, gh_repo, gh_username, task, cmd, cmd_text)

    if not use_webhook:
        bot.remove_webhook()
        time.sleep(0.5)
        telebot.logger.info("start a bot using infinity_polling ...")
        bot.infinity_polling()
    else:
        fly_io_config = dict()
        with open("fly.toml") as f:
            fly_io_config: dict = toml.load(f)

        listen_port = fly_io_config.get("http_service").get("internal_port")
        webhook_url_base = f"https://{fly_io_config.get('app')}.fly.dev"
        webhook_url_path = f"/{sha256_hash(tg_token)}/"
        webhook_url = webhook_url_base + webhook_url_path

        app = flask.Flask(__name__)

        # Empty webserver index, return nothing, just http 200
        @app.route("/", methods=["GET", "HEAD"])
        def index():
            return ""

        @app.route(webhook_url_path, methods=["POST"])
        def webhook():
            if flask.request.method == "POST":
                json_string = flask.request.get_data().decode("utf-8")
                update = telebot.types.Update.de_json(json_string)
                bot.process_new_updates([update])
                return "", 200
            else:
                flask.abort(403)

        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=webhook_url)

        telebot.logger.info("start a bot using webhook ...")
        app.run(host="0.0.0.0", port=listen_port)


if __name__ == "__main__":
    main()
