import pendulum
import requests

from github.ContentFile import ContentFile  # type: ignore
from github.Issue import Issue  # type: ignore
from github.IssueComment import IssueComment  # type: ignore
from github.Repository import Repository
from github.InputGitAuthor import InputGitAuthor
from telebot import TeleBot  # type: ignore
from telebot.types import Message  # type: ignore

from config import (
    MyNumber,
    DataDir,
    MyNumberFilenameFormat,
    GithubWorkBranch,
    TimeZone,
    GithubCommitter,
    GithubFileAbsPath,
)

from utils import (
    read_str_as_dict,
    sort_dict_within_list,
    list_to_dict,
    fmt_to_today_utc,
    fmt_utc_to_datetime_str,
    days_until_today,
    github_is_me,
    is_today,
)


def respond_info(bot: TeleBot, message: Message) -> None:
    text = {
        "id": message.from_user.id,
        "username": message.from_user.username,
        "chat_id": message.chat.id,
    }
    bot.reply_to(message, str(text))


def respond_daily(
    bot: TeleBot,
    message: Message,
    repo: Repository,
    github_name: str,
    task: dict,
    cmd_text: str,
):
    labels: list = task.get("label")
    if labels is None:
        bot.reply_to(message, f"labels empty.")
        return

    issues = repo.get_issues(labels=labels, state="all", creator=github_name)
    if issues.totalCount <= 0:
        bot.reply_to(message, f"No issue found associated with the label({labels}).")
        return

    issue: Issue = issues[0]
    today_utc = fmt_to_today_utc(TimeZone)

    # 获取当天issue，避免重复评论
    # 如果当天已经评论过，更新最新评论的内容
    comments = issue.get_comments(since=today_utc)
    my_comments = [
        c
        for c in comments
        if github_is_me(c, github_name) and is_today(c.created_at, TimeZone)
    ]
    if len(my_comments) > 0:
        latest_comment: IssueComment = my_comments[-1]
        latest_text = latest_comment.body.splitlines()[0]
        if latest_text == cmd_text:
            bot.reply_to(
                message,
                f"same comment.({fmt_utc_to_datetime_str(latest_comment.updated_at, TimeZone)})",
            )
            return
        try:
            latest_comment.edit(body=cmd_text)
            bot.reply_to(
                message,
                f"update comment success:\n"
                + f"{fmt_utc_to_datetime_str(latest_comment.updated_at, TimeZone)}\n"
                + f"({latest_text})->({cmd_text})",
            )
        except Exception as e:
            bot.reply_to(message, f"update comment failed: {e}")

        return

    try:
        issue.create_comment(body=cmd_text)
        bot.reply_to(message, "create comment success.")
        if not task.get("skip_readme"):
            respond_my_number_todo(bot, message, repo, github_name)
    except Exception as e:
        bot.reply_to(message, f"create comment failed: {e}")


def respond_github_workflow(
    bot: TeleBot, message: Message, repo: Repository, task: dict
) -> None:
    try:
        workflow_id = task.get("workflow_id")
        ref = task.get("work_branch")
        workflow = repo.get_workflow(workflow_id)
        state = workflow.create_dispatch(ref=ref)
        resp_message = f"GitHub Action '{workflow.name}' triggered successfully. Run state: {state}."
        bot.reply_to(message, resp_message)
    except Exception as e:
        bot.reply_to(message, f"[action triggered] An error may have occurred: {e}")


def respond_my_number_todo(
    bot: TeleBot, message: Message, repo: Repository, github_name: str
) -> None:
    content_file_dict = dict()
    for cf in repo.get_dir_contents(DataDir, ref=GithubWorkBranch):
        content_file_dict.update({cf.name: cf})

    resp_message = []
    do_fmt = "☑{0}"
    todo_fmt = "☐{0}"
    for task, config in MyNumber.items():
        if config.get("skip_readme"):
            continue
        desc: str = config.get("desc")
        task_name = desc.split("_")[-1]

        labels: list = config.get("label")
        if labels is None:
            resp_message.append(todo_fmt.format(task_name))
            return

        issues = repo.get_issues(labels=labels, state="all", creator=github_name)
        if issues.totalCount <= 0:
            resp_message.append(todo_fmt.format(task_name))
            return

        issue: Issue = issues[0]
        today_utc = fmt_to_today_utc(TimeZone)

        comments = issue.get_comments(since=today_utc)
        my_comments = [
            c
            for c in comments
            if github_is_me(c, github_name) and is_today(c.created_at, TimeZone)
        ]
        if len(my_comments) <= 0:
            resp_message.append(todo_fmt.format(task_name))
            continue

        resp_message.append(do_fmt.format(task_name))

    msg = f"{pendulum.today(tz=TimeZone).to_date_string()} MyNumber Todo:\n"
    msg += "\n".join(resp_message)

    msg += "\nexecute if complete:\n"
    msg += "1. /run_daily\n"
    msg += "2. /clock_in_summary\n"

    bot.send_message(message.chat.id, msg)


def respond_clock_in(bot: TeleBot, message: Message, repo: Repository, clock_in: list):
    content_file_dict = dict()
    for cf in repo.get_dir_contents(DataDir, ref=GithubWorkBranch):
        content_file_dict.update({cf.name: cf})

    resp_message = []
    for tag in clock_in:
        config: dict = MyNumber.get(tag)
        if not config:
            print(f"{tag} not found in 'MyNumber'")
            continue

        filename = MyNumberFilenameFormat.format(**config)
        content: ContentFile = content_file_dict.get(filename)
        if content is None:
            print(f"{tag} not found in repo")
            continue

        text = content.decoded_content.decode("utf-8")
        data: dict = read_str_as_dict(text)

        desc: str = config.get("desc")
        name = desc.split("_")[-1]
        resp_message.append(f"{name} {len(data)} 天")

    msg = ", ".join(resp_message) + "."
    bot.reply_to(message, msg)


def respond_clock_in_summary(
    bot: TeleBot, message: Message, repo: Repository, clock_in: list
):
    resp_list = []
    resp_template = "{name}({start_day}): 打卡({win_days})天, 未打卡({fail_days})天\n"

    content_file_dict = dict()
    for cf in repo.get_dir_contents(DataDir, ref=GithubWorkBranch):
        content_file_dict.update({cf.name: cf})

    for tag in clock_in:
        config: dict = MyNumber.get(tag)
        if not config:
            print(f"{tag} not found in 'MyNumber'")
            continue
        if config.get("skip_readme"):
            continue

        filename = MyNumberFilenameFormat.format(**config)
        content: ContentFile = content_file_dict.get(filename)
        if content is None:
            print(f"{tag} not found in repo")
            continue

        text = content.decoded_content.decode("utf-8")
        data = read_str_as_dict(text)

        desc = config.get("desc")
        stat: dict = list_to_dict(["name", "start_day", "win_days", "fail_days"])
        stat["name"] = desc.split("_")[-1]
        stat["start_day"] = list(sorted([i for i in data.keys()]))[0]
        stat["win_days"] = len(data)
        stat["fail_days"] = days_until_today(stat["start_day"]) - stat["win_days"]
        resp_list.append(stat)

    msg = ""
    resp_list = sort_dict_within_list(resp_list, key1="start_day", key2="win_days")
    for stat in resp_list:
        msg += resp_template.format(**stat)

    bot.reply_to(message, msg)


def respond_running(
    bot: TeleBot,
    message: Message,
    repo: Repository,
    github_name: str,
    task: dict,
    cmd,
    cmd_text: str,
):
    need_comment = False
    if cmd_text.startswith("comment"):
        need_comment = True
        cmd_text = cmd_text[len("comment") :].strip()

    labels: list = task.get("label")
    if labels is None:
        bot.reply_to(message, f"labels empty.")
        return

    issues = repo.get_issues(labels=labels, state="all", creator=github_name)
    if issues.totalCount <= 0:
        bot.reply_to(message, f"No issue found associated with the label({labels}).")
        return
    issue: Issue = issues[0]
    if message.photo is None:
        try:
            issue.create_comment(cmd_text)
            bot.reply_to(message, "create comment success.")
        except Exception as e:
            bot.reply_to(message, f"create comment failed: {e}")
        return

    now = pendulum.now(tz=TimeZone)

    repo_rel_path = task.get("path")

    max_size_photo = max(message.photo, key=lambda p: p.file_size)
    max_file_path = bot.get_file(max_size_photo.file_id).file_path
    url = "https://api.telegram.org/file/bot{0}/{1}".format(bot.token, max_file_path)
    file_type = url.split(".")[-1]
    file_name = f"{repo_rel_path}/{now.format('YYYYMMDD-HHmmss')}-{cmd_text.replace(' ', '_')}.{file_type}"

    image_resp = requests.get(url=url)
    if not image_resp.ok:
        msg = f"download image from tg failed: {image_resp.status_code}"
        bot.reply_to(message, msg)
        return

    try:
        result = repo.create_file(
            path=file_name,
            message=f"chore: add {cmd} image",
            content=image_resp.content,
            committer=InputGitAuthor(**GithubCommitter),
            branch=GithubWorkBranch,
        )
    except Exception as e:
        msg = "create file failed."
        bot.reply_to(message, msg)
        return

    if not need_comment:
        bot.reply_to(message, "upload image finished")
        return

    image_url_for_issue = f"{GithubFileAbsPath}/{file_name}?raw=true"
    image_url_for_issue_html = f'<img src="{image_url_for_issue}" width="35%">'
    issue_content = f"{cmd_text}\n{image_url_for_issue_html}"
    try:
        issue.create_comment(issue_content)
    except Exception as e:
        msg = "upload image finished but create comment failed."
        bot.reply_to(message, msg)
        return
    bot.reply_to(message, "upload image finished and create comment success.")
